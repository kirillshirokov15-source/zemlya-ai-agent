from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
from openai import OpenAI

from app.core.config import settings


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MODEL = os.getenv("OPENAI_ENRICHMENT_MODEL", os.getenv("OPENAI_QUALIFICATION_MODEL", "gpt-5.6-luna"))

ENRICHMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "company_name": {"type": ["string", "null"]},
        "legal_name": {"type": ["string", "null"]},
        "inn": {"type": ["string", "null"]},
        "ogrn": {"type": ["string", "null"]},
        "website": {"type": ["string", "null"]},
        "resolution_confidence": {"type": "string", "enum": ["high", "medium", "low", "unresolved"]},
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "role": {"type": ["string", "null"]},
                    "email": {"type": ["string", "null"]},
                    "phone": {"type": ["string", "null"]},
                    "profile_url": {"type": ["string", "null"]},
                    "source_url": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["name", "role", "email", "phone", "profile_url", "source_url", "confidence"],
            },
        },
        "evidence": {"type": "array", "items": {"type": "string"}},
        "unresolved_reason": {"type": ["string", "null"]},
    },
    "required": [
        "company_name", "legal_name", "inn", "ogrn", "website",
        "resolution_confidence", "contacts", "evidence", "unresolved_reason",
    ],
}

SYSTEM_INSTRUCTIONS = """
Ты выполняешь company resolution и contact enrichment для B2B-лида.
Работай только по переданным поисковым результатам.

Критические правила:
1. Ничего не придумывай. Если факт не подтвержден явно – null.
2. Нужно установить именно компанию/инвестора конкретного проекта, а не просто похожую компанию отрасли.
3. ИНН, ОГРН, сайт, ФИО и должности указывай только при явном подтверждении в результатах.
4. Контакт добавляй только если source_url присутствует среди переданных результатов.
5. Приоритет контактов: гендиректор/владелец, директор по развитию, инвестициям,
   строительству, недвижимости/земельным вопросам, затем общий корпоративный контакт.
6. Не объединяй сведения разных одноименных компаний.
7. Для анонимного проекта resolution_confidence=high только при сильном совпадении
   объекта, локации, суммы/сроков и описания проекта.
8. evidence – короткие факты, которые прямо подтверждают выбранную компанию или контакт.
9. Если надежно установить компанию нельзя – resolution_confidence=unresolved.
"""


def _project_query(project: dict[str, Any]) -> str:
    company = project.get("company_name")
    ptype = project.get("project_type") or "инвестиционный проект"
    location = project.get("location") or "Московская область"
    investment = project.get("investment_rub")
    summary = project.get("project_summary") or ""
    if company:
        return f'"{company}" {location} {ptype} генеральный директор контакты инвестиции'
    money = f" {int(investment)} рублей" if isinstance(investment, (int, float)) else ""
    return f'{ptype} {location}{money} инвестор компания {summary[:180]}'


def _contact_query(company: str, location: str | None) -> str:
    return (
        f'"{company}" {location or "Московская область"} '
        'генеральный директор директор по развитию инвестициям строительство контакты email телефон'
    )


async def _tavily(query: str, max_results: int = 6) -> list[dict[str, Any]]:
    if not settings.tavily_api_key:
        return []
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": "advanced",
        "topic": "general",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(TAVILY_SEARCH_URL, json=payload)
    response.raise_for_status()
    return response.json().get("results", [])


def _compact_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for item in results:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "title": item.get("title"),
            "url": url,
            "content": (item.get("content") or "")[:3500],
            "score": item.get("score"),
        })
    return out[:12]


def _empty(status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "company_name": None,
        "legal_name": None,
        "inn": None,
        "ogrn": None,
        "website": None,
        "resolution_confidence": "unresolved",
        "contacts": [],
        "evidence": [],
        "unresolved_reason": reason,
        "search_results": [],
    }


def enrich_project(project: dict[str, Any]) -> dict[str, Any]:
    if not settings.tavily_api_key:
        return {**project, "enrichment": _empty("skipped", "TAVILY_API_KEY is not configured")}
    if not settings.openai_api_key:
        return {**project, "enrichment": _empty("skipped", "OPENAI_API_KEY is not configured")}

    try:
        first = asyncio.run(_tavily(_project_query(project), max_results=7))
        results = list(first)
        known_company = project.get("company_name")
        if known_company:
            second = asyncio.run(_tavily(_contact_query(known_company, project.get("location")), max_results=6))
            results.extend(second)
        compact = _compact_results(results)
        if not compact:
            return {**project, "enrichment": _empty("unresolved", "No enrichment search results")}

        client = OpenAI(api_key=settings.openai_api_key)
        payload = {
            "project": {
                "company_name": project.get("company_name"),
                "project_type": project.get("project_type"),
                "project_summary": project.get("project_summary"),
                "location": project.get("location"),
                "investment_rub": project.get("investment_rub"),
                "stage": project.get("stage"),
            },
            "search_results": compact,
        }
        response = client.responses.create(
            model=MODEL,
            store=False,
            instructions=SYSTEM_INSTRUCTIONS,
            input=json.dumps(payload, ensure_ascii=False),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "company_enrichment",
                    "strict": True,
                    "schema": ENRICHMENT_SCHEMA,
                }
            },
        )
        enrichment = json.loads(response.output_text)
        enrichment["status"] = (
            "resolved" if enrichment.get("resolution_confidence") in {"high", "medium"}
            else "unresolved"
        )
        enrichment["search_results"] = compact
        enriched = dict(project)
        enriched["enrichment"] = enrichment

        # Keep the qualification identity stable for persistence fingerprinting.
        # A resolved identity is stored separately and shown as the display company.
        enriched["resolved_company_name"] = (
            enrichment.get("company_name")
            if enrichment.get("resolution_confidence") in {"high", "medium"}
            else None
        )
        enriched["legal_name"] = enrichment.get("legal_name")
        enriched["inn"] = enrichment.get("inn")
        enriched["ogrn"] = enrichment.get("ogrn")
        enriched["website"] = enrichment.get("website")
        return enriched
    except Exception as exc:
        return {
            **project,
            "enrichment": _empty("error", f"{type(exc).__name__}: {str(exc)[:500]}")
        }


def enrich_projects(
    projects: list[dict[str, Any]],
    *,
    max_projects: int = 10,
    min_project_score: int = 45,
) -> dict[str, Any]:
    ordered = sorted(projects, key=lambda x: x.get("lead_score") or 0, reverse=True)
    enriched: list[dict[str, Any]] = []
    processed = 0

    for project in ordered:
        should_enrich = processed < max_projects and (project.get("lead_score") or 0) >= min_project_score
        if should_enrich:
            enriched.append(enrich_project(project))
            processed += 1
        else:
            enriched.append({
                **project,
                "enrichment": _empty("deferred", "Enrichment budget/score threshold")
            })

    return {
        "input_count": len(projects),
        "processed_count": processed,
        "resolved_count": sum(
            1 for x in enriched
            if (x.get("enrichment") or {}).get("status") == "resolved"
        ),
        "unresolved_count": sum(
            1 for x in enriched
            if (x.get("enrichment") or {}).get("status") in {"unresolved", "error"}
        ),
        "projects": enriched,
    }
