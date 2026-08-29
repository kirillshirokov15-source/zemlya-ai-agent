from __future__ import annotations

from typing import Any


SOURCE_TIER_POINTS = {
    "A_official": 10,
    "B_top_media": 8,
    "C_other": 5,
    "D_weak": 2,
}

STAGE_POINTS = {
    "A": 25,
    "B": 23,
    "V": 14,
    "unknown": 10,
    "G": 0,
}

LAND_POINTS = {
    "confirmed_needed": 25,
    "high_probability": 20,
    "unknown": 12,
    "land_defined": 5,
}

CONFIDENCE_POINTS = {
    "high": 8,
    "medium": 5,
    "low": 2,
}

SIGNAL_POINTS = {
    "confirmed_project": 7,
    "early_signal": 4,
    "insufficient_data": 1,
    "exclude": 0,
}


def _investment_points(value: Any) -> int:
    if not isinstance(value, (int, float)) or value <= 0:
        # Unknown investment should not kill an otherwise strong early lead.
        return 4

    if value >= 10_000_000_000:
        return 15
    if value >= 3_000_000_000:
        return 13
    if value >= 1_000_000_000:
        return 11
    if value >= 300_000_000:
        return 9
    if value >= 100_000_000:
        return 6
    return 3


def _corroboration_points(project: dict[str, Any]) -> int:
    count = int(project.get("source_count") or 0)

    if count >= 3:
        return 5
    if count == 2:
        return 4
    if count == 1:
        return 1
    return 0


def _completeness_points(project: dict[str, Any]) -> tuple[int, dict[str, bool]]:
    checks = {
        "company_known": bool(project.get("company_name")),
        "location_known": bool(project.get("location")),
        "project_type_known": bool(project.get("project_type")),
        "investment_known": isinstance(project.get("investment_rub"), (int, float))
        and project.get("investment_rub") > 0,
        "stage_known": project.get("stage") not in (None, "", "unknown"),
    }

    # Maximum 5 points – one for every usable sales field.
    return sum(1 for value in checks.values() if value), checks


def _priority_label(score: int) -> str:
    if score >= 80:
        return "A_priority"
    if score >= 65:
        return "B_strong"
    if score >= 50:
        return "C_verify"
    return "D_low"


def _recommended_action(project: dict[str, Any], score: int) -> str:
    if score >= 80:
        return "deep_verify_now"
    if score >= 65:
        return "verify_and_enrich"
    if score >= 50:
        return "verify_if_capacity"
    return "keep_low_priority"


def score_project(project: dict[str, Any]) -> dict[str, Any]:
    stage = project.get("stage") or "unknown"
    land_status = project.get("land_status") or "unknown"
    confidence = project.get("confidence") or "low"
    signal_status = project.get("signal_status") or "insufficient_data"

    primary_source = project.get("primary_source") or {}
    source_tier = primary_source.get("source_tier") or "C_other"

    stage_score = STAGE_POINTS.get(stage, 10)
    land_score = LAND_POINTS.get(land_status, 12)
    investment_score = _investment_points(project.get("investment_rub"))
    source_score = SOURCE_TIER_POINTS.get(source_tier, 5)
    corroboration_score = _corroboration_points(project)
    confidence_score = CONFIDENCE_POINTS.get(confidence, 2)
    signal_score = SIGNAL_POINTS.get(signal_status, 1)
    completeness_score, completeness = _completeness_points(project)

    total = (
        stage_score
        + land_score
        + investment_score
        + source_score
        + corroboration_score
        + confidence_score
        + signal_score
        + completeness_score
    )

    # Safety cap – score model is designed for 0..100.
    total = max(0, min(100, int(total)))

    scored = dict(project)
    scored["lead_score"] = total
    scored["priority"] = _priority_label(total)
    scored["recommended_action"] = _recommended_action(project, total)
    scored["score_breakdown"] = {
        "stage": {
            "value": stage,
            "points": stage_score,
            "max_points": 25,
        },
        "land_need": {
            "value": land_status,
            "points": land_score,
            "max_points": 25,
        },
        "investment": {
            "value_rub": project.get("investment_rub"),
            "points": investment_score,
            "max_points": 15,
        },
        "primary_source": {
            "tier": source_tier,
            "points": source_score,
            "max_points": 10,
        },
        "corroboration": {
            "source_count": project.get("source_count") or 0,
            "points": corroboration_score,
            "max_points": 5,
        },
        "confidence": {
            "value": confidence,
            "points": confidence_score,
            "max_points": 8,
        },
        "signal": {
            "value": signal_status,
            "points": signal_score,
            "max_points": 7,
        },
        "data_completeness": {
            "checks": completeness,
            "points": completeness_score,
            "max_points": 5,
        },
    }

    return scored


def score_projects(projects: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [score_project(project) for project in projects]

    scored.sort(
        key=lambda x: (
            x.get("lead_score") or 0,
            x.get("source_count") or 0,
            (x.get("primary_source") or {}).get("search_score") or 0,
        ),
        reverse=True,
    )

    return {
        "projects_scored_count": len(scored),
        "priority_counts": {
            "A_priority": sum(1 for x in scored if x["priority"] == "A_priority"),
            "B_strong": sum(1 for x in scored if x["priority"] == "B_strong"),
            "C_verify": sum(1 for x in scored if x["priority"] == "C_verify"),
            "D_low": sum(1 for x in scored if x["priority"] == "D_low"),
        },
        "projects": scored,
    }
