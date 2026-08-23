from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import settings


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


DEFAULT_DISCOVERY_QUERIES = [
    'Московская область новый завод инвестиции площадка',
    'Подмосковье строительство производства инвестор',
    'Московская область расширение производства новый цех',
    'Подмосковье индустриальный парк новый резидент производство',
    'Московская область логистический комплекс инвестиции строительство',
    'Подмосковье торговый центр инвестиционный проект площадка',
]


class TavilySearchError(RuntimeError):
    pass


async def tavily_search(
    query: str,
    *,
    max_results: int = 10,
    days_back: int = 180,
) -> list[dict[str, Any]]:
    if not settings.tavily_api_key:
        raise TavilySearchError("TAVILY_API_KEY is not configured")

    start_date = (date.today() - timedelta(days=days_back)).isoformat()
    end_date = date.today().isoformat()

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": "advanced",
        "topic": "general",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "start_date": start_date,
        "end_date": end_date,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(TAVILY_SEARCH_URL, json=payload)

    if response.status_code >= 400:
        raise TavilySearchError(
            f"Tavily returned HTTP {response.status_code}: {response.text[:500]}"
        )

    data = response.json()
    return data.get("results", [])


async def run_default_discovery(
    *,
    max_results_per_query: int = 8,
    days_back: int = 180,
) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in DEFAULT_DISCOVERY_QUERIES:
        results = await tavily_search(
            query,
            max_results=max_results_per_query,
            days_back=days_back,
        )

        for item in results:
            url = item.get("url")
            if not url or url in seen_urls:
                continue

            seen_urls.add(url)
            collected.append(
                {
                    "query": query,
                    "title": item.get("title"),
                    "url": url,
                    "content": item.get("content"),
                    "score": item.get("score"),
                    "published_date": item.get("published_date"),
                }
            )

    collected.sort(
        key=lambda item: item.get("score") or 0,
        reverse=True,
    )

    return {
        "queries_used": len(DEFAULT_DISCOVERY_QUERIES),
        "unique_results": len(collected),
        "results": collected,
    }
