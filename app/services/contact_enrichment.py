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
from app.services.contact_cache import get_cached_contacts, set_cached_contacts


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
MODEL = os.getenv(
    "OPENAI_ENRICHMENT_MODEL",
    os.getenv("OPENAI_QUALIFICATION_MODEL", "gpt-5.6-luna"),
)

CONTACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
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
                    "contact_type": {
                        "type": "string",
                        "enum": ["decision_maker", "executive", "company_general", "other"],
                    },
                    "reason_relevant": {"type": "string"},
                },
                "required": [
                    "name", "role", "email", "phone", "profile_url", "source_url",
                    "confidence", "contact_type", "reason_relevant"
                ],
            },
        },
        "general_company_email": {"type": ["string", "null"]},
        "general_company_phone": {"type": ["string", "null"]},
        "general_contact_source_url": {"type": ["string", "null"]},
    },
    "required": [
        "contacts", "general_company_email", "general_company_phone",
        "general_contact_source_url"
    ],
}

SYSTEM = """
Ты извлекаешь B2B-контакты для отдела продаж.

Компания уже установлена предыдущим Company Resolution. Твоя задача – найти
только публично опубликованные деловые контакты, которые относятся именно
к этому юридическому лицу или его подтвержденному официальному сайту.

Приоритет ЛПР:
1. собственник / бенефициар / генеральный директор;
2. директор по развитию / инвестициям;
3. директор по строительству / недвижимости / земельным вопросам;
4. руководитель проекта;
5. если ЛПР нет – общий корпоративный телефон/email.

Строгие правила:
– не придумывай имя, должность, телефон или email;
– не генерируй email по шаблону;
– не смешивай одноименные компании;
– источник должен быть среди переданных URL;
– телефон/email должны явно присутствовать в источнике;
– личные бытовые контакты не нужны, только публичные деловые;
– contact_type=decision_maker только для роли, способной влиять на проект;
– если найден только генеральный директор без прямого контакта, сохрани его,
  но не выдавай выдуманный телефон/email;
– если есть общий корпоративный контакт, сохрани его отдельно.
"""


def _domain(url: str | None) -> str:
    try:
        return urlparse(url or "").netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _queries(project: dict[str, Any]) -> list[str]:
    e = project.get("enrichment") or {}
    legal = e.get("legal_name") or project.get("legal_name")
    company = e.get("company_name") or project.get("resolved_company_name") or project.get("company_name")
    inn = e.get("inn") or project.get("inn")
    website = e.get("website") or project.get("website")

    name = legal or company
    if not name:
        return []

    q = [
        f'"{name}" генеральный директор контакты',
        f'"{name}" директор по развитию инвестициям строительство',
        f'"{name}" телефон email контакты',
    ]
    if inn:
        q.append(f'"{inn}" директор контакты')
    if website:
        domain = _domain(website)
        if domain:
            q.append(f'site:{domain} контакты руководство директор')
    return list(dict.fromkeys(q))[:5]


