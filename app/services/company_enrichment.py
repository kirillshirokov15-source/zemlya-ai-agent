from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from app.core.config import settings


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
MODEL = os.getenv(
    "OPENAI_ENRICHMENT_MODEL",
    os.getenv("OPENAI_QUALIFICATION_MODEL", "gpt-5.6-luna"),
)

OFFICIAL_DOMAINS = (
    "mosreg.ru",
    "gov.ru",
    "nalog.gov.ru",
    "invest.mosreg.ru",
)

RESOLUTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "company_name": {"type": ["string", "null"]},
        "legal_name": {"type": ["string", "null"]},
        "inn": {"type": ["string", "null"]},
        "ogrn": {"type": ["string", "null"]},
        "website": {"type": ["string", "null"]},
        "project_relation_confidence": {
            "type": "string",
            "enum": ["high", "medium", "low", "unresolved"],
        },
        "legal_identity_confidence": {
            "type": "string",
            "enum": ["high", "medium", "low", "unresolved"],
        },
        "project_relation_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fact": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["fact", "source_url"],
            },
        },
        "legal_identity_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fact": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["fact", "source_url"],
            },
        },
        "unresolved_reason": {"type": ["string", "null"]},
    },
    "required": [
        "company_name",
        "legal_name",
        "inn",
        "ogrn",
        "website",
        "project_relation_confidence",
        "legal_identity_confidence",
        "project_relation_evidence",
        "legal_identity_evidence",
        "unresolved_reason",
    ],
}

