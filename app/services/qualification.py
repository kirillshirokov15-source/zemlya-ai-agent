from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from typing import Any

from openai import OpenAI
from app.core.config import settings

MODEL = os.getenv("OPENAI_QUALIFICATION_MODEL", "gpt-5.6-luna")

EXCLUDED_URL_HINTS = ("roomfi.ru", "youtube.com", "youtu.be")

PROJECT_HINTS = (
    "завод", "производств", "цех", "склад", "логистичес",
    "торговый центр", "тц ", "индустриальн", "технопарк",
    "площадк", "инвест", "резидент", "расшир",
)

MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

MONTHS_EN = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

RU_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(MONTHS_RU.keys()) + r")\s+(20\d{2})\b",
    re.IGNORECASE,
)
EN_DATE_PATTERN = re.compile(
    r"\b(" + "|".join(MONTHS_EN.keys()) + r")\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.IGNORECASE,
)
DOT_DATE_PATTERN = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
ISO_DATE_PATTERN = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
YEAR_CONTEXT_PATTERN = re.compile(
    r"(?:к|в|на|до|с)\s+(20\d{2})\s*(?:году|г\.?)?",
    re.IGNORECASE,
)

QUALIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "relevant": {"type": "boolean"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "project_type": {"type": ["string", "null"]},
        "company_name": {"type": ["string", "null"]},
        "project_summary": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "investment_rub": {"type": ["number", "null"]},
        "stage": {"type": "string", "enum": ["A", "B", "V", "G", "unknown"]},
        "land_status": {
            "type": "string",
            "enum": ["confirmed_needed", "high_probability", "unknown", "land_defined"],
        },
        "signal_status": {
            "type": "string",
            "enum": ["confirmed_project", "early_signal", "insufficient_data", "exclude"],
        },
        "exclusion_reason": {"type": ["string", "null"]},
        "needs_deep_verification": {"type": "boolean"},
        "verification_questions": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "relevant", "confidence", "project_type", "company_name",
        "project_summary", "location", "investment_rub", "stage",
        "land_status", "signal_status", "exclusion_reason",
        "needs_deep_verification", "verification_questions", "evidence",
    ],
}

SYSTEM_INSTRUCTIONS = '''
Ты квалифицируешь B2B-лиды для компании, которая помогает инвесторам
подбирать и оформлять земельные участки под инвестиционные проекты
в Московской области.

Правила:
1. Не придумывай факты. Используй только переданный текст.
2. Отсутствие информации об участке не означает, что участка нет.
3. A — проект заявлен, площадка/земля еще не определена.
4. B — территория понятна, но участок выбирается, согласуется или оформляется.
5. V — участок уже определен/предоставлен, строительство еще не началось.
6. G — строительство фактически началось. Такие проекты исключаются.
7. Жилые проекты и АЗС исключаются. Склады, логистика и ТЦ допускаются.
8. Если объект уже открыт, введен или строительство идет — relevant=false.
9. При недостатке данных stage=unknown, land_status=unknown,
   needs_deep_verification=true.
10. evidence — только факты, прямо присутствующие во входном тексте.
11. project_summary — максимум 2 коротких предложения.
12. company_name указывай только если название явно есть в тексте.
13. Если входной текст содержит старую дату, но prefilter не исключил материал,
    не считай проект актуальным без отдельного свежего подтверждения.
'''

def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None

def _extract_dates(text: str) -> list[date]:
    out: list[date] = []
    for m in RU_DATE_PATTERN.finditer(text):
        value = _safe_date(int(m.group(3)), MONTHS_RU[m.group(2).lower()], int(m.group(1)))
        if value:
            out.append(value)
    for m in EN_DATE_PATTERN.finditer(text):
        value = _safe_date(int(m.group(3)), MONTHS_EN[m.group(1).lower()], int(m.group(2)))
        if value:
            out.append(value)
    for m in DOT_DATE_PATTERN.finditer(text):
        value = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if value:
            out.append(value)
    for m in ISO_DATE_PATTERN.finditer(text):
        value = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if value:
            out.append(value)
    return out

def _extract_context_years(text: str) -> list[int]:
    years = []
    current_year = date.today().year
    for m in YEAR_CONTEXT_PATTERN.finditer(text):
        year = int(m.group(1))
        if 2000 <= year <= current_year + 10:
            years.append(year)
    return years