async def _search(q: str) -> list[dict[str, Any]]:
    if not settings.tavily_api_key:
        return []
    payload = {
        "api_key": settings.tavily_api_key,
        "query": q,
        "search_depth": "advanced",
        "topic": "general",
        "max_results": 6,
        "include_answer": False,
        "include_raw_content": False,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(TAVILY_SEARCH_URL, json=payload)
        r.raise_for_status()
    return r.json().get("results") or []


async def _extract(urls: list[str]) -> dict[str, str]:
    if not urls:
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
        r = await client.post(TAVILY_EXTRACT_URL, headers=headers, json=payload)
        r.raise_for_status()
    return {
        str(x.get("url")): str(x.get("raw_content") or "")
        for x in (r.json().get("results") or [])
        if x.get("url")
    }


def _normalize_phone(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) < 10 or len(digits) > 15:
        return None
    return s


def _normalize_email(value: Any) -> str | None:
    if not value:
        return None
    s = str(value).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        return None
    return s


def _run_llm(project: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    client = OpenAI(api_key=settings.openai_api_key)
    e = project.get("enrichment") or {}
    response = client.responses.create(
        model=MODEL,
        store=False,
        instructions=SYSTEM,
        input=json.dumps({
            "company": {
                "company_name": e.get("company_name") or project.get("resolved_company_name"),
                "legal_name": e.get("legal_name") or project.get("legal_name"),
                "inn": e.get("inn") or project.get("inn"),
                "ogrn": e.get("ogrn") or project.get("ogrn"),
                "website": e.get("website") or project.get("website"),
                "resolution_confidence": e.get("resolution_confidence"),
            },
            "project": {
                "project_type": project.get("project_type"),
                "location": project.get("location"),
                "project_summary": project.get("project_summary"),
            },
            "sources": sources,
        }, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "company_contacts",
                "strict": True,
                "schema": CONTACT_SCHEMA,
            }
        },
    )
    return json.loads(response.output_text)


def enrich_contacts(project: dict[str, Any]) -> dict[str, Any]:
    e = project.get("enrichment") or {}
    if e.get("status") != "resolved":
        return {**project, "contact_enrichment": {"status": "skipped", "contacts": []}}

    inn = e.get("inn") or project.get("inn")
    legal_name = e.get("legal_name") or project.get("legal_name")

    cached = get_cached_contacts(inn)
    if cached:
        out = dict(project)
        out["contact_enrichment"] = cached
        merged_e = dict(e)
        merged_e["contacts"] = cached.get("contacts") or []
        merged_e["general_company_email"] = cached.get("general_company_email")
        merged_e["general_company_phone"] = cached.get("general_company_phone")
        out["enrichment"] = merged_e
        return out

    queries = _queries(project)
    if not queries:
        return {**project, "contact_enrichment": {"status": "skipped", "contacts": []}}

    try:
        results: list[dict[str, Any]] = []
        for q in queries:
            results.extend(asyncio.run(_search(q)))

        unique = {}
        for x in results:
            if x.get("url"):
                unique[str(x["url"])] = x
        selected = list(unique.values())[:20]
        extracted = asyncio.run(_extract(list(unique.keys())[:20]))

        sources = []
        for x in selected:
            url = str(x.get("url"))
            content = extracted.get(url) or str(x.get("content") or "")
            sources.append({
                "title": x.get("title"),
                "url": url,
                "domain": _domain(url),
                "content": content[:7000],
            })

        if not sources:
            return {**project, "contact_enrichment": {"status": "not_found", "contacts": []}}

        raw = _run_llm(project, sources)
        allowed_urls = {x["url"] for x in sources}
        clean = []
        seen = set()

        for c in raw.get("contacts") or []:
            if c.get("source_url") not in allowed_urls:
                continue
            email = _normalize_email(c.get("email"))
            phone = _normalize_phone(c.get("phone"))
            name = (c.get("name") or "").strip() or None
            role = (c.get("role") or "").strip() or None
            if not (name or email or phone):
                continue
            key = (name or "", role or "", email or "", phone or "")
            if key in seen:
                continue
            seen.add(key)
            clean.append({
                **c,
                "name": name,
                "role": role,
                "email": email,
                "phone": phone,
            })

        # Rank actionable contacts first.
        type_rank = {"decision_maker": 0, "executive": 1, "company_general": 2, "other": 3}
        conf_rank = {"high": 0, "medium": 1, "low": 2}
        clean.sort(key=lambda c: (
            type_rank.get(c.get("contact_type"), 9),
            0 if (c.get("phone") or c.get("email")) else 1,
            conf_rank.get(c.get("confidence"), 9),
        ))

        general_email = _normalize_email(raw.get("general_company_email"))
        general_phone = _normalize_phone(raw.get("general_company_phone"))
        general_source = raw.get("general_contact_source_url")
        if general_source not in allowed_urls:
            general_source = None
            general_email = None
            general_phone = None

        status = "resolved" if clean or general_email or general_phone else "not_found"
        ce = {
            "status": status,
            "contacts": clean[:8],
            "general_company_email": general_email,
            "general_company_phone": general_phone,
            "general_contact_source_url": general_source,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        out = dict(project)
        out["contact_enrichment"] = ce

        # Preserve the existing persistence contract: contacts are stored from enrichment.contacts.
        merged_e = dict(e)
        merged_e["contacts"] = clean[:8]
        merged_e["general_company_email"] = general_email
        merged_e["general_company_phone"] = general_phone
        out["enrichment"] = merged_e
        set_cached_contacts(inn, legal_name, ce)
        return out

    except Exception as exc:
        return {
            **project,
            "contact_enrichment": {
                "status": "error",
                "contacts": [],
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            },
        }


def enrich_project_contacts(
    projects: list[dict[str, Any]],
    *,
    max_projects: int = 10,
    min_project_score: int = 55,
) -> dict[str, Any]:
    ordered = sorted(
        projects,
        key=lambda p: p.get("project_score") or p.get("lead_score") or 0,
        reverse=True,
    )

    output: list[dict[str, Any]] = []
    processed = 0
    run_cache: dict[str, dict[str, Any]] = {}

    for p in ordered:
        score = p.get("project_score") or p.get("lead_score") or 0
        e = p.get("enrichment") or {}
        resolved = e.get("status") == "resolved"
        inn = e.get("inn") or p.get("inn")

        if inn and inn in run_cache:
            cached_project = dict(p)
            ce = dict(run_cache[inn])
            cached_project["contact_enrichment"] = ce
            merged_e = dict(e)
            merged_e["contacts"] = ce.get("contacts") or []
            merged_e["general_company_email"] = ce.get("general_company_email")
            merged_e["general_company_phone"] = ce.get("general_company_phone")
            cached_project["enrichment"] = merged_e
            output.append(cached_project)
            continue

        if processed < max_projects and score >= min_project_score and resolved:
            enriched = enrich_contacts(p)
            output.append(enriched)
            processed += 1
            if inn and enriched.get("contact_enrichment"):
                run_cache[inn] = dict(enriched["contact_enrichment"])
        else:
            output.append(p)

    return {
        "processed_count": processed,
        "with_contacts_count": sum(
            1 for p in output
            if (p.get("contact_enrichment") or {}).get("status") == "resolved"
        ),
        "with_direct_contact_count": sum(
            1 for p in output
            if any(
                c.get("phone") or c.get("email")
                for c in ((p.get("contact_enrichment") or {}).get("contacts") or [])
            )
        ),
        "cache_hit_count": sum(
            1 for p in output
            if (p.get("contact_enrichment") or {}).get("cache_hit") is True
        ),
        "projects": output,
    }
