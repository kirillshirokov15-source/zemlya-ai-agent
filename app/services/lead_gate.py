from __future__ import annotations

from typing import Any


MOSCOW_REGION_MARKERS = (
    "московская область",
    "московской области",
    "подмосковье",
    "подмосковья",
    "подмосковн",
)

PAUSED_MARKERS = (
    "приостановлен",
    "приостановлена",
    "приостановлено",
    "заморожен",
    "заморожена",
    "реализация приостановлена",
)

COMPLETED_MARKERS = (
    "введен в эксплуатацию",
    "введён в эксплуатацию",
    "запущен в работу",
    "строительство завершено",
    "объект завершен",
    "объект завершён",
)


def _q(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("qualification") or {}


def _combined_text(item: dict[str, Any]) -> str:
    qualification = _q(item)
    evidence = qualification.get("evidence") or []
    parts = [
        item.get("title") or "",
        item.get("content") or "",
        qualification.get("project_summary") or "",
        qualification.get("location") or "",
        " ".join(str(x) for x in evidence),
    ]
    return "\n".join(parts).lower()


def _has_moscow_region(item: dict[str, Any]) -> bool:
    location = str(_q(item).get("location") or "").lower()
    if any(marker in location for marker in MOSCOW_REGION_MARKERS):
        return True

    extraction = item.get("extraction") or {}
    location_hint = str(extraction.get("location_hint") or "").lower()
    if any(marker in location_hint for marker in MOSCOW_REGION_MARKERS):
        return True

    # Use title/content only as secondary explicit evidence.
    text = _combined_text(item)
    return any(marker in text for marker in MOSCOW_REGION_MARKERS)


def classify_lead(item: dict[str, Any]) -> dict[str, Any]:
    qualification = _q(item)
    text = _combined_text(item)

    active_reasons: list[str] = []
    verification_reasons: list[str] = []
    reject_reasons: list[str] = []

    if not qualification.get("relevant"):
        reject_reasons.append("qualification_not_relevant")

    if qualification.get("signal_status") == "exclude":
        reject_reasons.append("qualification_excluded")

    if qualification.get("stage") == "G":
        reject_reasons.append("construction_started_or_completed")

    if any(marker in text for marker in COMPLETED_MARKERS):
        reject_reasons.append("completed_project_signal")

    if not _has_moscow_region(item):
        verification_reasons.append("moscow_region_not_confirmed")

    if not qualification.get("project_type"):
        verification_reasons.append("project_type_not_confirmed")

    if qualification.get("signal_status") == "insufficient_data":
        verification_reasons.append("insufficient_project_data")

    if qualification.get("confidence") == "low":
        verification_reasons.append("low_confidence")

    if any(marker in text for marker in PAUSED_MARKERS):
        verification_reasons.append("project_paused")

    if qualification.get("company_name"):
        active_reasons.append("company_known")

    if qualification.get("location"):
        active_reasons.append("location_known")

    if qualification.get("project_type"):
        active_reasons.append("project_type_known")

    if qualification.get("signal_status") == "confirmed_project":
        active_reasons.append("confirmed_project_signal")

    if reject_reasons:
        bucket = "rejected"
    elif verification_reasons:
        bucket = "verification_pool"
    else:
        bucket = "active"

    gated = dict(item)
    gated["lead_gate"] = {
        "bucket": bucket,
        "active_reasons": active_reasons,
        "verification_reasons": verification_reasons,
        "reject_reasons": reject_reasons,
    }
    return gated


def gate_qualified_results(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    gated = [classify_lead(item) for item in items]

    active = [x for x in gated if x["lead_gate"]["bucket"] == "active"]
    verification_pool = [
        x for x in gated
        if x["lead_gate"]["bucket"] == "verification_pool"
    ]
    rejected = [x for x in gated if x["lead_gate"]["bucket"] == "rejected"]

    return {
        "input_qualified_count": len(items),
        "active_count": len(active),
        "verification_pool_count": len(verification_pool),
        "rejected_count": len(rejected),
        "active": active,
        "verification_pool": verification_pool,
        "rejected": rejected,
    }
