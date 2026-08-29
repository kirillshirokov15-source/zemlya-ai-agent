from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


SOURCE_POINTS = {
    "tass.ru": 10,
    "ria.ru": 10,
    "interfax.ru": 10,
    "kommersant.ru": 10,
    "rbc.ru": 9,
    "vedomosti.ru": 9,
    "mosreg.ru": 10,
    "invest.mosreg.ru": 10,
    "mii.mosreg.ru": 10,
    "minpromtorg.gov.ru": 10,
    "mosreginvest.ru": 9,
    "bbgl.ru": 6,
}

PROJECT_KEYWORDS = (
    "завод",
    "производств",
    "фабрик",
    "цех",
    "комплекс",
    "склад",
    "логист",
    "индустриальн",
    "кластер",
    "центр",
    "корпус",
    "предприят",
)

LAND_NEED_KEYWORDS = (
    "подбирает площадку",
    "подбор площадки",
    "подбирает участок",
    "земельный участок",
    "подготовка стройплощадки",
    "проектирование",
    "планирует построить",
    "планируется строительство",
    "будет построен",
    "создание",
)

BAD_GENERIC_KEYWORDS = (
    "более 2,3 тысячи",
    "более 2300",
    "тысячи инвестиционных проектов",
    "инвестпроекты почти на",
    "итоги года",
    "всего проектов",
)

COMPLETE_KEYWORDS = (
    "введен в эксплуатацию",
    "введён в эксплуатацию",
    "открылся",
    "запущен в работу",
    "строительство завершено",
    "объект завершен",
    "объект завершён",
)

EXCLUDED_KEYWORDS = (
    "жилой комплекс",
    "жк ",
    "азс",
    "автозаправ",
)


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _source_points(url: str | None) -> int:
    domain = _domain(url)
    for known, points in SOURCE_POINTS.items():
        if domain == known or domain.endswith("." + known):
            return points
    return 5


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _investment_hint(item: dict[str, Any]) -> float | None:
    extraction = item.get("extraction") or {}
    value = extraction.get("investment_rub_hint")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _company_hint(item: dict[str, Any]) -> str | None:
    extraction = item.get("extraction") or {}
    value = extraction.get("company_name_hint")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def score_candidate(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title") or ""
    content = item.get("content") or ""
    text = f"{title}\n{content}".lower()
    extraction = item.get("extraction") or {}

    score = 0
    reasons: list[str] = []

    # Tavily is useful but should not dominate business priority.
    tavily_score = item.get("score")
    if isinstance(tavily_score, (int, float)):
        pts = min(12, max(0, round(float(tavily_score) * 12)))
        score += pts
        reasons.append(f"search_relevance:+{pts}")

    source_pts = _source_points(item.get("url"))
    score += source_pts
    reasons.append(f"source_quality:+{source_pts}")

    if _contains_any(text, PROJECT_KEYWORDS):
        score += 14
        reasons.append("specific_project_signal:+14")

    if _contains_any(text, LAND_NEED_KEYWORDS):
        score += 20
        reasons.append("land_or_early_stage_signal:+20")

    if _company_hint(item):
        score += 12
        reasons.append("company_known:+12")

    location_hint = extraction.get("location_hint")
    if (
        "московск" in text
        or "подмосков" in text
        or (isinstance(location_hint, str) and location_hint.strip())
    ):
        score += 8
        reasons.append("moscow_region_signal:+8")

    investment = _investment_hint(item)
    if investment is not None:
        if investment >= 1_000_000_000:
            pts = 10
        elif investment >= 300_000_000:
            pts = 8
        elif investment >= 100_000_000:
            pts = 5
        else:
            pts = 2
        score += pts
        reasons.append(f"investment_signal:+{pts}")

    if extraction.get("was_split"):
        score += 5
        reasons.append("atomic_extracted_project:+5")

    if _contains_any(text, BAD_GENERIC_KEYWORDS):
        score -= 25
        reasons.append("generic_article:-25")

    if _contains_any(text, COMPLETE_KEYWORDS):
        score -= 35
        reasons.append("likely_completed:-35")

    if _contains_any(text, EXCLUDED_KEYWORDS):
        score -= 50
        reasons.append("excluded_type:-50")

    score = max(0, min(100, int(score)))

    result = dict(item)
    result["prequalification"] = {
        "score": score,
        "reasons": reasons,
    }
    return result


def rank_candidates(
    items: list[dict[str, Any]],
    max_selected: int = 35,
    minimum_score: int = 20,
) -> dict[str, Any]:
    scored = [score_candidate(item) for item in items]

    scored.sort(
        key=lambda x: (
            (x.get("prequalification") or {}).get("score") or 0,
            x.get("score") or 0,
        ),
        reverse=True,
    )

    eligible = [
        item
        for item in scored
        if (item.get("prequalification") or {}).get("score", 0) >= minimum_score
    ]
    below_threshold = [
        item
        for item in scored
        if (item.get("prequalification") or {}).get("score", 0) < minimum_score
    ]

    selected = eligible[:max_selected]
    deferred = eligible[max_selected:]

    return {
        "input_count": len(items),
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "deferred_count": len(deferred),
        "below_threshold_count": len(below_threshold),
        "max_selected": max_selected,
        "minimum_score": minimum_score,
        "selected": selected,
        "deferred": deferred,
        "below_threshold": below_threshold,
    }
