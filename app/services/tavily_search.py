from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import settings


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilySearchError(RuntimeError):
    pass


class TavilyUsageLimitError(TavilySearchError):
    pass


DEFAULT_QUERIES = [
    "Московская область новый завод инвестиции площадка производство",
    "Подмосковье строительство производства инвестор земельный участок",
    "Московская область новый логистический производственно складской комплекс инвестор",
    "Подмосковье индустриальный парк новый резидент производство инвестиции",
]


async def tavily_search(
    query: str,
    *,
    max_results: int = 6,
    days_back: int = 180,
    search_depth: str = "basic",
) -> list[dict[str, Any]]:
    if not settings.tavily_api_key:
        raise TavilySearchError("TAVILY_API_KEY is not configured")

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days_back)

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": search_depth,
        "topic": "general",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(TAVILY_SEARCH_URL, json=payload)

    if response.status_code == 432:
        raise TavilyUsageLimitError(
            f"Tavily usage limit reached: {response.text[:500]}"
        )

    if response.status_code >= 400:
        raise TavilySearchError(
            f"Tavily returned HTTP {response.status_code}: {response.text[:500]}"
        )

    results = response.json().get("results") or []
    normalized = []
    for item in results:
        row = dict(item)
        row["query"] = query
        normalized.append(row)
    return normalized


async def run_default_discovery(
    *,
    max_results_per_query: int = 6,
    days_back: int = 180,
) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    queries_used: list[str] = []
    quota_exhausted = False
    quota_error = None

    for query in DEFAULT_QUERIES:
        try:
            rows = await tavily_search(
                query,
                max_results=max_results_per_query,
                days_back=days_back,
                search_depth="basic",
            )
            collected.extend(rows)
            queries_used.append(query)
        except TavilyUsageLimitError as exc:
            quota_exhausted = True
            quota_error = str(exc)
            # Stop immediately – do not spend time on more guaranteed failures.
            break

    # URL dedupe.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in collected:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)

    return {
        "queries_used": queries_used,
        "results": deduped,
        "raw_results_count": len(collected),
        "unique_results": len(deduped),
        "quota_exhausted": quota_exhausted,
        "quota_error": quota_error,
        "planned_queries_count": len(DEFAULT_QUERIES),
        "completed_queries_count": len(queries_used),
    }
