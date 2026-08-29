from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse


OFFICIAL_DOMAINS = (
    "mosreg.ru",
    "mii.mosreg.ru",
    "mio.mosreg.ru",
    "invest.mosreg.ru",
    "gov.ru",
)

TOP_MEDIA_DOMAINS = (
    "tass.ru",
    "ria.ru",
    "interfax.ru",
    "rbc.ru",
    "kommersant.ru",
    "vedomosti.ru",
)

WEAK_SOURCE_DOMAINS = (
    "vk.com",
    "m.vk.com",
    "youtube.com",
    "youtu.be",
)

LEGAL_FORM_WORDS = {
    "ооо", "ао", "пао", "оао", "зао",
    "компания", "группа", "гк",
}

GENERIC_TITLE_WORDS = {
    "московская", "область", "подмосковье",
    "новый", "новая", "новое", "нового",
    "построят", "построит", "создаст", "создадут",
    "инвестиции", "инвестор", "инвестирует",
    "проект", "производство", "завод",
    "комплекс", "центр",
}

PROJECT_CATEGORY_RULES = (
    ("logistics", ("логист", "склад", "тлц", "транспортно-логист")),
    ("retail", ("торговый центр", "трц", "ритейл")),
    ("industrial", ("производ", "завод", "цех", "спецтехник")),
    ("industrial_park", ("индустриальн", "технопарк")),
)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[«»\"'`]", " ", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_company(value: str | None) -> str:
    text = _normalize_text(value)
    if not text:
        return ""

    tokens = [
        token for token in text.split()
        if token not in LEGAL_FORM_WORDS
    ]
    return " ".join(tokens).strip()


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _source_tier(url: str | None) -> str:
    domain = _domain(url)

    if any(domain == d or domain.endswith("." + d) for d in OFFICIAL_DOMAINS):
        return "A_official"

    if any(domain == d or domain.endswith("." + d) for d in TOP_MEDIA_DOMAINS):
        return "B_top_media"

    if any(domain == d or domain.endswith("." + d) for d in WEAK_SOURCE_DOMAINS):
        return "D_weak"

    return "C_other"


def _source_rank(url: str | None) -> int:
    tier = _source_tier(url)
    return {
        "A_official": 4,
        "B_top_media": 3,
        "C_other": 2,
        "D_weak": 1,
    }[tier]


def _project_category(item: dict[str, Any]) -> str:
    q = item.get("qualification") or {}
    text = _normalize_text(
        " ".join(
            str(x or "")
            for x in (
                q.get("project_type"),
                q.get("project_summary"),
                item.get("title"),
            )
        )
    )

    for category, hints in PROJECT_CATEGORY_RULES:
        if any(hint in text for hint in hints):
            return category

    return "other"


def _location_tokens(item: dict[str, Any]) -> set[str]:
    q = item.get("qualification") or {}
    value = _normalize_text(q.get("location"))
    if not value:
        return set()

    stop = {
        "московская", "область", "подмосковье",
        "городской", "округ", "город", "г",
        "территория", "площадка",
    }
    return {
        token
        for token in value.split()
        if len(token) >= 4 and token not in stop
    }


def _title_tokens(item: dict[str, Any]) -> set[str]:
    value = _normalize_text(item.get("title"))
    return {
        token
        for token in value.split()
        if len(token) >= 4 and token not in GENERIC_TITLE_WORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_project(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
    qa = a.get("qualification") or {}
    qb = b.get("qualification") or {}

    company_a = _normalize_company(qa.get("company_name"))
    company_b = _normalize_company(qb.get("company_name"))

    category_a = _project_category(a)
    category_b = _project_category(b)

    loc_a = _location_tokens(a)
    loc_b = _location_tokens(b)
    location_overlap = bool(loc_a & loc_b)

    title_similarity = _jaccard(_title_tokens(a), _title_tokens(b))

    # Strongest case: the same explicitly named company and the same project
    # category, plus a compatible location or highly similar publication title.
    if company_a and company_b and company_a == company_b:
        if category_a == category_b and (location_overlap or title_similarity >= 0.45):
            return True, "same_company_category_location_or_title"

    # Conservative fallback for sources where the company was not extracted.
    # We only merge when titles are very similar AND category/location agree.
    if title_similarity >= 0.72:
        if category_a == category_b and (location_overlap or not loc_a or not loc_b):
            return True, "high_title_similarity"

    return False, ""


def _source_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "domain": _domain(item.get("url")),
        "source_tier": _source_tier(item.get("url")),
        "search_query": item.get("query"),
        "search_score": item.get("score"),
        "published_date": item.get("published_date"),
        "evidence": (item.get("qualification") or {}).get("evidence") or [],
    }


def _best_value(group: list[dict[str, Any]], field: str) -> Any:
    # Prefer a non-empty value from the strongest source.
    ordered = sorted(
        group,
        key=lambda x: (
            _source_rank(x.get("url")),
            x.get("score") or 0,
        ),
        reverse=True,
    )

    for item in ordered:
        value = (item.get("qualification") or {}).get(field)
        if value not in (None, "", [], {}):
            return value
    return None


def _best_primary(group: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        group,
        key=lambda x: (
            _source_rank(x.get("url")),
            x.get("score") or 0,
        ),
    )


def _merge_group(
    group: list[dict[str, Any]],
    merge_reason: str | None,
) -> dict[str, Any]:
    primary = _best_primary(group)
    primary_q = primary.get("qualification") or {}

    sources = [_source_record(item) for item in group]
    sources.sort(
        key=lambda x: (
            {"A_official": 4, "B_top_media": 3, "C_other": 2, "D_weak": 1}[x["source_tier"]],
            x.get("search_score") or 0,
        ),
        reverse=True,
    )

    verification_questions: list[str] = []
    seen_questions: set[str] = set()
    evidence: list[str] = []
    seen_evidence: set[str] = set()

    for item in group:
        q = item.get("qualification") or {}

        for question in q.get("verification_questions") or []:
            normalized = _normalize_text(question)
            if normalized and normalized not in seen_questions:
                seen_questions.add(normalized)
                verification_questions.append(question)

        for fact in q.get("evidence") or []:
            normalized = _normalize_text(fact)
            if normalized and normalized not in seen_evidence:
                seen_evidence.add(normalized)
                evidence.append(fact)

    company_name = _best_value(group, "company_name")
    project_type = _best_value(group, "project_type")
    location = _best_value(group, "location")
    investment_rub = _best_value(group, "investment_rub")

    return {
        "company_name": company_name,
        "project_type": project_type,
        "project_summary": _best_value(group, "project_summary"),
        "location": location,
        "investment_rub": investment_rub,
        "stage": _best_value(group, "stage") or primary_q.get("stage"),
        "land_status": _best_value(group, "land_status") or primary_q.get("land_status"),
        "signal_status": _best_value(group, "signal_status") or primary_q.get("signal_status"),
        "confidence": _best_value(group, "confidence") or primary_q.get("confidence"),
        "needs_deep_verification": any(
            bool((item.get("qualification") or {}).get("needs_deep_verification"))
            for item in group
        ),
        "verification_questions": verification_questions[:10],
        "evidence": evidence[:15],
        "source_count": len(sources),
        "sources": sources,
        "primary_source": sources[0],
        "deduplication": {
            "merged": len(group) > 1,
            "merged_source_count": len(group),
            "merge_reason": merge_reason,
        },
    }


def deduplicate_qualified_projects(
    qualified: list[dict[str, Any]],
) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []

    for item in qualified:
        matched_index: int | None = None
        matched_reason: str | None = None

        for i, group_info in enumerate(groups):
            # Compare with every member rather than only the group's first item.
            for member in group_info["items"]:
                same, reason = _same_project(item, member)
                if same:
                    matched_index = i
                    matched_reason = reason
                    break

            if matched_index is not None:
                break

        if matched_index is None:
            groups.append({
                "items": [deepcopy(item)],
                "merge_reason": None,
            })
        else:
            groups[matched_index]["items"].append(deepcopy(item))
            if not groups[matched_index]["merge_reason"]:
                groups[matched_index]["merge_reason"] = matched_reason

    projects = [
        _merge_group(group["items"], group["merge_reason"])
        for group in groups
    ]

    # Stronger sources and multi-source projects first, then search relevance.
    projects.sort(
        key=lambda p: (
            p["source_count"],
            {"A_official": 4, "B_top_media": 3, "C_other": 2, "D_weak": 1}.get(
                (p.get("primary_source") or {}).get("source_tier"),
                0,
            ),
            (p.get("primary_source") or {}).get("search_score") or 0,
        ),
        reverse=True,
    )

    return {
        "input_qualified_count": len(qualified),
        "unique_projects_count": len(projects),
        "duplicates_merged_count": len(qualified) - len(projects),
        "multi_source_projects_count": sum(
            1 for p in projects if p["source_count"] > 1
        ),
        "projects": projects,
    }