SYSTEM_INSTRUCTIONS = """
Ты выполняешь строгий Company Resolution для B2B инвестиционного проекта.

Цель – установить юридическое лицо, которое действительно является инвестором,
заказчиком или инициатором КОНКРЕТНОГО проекта.

Правила:
1. Ничего не придумывай. Не заполняй ИНН/ОГРН/сайт по памяти.
2. Похожее название компании не является доказательством.
3. Сначала докажи связь компании с проектом – объект, локация, инвестиции,
   сроки, индустриальный парк или иные уникальные признаки.
4. Затем отдельно докажи юридическую идентичность компании.
5. ИНН и ОГРН указывай только если они явно присутствуют в переданных источниках.
6. Не смешивай бренд, группу компаний и юридическое лицо. company_name может
   быть публичным названием, legal_name – только конкретное юрлицо.
7. Если проект анонимный, high допустим только при очень сильном совпадении
   нескольких уникальных параметров проекта.
8. Если несколько компаний могут подходить – unresolved.
9. Каждый evidence должен ссылаться только на URL из переданных результатов.
10. Не занимайся поиском ЛПР и контактов – это следующий отдельный этап.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain(url: str | None) -> str:
    try:
        return urlparse(url or "").netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _official(url: str | None) -> bool:
    d = _domain(url)
    return any(d == x or d.endswith("." + x) for x in OFFICIAL_DOMAINS)


def _digits(value: Any) -> str | None:
    if value is None:
        return None
    s = re.sub(r"\D", "", str(value))
    return s or None


def valid_inn(value: Any) -> bool:
    inn = _digits(value)
    if not inn:
        return False
    if len(inn) == 10:
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        check = sum(int(inn[i]) * weights[i] for i in range(9)) % 11 % 10
        return check == int(inn[9])
    if len(inn) == 12:
        w11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        w12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        c11 = sum(int(inn[i]) * w11[i] for i in range(10)) % 11 % 10
        c12 = sum(int(inn[i]) * w12[i] for i in range(11)) % 11 % 10
        return c11 == int(inn[10]) and c12 == int(inn[11])
    return False


def valid_ogrn(value: Any) -> bool:
    ogrn = _digits(value)
    if not ogrn:
        return False
    if len(ogrn) == 13:
        return (int(ogrn[:12]) % 11) % 10 == int(ogrn[12])
    if len(ogrn) == 15:
        return (int(ogrn[:14]) % 13) % 10 == int(ogrn[14])
    return False


def _project_payload(project: dict[str, Any]) -> dict[str, Any]:
    return project.get("qualification") or project


def _queries(project: dict[str, Any]) -> list[str]:
    p = _project_payload(project)
    company = p.get("company_name")
    ptype = p.get("project_type") or "производственный проект"
    location = p.get("location") or "Московская область"
    investment = p.get("investment_rub")
    summary = re.sub(r"\s+", " ", str(p.get("project_summary") or "")).strip()
    money = f' "{int(investment)}" инвестиции' if isinstance(investment, (int, float)) else ""

    queries = []
    if company:
        queries.extend([
            f'"{company}" "{location}" {ptype} инвестор проект',
            f'"{company}" ИНН ОГРН официальный сайт',
            f'"{company}" Московская область строительство производство инвестиции',
        ])
    else:
        queries.extend([
            f'"{location}" {ptype}{money} инвестор компания',
            f'{ptype} "{location}" {money} строительство инвестор',
        ])
        if summary:
            # Search on a compact distinctive fragment instead of an LLM-generated
            # full sentence.
            fragment = " ".join(summary.split()[:18])
            queries.append(f'"{fragment}"')

    # Deduplicate while preserving order.
    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:4]


async def _tavily_search(query: str, max_results: int = 6) -> list[dict[str, Any]]:
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


async def _extract(urls: list[str]) -> dict[str, str]:
    if not urls or not settings.tavily_api_key:
        return {}
    headers = {
        "Authorization": f"Bearer {settings.tavily_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "urls": urls[:20],
        "extract_depth": "basic",
        "format": "markdown",
        "include_images": False,
        "timeout": 25,
    }
    async with httpx.AsyncClient(timeout=40) as client:
        response = await client.post(TAVILY_EXTRACT_URL, headers=headers, json=payload)
        response.raise_for_status()
    data = response.json()
    return {
        str(x.get("url")): str(x.get("raw_content") or "")
        for x in data.get("results") or []
        if x.get("url")
    }


def _compact(results: list[dict[str, Any]], extracted: dict[str, str]) -> list[dict[str, Any]]:
    out, seen = [], set()
    # Official sources first, then Tavily score.
    ordered = sorted(
        results,
        key=lambda x: (int(_official(x.get("url"))), float(x.get("score") or 0)),
        reverse=True,
    )
    for item in ordered:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        full = extracted.get(str(url), "")
        content = full if len(full) >= 300 else str(item.get("content") or "")
        out.append({
            "title": item.get("title"),
            "url": url,
            "domain": _domain(url),
            "official_source": _official(url),
            "content": content[:6500],
            "search_score": item.get("score"),
        })
    return out[:14]


def _verification_queries(resolution: dict[str, Any], project: dict[str, Any]) -> list[str]:
    p = _project_payload(project)
    legal = resolution.get("legal_name") or resolution.get("company_name")
    inn = _digits(resolution.get("inn"))
    ogrn = _digits(resolution.get("ogrn"))
    location = p.get("location") or "Московская область"
    ptype = p.get("project_type") or "инвестиционный проект"

    queries = []
    if legal:
        queries.append(f'"{legal}" ИНН ОГРН')
        queries.append(f'"{legal}" "{location}" {ptype}')
    if inn:
        queries.append(f'"{inn}" "{legal or ""}"')
    if ogrn:
        queries.append(f'"{ogrn}" "{legal or ""}"')
    return list(dict.fromkeys(x.strip() for x in queries if x.strip()))[:4]


def _empty(status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "company_name": None,
        "legal_name": None,
        "inn": None,
        "ogrn": None,
        "website": None,
        "resolution_confidence": "unresolved",
        "project_relation_confidence": "unresolved",
        "legal_identity_confidence": "unresolved",
        "project_relation_evidence": [],
        "legal_identity_evidence": [],
        "contacts": [],
        "unresolved_reason": reason,
        "checked_at": _now_iso(),
        "search_results": [],
    }


def _llm_resolve(project: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    client = OpenAI(api_key=settings.openai_api_key)
    p = _project_payload(project)
    response = client.responses.create(
        model=MODEL,
        store=False,
        instructions=SYSTEM_INSTRUCTIONS,
        input=json.dumps({
            "project": {
                "company_name": p.get("company_name"),
                "project_type": p.get("project_type"),
                "project_summary": p.get("project_summary"),
                "location": p.get("location"),
                "investment_rub": p.get("investment_rub"),
                "stage": p.get("stage"),
            },
            "sources": results,
        }, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "company_resolution",
                "strict": True,
                "schema": RESOLUTION_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)


def _finalize(resolution: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    valid_urls = {x.get("url") for x in results}
    relation_evidence = [
        x for x in resolution.get("project_relation_evidence") or []
        if x.get("source_url") in valid_urls
    ]
    legal_evidence = [
        x for x in resolution.get("legal_identity_evidence") or []
        if x.get("source_url") in valid_urls
    ]

    inn = _digits(resolution.get("inn"))
    ogrn = _digits(resolution.get("ogrn"))
    inn_ok = valid_inn(inn) if inn else False
    ogrn_ok = valid_ogrn(ogrn) if ogrn else False

    # Never persist structurally invalid identifiers.
    if inn and not inn_ok:
        inn = None
    if ogrn and not ogrn_ok:
        ogrn = None

    relation_conf = resolution.get("project_relation_confidence") or "unresolved"
    identity_conf = resolution.get("legal_identity_confidence") or "unresolved"

    relation_domains = {_domain(x.get("source_url")) for x in relation_evidence}
    identity_domains = {_domain(x.get("source_url")) for x in legal_evidence}
    official_relation = any(_official(x.get("source_url")) for x in relation_evidence)
    official_identity = any(_official(x.get("source_url")) for x in legal_evidence)

    high = (
        relation_conf == "high"
        and bool(resolution.get("legal_name") or resolution.get("company_name"))
        and bool(inn or ogrn)
        and bool(relation_evidence)
        and bool(legal_evidence)
        and (
            official_relation
            or official_identity
            or len(relation_domains | identity_domains) >= 2
        )
    )
    medium = (
        relation_conf in {"high", "medium"}
        and bool(resolution.get("legal_name") or resolution.get("company_name"))
        and bool(relation_evidence)
        and (
            bool(inn or ogrn)
            or identity_conf in {"high", "medium"}
            or len(relation_domains) >= 2
        )
    )

    confidence = "high" if high else "medium" if medium else "unresolved"
    status = "resolved" if confidence in {"high", "medium"} else "unresolved"

    return {
        "status": status,
        "company_name": resolution.get("company_name") if status == "resolved" else None,
        "legal_name": resolution.get("legal_name") if status == "resolved" else None,
        "inn": inn if status == "resolved" else None,
        "ogrn": ogrn if status == "resolved" else None,
        "website": resolution.get("website") if status == "resolved" else None,
        "resolution_confidence": confidence,
        "project_relation_confidence": relation_conf,
        "legal_identity_confidence": identity_conf,
        "project_relation_evidence": relation_evidence,
        "legal_identity_evidence": legal_evidence,
        "contacts": [],
        "unresolved_reason": (
            resolution.get("unresolved_reason")
            if status == "unresolved"
            else None
        ),
        "identifier_checks": {
            "inn_present": bool(resolution.get("inn")),
            "inn_checksum_valid": inn_ok,
            "ogrn_present": bool(resolution.get("ogrn")),
            "ogrn_checksum_valid": ogrn_ok,
        },
        "checked_at": _now_iso(),
        "search_results": results,
    }


def enrich_project(project: dict[str, Any]) -> dict[str, Any]:
    if not settings.tavily_api_key:
        return {**project, "enrichment": _empty("skipped", "TAVILY_API_KEY is not configured")}
    if not settings.openai_api_key:
        return {**project, "enrichment": _empty("skipped", "OPENAI_API_KEY is not configured")}

    try:
        search_results: list[dict[str, Any]] = []
        for query in _queries(project):
            search_results.extend(asyncio.run(_tavily_search(query, max_results=6)))

        urls = list(dict.fromkeys(
            str(x.get("url")) for x in search_results if x.get("url")
        ))[:20]
        extracted = asyncio.run(_extract(urls))
        compact = _compact(search_results, extracted)
        if not compact:
            return {**project, "enrichment": _empty("unresolved", "No company-resolution sources")}

        first = _llm_resolve(project, compact)

        # Second pass: search specifically for the proposed legal identity.
        verification_results: list[dict[str, Any]] = []
        for query in _verification_queries(first, project):
            verification_results.extend(asyncio.run(_tavily_search(query, max_results=5)))

        if verification_results:
            verify_urls = list(dict.fromkeys(
                str(x.get("url")) for x in verification_results if x.get("url")
            ))[:20]
            verify_extract = asyncio.run(_extract(verify_urls))
            combined = _compact(search_results + verification_results, {**extracted, **verify_extract})
            final_raw = _llm_resolve(project, combined)
        else:
            combined = compact
            final_raw = first

        enrichment = _finalize(final_raw, combined)

        enriched = dict(project)
        enriched["enrichment"] = enrichment
        enriched["resolved_company_name"] = enrichment.get("company_name")
        enriched["legal_name"] = enrichment.get("legal_name")
        enriched["inn"] = enrichment.get("inn")
        enriched["ogrn"] = enrichment.get("ogrn")
        enriched["website"] = enrichment.get("website")
        enriched["company_resolution_confidence"] = enrichment.get("resolution_confidence")
        enriched["company_relation_confidence"] = enrichment.get("project_relation_confidence")
        return enriched
    except Exception as exc:
        return {
            **project,
            "enrichment": _empty("error", f"{type(exc).__name__}: {str(exc)[:500]}"),
            "company_resolution_confidence": "unresolved",
            "company_relation_confidence": "unresolved",
        }


def enrich_projects(
    projects: list[dict[str, Any]],
    *,
    max_projects: int = 20,
    min_project_score: int = 40,
) -> dict[str, Any]:
    ordered = sorted(
        projects,
        key=lambda x: x.get("project_score") or x.get("lead_score") or 0,
        reverse=True,
    )

    enriched: list[dict[str, Any]] = []
    processed = 0
    for project in ordered:
        score = project.get("project_score") or project.get("lead_score") or 0
        if processed < max_projects and score >= min_project_score:
            enriched.append(enrich_project(project))
            processed += 1
        else:
            enriched.append({
                **project,
                "enrichment": _empty("deferred", "Company resolution budget/score threshold"),
                "company_resolution_confidence": "unresolved",
                "company_relation_confidence": "unresolved",
            })

    return {
        "input_count": len(projects),
        "processed_count": processed,
        "resolved_count": sum(
            1 for x in enriched
            if (x.get("enrichment") or {}).get("status") == "resolved"
        ),
        "high_confidence_count": sum(
            1 for x in enriched
            if (x.get("enrichment") or {}).get("resolution_confidence") == "high"
        ),
        "medium_confidence_count": sum(
            1 for x in enriched
            if (x.get("enrichment") or {}).get("resolution_confidence") == "medium"
        ),
        "unresolved_count": sum(
            1 for x in enriched
            if (x.get("enrichment") or {}).get("status") != "resolved"
        ),
        "projects": enriched,
    }