def deterministic_prefilter(item: dict[str, Any], days_back: int = 180) -> dict[str, Any]:
    title = item.get("title") or ""
    content = item.get("content") or ""
    url = (item.get("url") or "").lower()
    text = f"{title}\n{content}".lower()
    reasons: list[str] = []

    if any(x in url for x in EXCLUDED_URL_HINTS):
        reasons.append("excluded_domain")
    if not any(x in text for x in PROJECT_HINTS):
        reasons.append("no_project_signal")
    if "жилой комплекс" in text or re.search(r"\bжк\b", text):
        reasons.append("residential")
    if "азс" in text or "автозаправ" in text:
        reasons.append("gas_station")

    explicit_dates = _extract_dates(text)
    cutoff = date.today() - timedelta(days=days_back)
    newest_date = max(explicit_dates) if explicit_dates else None

    if newest_date and newest_date < cutoff:
        reasons.append("stale_date_detected")

    context_years = _extract_context_years(text)
    newest_context_year = max(context_years) if context_years else None
    if not newest_date and newest_context_year and newest_context_year < date.today().year - 1:
        reasons.append("stale_year_context_detected")

    stale = "stale_date_detected" in reasons or "stale_year_context_detected" in reasons

    hard_reject = any(x in reasons for x in [
        "excluded_domain", "no_project_signal", "residential",
        "gas_station", "stale_date_detected", "stale_year_context_detected",
    ])

    reserve_candidate = stale and not any(x in reasons for x in [
        "excluded_domain", "no_project_signal", "residential", "gas_station"
    ])

    return {
        "hard_reject": hard_reject,
        "reserve_candidate": reserve_candidate,
        "prefilter_reasons": reasons,
        "newest_detected_date": newest_date.isoformat() if newest_date else None,
        "newest_context_year": newest_context_year,
        "cutoff_date": cutoff.isoformat(),
    }

def _excluded_result(item: dict[str, Any], prefilter: dict[str, Any]) -> dict[str, Any]:
    reason = "stale_project_for_reserve" if prefilter.get("reserve_candidate") else ", ".join(prefilter["prefilter_reasons"])
    return {
        **item,
        "prefilter": prefilter,
        "qualification": {
            "relevant": False,
            "confidence": "high",
            "project_type": None,
            "company_name": None,
            "project_summary": None,
            "location": None,
            "investment_rub": None,
            "stage": "unknown",
            "land_status": "unknown",
            "signal_status": "exclude",
            "exclusion_reason": reason,
            "needs_deep_verification": False,
            "verification_questions": [],
            "evidence": [],
        },
    }

def qualify_result(item: dict[str, Any]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    prefilter = deterministic_prefilter(item)
    if prefilter["hard_reject"]:
        return _excluded_result(item, prefilter)

    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "title": item.get("title"),
        "url": item.get("url"),
        "content": (item.get("content") or "")[:7000],
        "search_query": item.get("query"),
        "search_score": item.get("score"),
        "published_date": item.get("published_date"),
        "prefilter": prefilter,
        "today": date.today().isoformat(),
    }

    response = client.responses.create(
        model=MODEL,
        store=False,
        instructions=SYSTEM_INSTRUCTIONS,
        input=json.dumps(payload, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "lead_qualification",
                "strict": True,
                "schema": QUALIFICATION_SCHEMA,
            }
        },
    )

    return {
        **item,
        "prefilter": prefilter,
        "qualification": json.loads(response.output_text),
    }

def qualify_results(results: list[dict[str, Any]], max_llm_items: int = 20) -> dict[str, Any]:
    ordered = sorted(results, key=lambda x: x.get("score") or 0, reverse=True)
    output: list[dict[str, Any]] = []
    llm_used = 0
    stale_filtered = 0
    hard_filtered = 0

    for item in ordered:
        prefilter = deterministic_prefilter(item)

        if prefilter["hard_reject"]:
            if prefilter.get("reserve_candidate"):
                stale_filtered += 1
            else:
                hard_filtered += 1
            output.append(_excluded_result(item, prefilter))
            continue

        if llm_used >= max_llm_items:
            output.append({
                **item,
                "prefilter": prefilter,
                "qualification": {
                    "relevant": False,
                    "confidence": "low",
                    "project_type": None,
                    "company_name": None,
                    "project_summary": None,
                    "location": None,
                    "investment_rub": None,
                    "stage": "unknown",
                    "land_status": "unknown",
                    "signal_status": "insufficient_data",
                    "exclusion_reason": "not_processed_in_llm_limit",
                    "needs_deep_verification": True,
                    "verification_questions": ["Повторно обработать при расширенном лимите."],
                    "evidence": [],
                },
            })
            continue

        output.append(qualify_result(item))
        llm_used += 1

    qualified = [x for x in output if x["qualification"]["relevant"]]
    reserve = [x for x in output if x.get("prefilter", {}).get("reserve_candidate")]

    return {
        "input_results": len(results),
        "llm_items_processed": llm_used,
        "hard_filtered_count": hard_filtered,
        "stale_filtered_count": stale_filtered,
        "reserve_candidate_count": len(reserve),
        "qualified_count": len(qualified),
        "qualified": qualified,
        "reserve_candidates": reserve,
        "all_results": output,
    }
