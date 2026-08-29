from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx


TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


def _chunks(values: list[str], size: int = 20):
    for i in range(0, len(values), size):
        yield values[i:i + size]


async def _extract_batch(urls: list[str], depth: str) -> dict[str, str]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "urls": urls,
        "extract_depth": depth,
        "format": "markdown",
        "include_images": False,
        "include_usage": True,
        "timeout": 30,
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(TAVILY_EXTRACT_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    return {
        str(row.get("url")): str(row.get("raw_content") or "")
        for row in (data.get("results") or [])
        if row.get("url") and row.get("raw_content")
    }


async def enrich_search_results_with_full_pages(
    items: list[dict[str, Any]],
    *,
    max_urls: int = 45,
    extract_depth: str = "basic",
    min_content_chars: int = 500,
    max_content_chars: int = 45000,
) -> dict[str, Any]:
    """
    Search snippets are useful for discovery but unsafe for final project
    extraction. Fetch the actual page for the strongest candidates and replace
    `content` with clean full-page content while preserving `search_snippet`.
    """
    selected = [x for x in items if x.get("url")][:max_urls]
    urls = list(dict.fromkeys(str(x["url"]) for x in selected))

    extracted: dict[str, str] = {}
    failed_batches = 0

    for batch in _chunks(urls, 20):
        try:
            extracted.update(await _extract_batch(batch, extract_depth))
        except Exception:
            failed_batches += 1

    results: list[dict[str, Any]] = []
    success_count = 0
    fallback_count = 0

    for item in items:
        out = dict(item)
        original = str(item.get("content") or "")
        full = extracted.get(str(item.get("url") or ""), "")

        out["search_snippet"] = original
        if len(full.strip()) >= min_content_chars:
            out["content"] = full[:max_content_chars]
            out["content_source"] = "tavily_extract_full_page"
            out["full_page_chars"] = len(full)
            success_count += 1
        else:
            out["content_source"] = "search_snippet_fallback"
            out["full_page_chars"] = 0
            fallback_count += 1

        results.append(out)

    return {
        "input_count": len(items),
        "urls_requested": len(urls),
        "full_page_success_count": success_count,
        "snippet_fallback_count": fallback_count,
        "failed_batches": failed_batches,
        "extract_depth": extract_depth,
        "results": results,
    }


def enrich_search_results_with_full_pages_sync(
    items: list[dict[str, Any]], **kwargs: Any
) -> dict[str, Any]:
    return asyncio.run(enrich_search_results_with_full_pages(items, **kwargs))
