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
    "перечень индустриальных парков",
    "промышленные предприятия московской области",
    "карта индустриальных парков",
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

PAUSED_KEYWORDS = (
    "проект приостановлен",
    "проект заморожен",
    "реализация приостановлена",
)

EXCLUDED_KEYWORDS = (
    "жилой комплекс",
    "жк ",
    "азс",
    "автозаправ",
)

TITLE_STOPWORDS = {
    "в", "на", "и", "по", "для", "из", "с", "со", "к", "от", "до", "за",
    "под", "над", "при", "новый", "новая", "новое", "построят", "строительство",
    "московской", "области", "подмосковье", "подмосковья", "рублей", "млрд",
    "млн", "инвестиции", "проект", "проекты",
}


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


TRUSTED_SOURCE_DOMAINS = (
    "mosreg.ru",
    "gov.ru",
    "tass.ru",
    "ria.ru",
    "interfax.ru",
)

def _is_trusted_source(url: str | None) -> bool:
    domain = _domain(url)
    return any(domain == d or domain.endswith("." + d) for d in TRUSTED_SOURCE_DOMAINS)


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


def _is_moscow_oblast(text: str, location_hint: Any) -> bool:
    combined = text.lower()

    if isinstance(location_hint, str):
        combined += "\n" + location_hint.lower()

    oblast_markers = (
        "московская область",
        "московской области",
        "московскую область",
        "подмосковье",
        "подмосковья",
        "подмосковный",
        "подмосковного",
    )
    return any(marker in combined for marker in oblast_markers)


def _is_moscow_city_only(item: dict[str, Any]) -> bool:
    extraction = item.get("extraction") or {}
    location = str(extraction.get("location_hint") or "").strip().lower()

    # Explicit extracted location "Москва" is outside target geography.
    if location in {"москва", "г. москва", "город москва"}:
        return True

    title = (item.get("title") or "").lower()
    content = (item.get("content") or "").lower()

    # A concrete project explicitly described as being "в Москве" is rejected
    # unless Moscow Oblast is also explicitly tied to that same atomic item.
    moscow_city = (
        " в москве" in f" {title}"
        or " в москве" in f" {content[:1200]}"
        or "локация: москва" in content
    )
    oblast = _is_moscow_oblast(f"{title}\n{content[:1200]}", location)

    return moscow_city and not oblast


def _content_integrity(item: dict[str, Any]) -> tuple[bool, float]:
    """
    Detect obvious search-result/page-content mismatches.
    We do not require perfect title repetition. We only reject when a concrete
    project title has almost no meaningful lexical support in the fetched text.
    """
    title = (item.get("title") or "").lower()
    content = (item.get("content") or "").lower()

    if not title or not content:
        return False, 0.0

    tokens = {
        token
        for token in re.findall(r"[a-zа-яё0-9]{4,}", title)
        if token not in TITLE_STOPWORDS
    }

    # Generic titles cannot be validated safely this way.
    if len(tokens) < 2:
        return True, 1.0

    matched = sum(1 for token in tokens if token in content)
    ratio = matched / len(tokens)

    concrete_marker = _contains_any(title, PROJECT_KEYWORDS)
    if concrete_marker and ratio < 0.20:
        return False, ratio

    return True, ratio


def score_candidate(item: dict[str, Any]) -> dict[str, Any]:
    title = item.get("title") or ""
    content = item.get("content") or ""
    text = f"{title}\n{content}".lower()
    extraction = item.get("extraction") or {}

    score = 0
    reasons: list[str] = []
    quality_reject_reasons: list[str] = []

    if _is_moscow_city_only(item):
        quality_reject_reasons.append("outside_target_region_moscow_city")

    integrity_ok, integrity_ratio = _content_integrity(item)
    if not integrity_ok:
        if _is_trusted_source(item.get("url")):
            reasons.append(
                f"trusted_source_title_content_mismatch:review:{integrity_ratio:.2f}"
            )
        else:
            quality_reject_reasons.append(
                f"title_content_mismatch:{integrity_ratio:.2f}"
            )

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
    if _is_moscow_oblast(text, location_hint):
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
        score -= 30
        reasons.append("generic_article_or_directory:-30")

    if _contains_any(text, COMPLETE_KEYWORDS):
        score -= 35
        reasons.append("likely_completed:-35")

    if _contains_any(text, PAUSED_KEYWORDS):
        score -= 25
        reasons.append("paused_project:-25")

    if _contains_any(text, EXCLUDED_KEYWORDS):
        score -= 50
        reasons.append("excluded_type:-50")

    score = max(0, min(100, int(score)))

    result = dict(item)
    result["prequalification"] = {
        "score": score,
        "reasons": reasons,
        "quality_reject": bool(quality_reject_reasons),
        "quality_reject_reasons": quality_reject_reasons,
        "title_content_integrity_ratio": round(integrity_ratio, 3),
    }
    return result


def rank_candidates(
    items: list[dict[str, Any]],
    max_selected: int = 35,
    minimum_score: int = 20,
) -> dict[str, Any]:
    scored = [score_candidate(item) for item in items]

    quality_rejected = [
        item
        for item in scored
        if (item.get("prequalification") or {}).get("quality_reject")
    ]

    usable = [
        item
        for item in scored
        if not (item.get("prequalification") or {}).get("quality_reject")
    ]

    usable.sort(
        key=lambda x: (
            (x.get("prequalification") or {}).get("score") or 0,
            x.get("score") or 0,
        ),
        reverse=True,
    )

    eligible = [
        item
        for item in usable
        if (item.get("prequalification") or {}).get("score", 0) >= minimum_score
    ]
    below_threshold = [
        item
        for item in usable
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
        "quality_rejected_count": len(quality_rejected),
        "max_selected": max_selected,
        "minimum_score": minimum_score,
        "selected": selected,
        "deferred": deferred,
        "below_threshold": below_threshold,
        "quality_rejected": quality_rejected,
    }
