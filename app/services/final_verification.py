from __future__ import annotations
from typing import Any
import re


PAUSED_MARKERS = (
    "проект приостановлен",
    "реализация приостановлена",
    "проект заморожен",
    "строительство приостановлено",
)
STARTED_MARKERS = (
    "строительство началось",
    "начаты строительно-монтажные работы",
    "ведется строительство",
    "ведётся строительство",
    "получено разрешение на строительство",
)
MODERNIZATION_MARKERS = (
    "модернизац",
    "реконструкц",
    "техническ перевооруж",
)


def _text(project: dict[str, Any]) -> str:
    parts = [
        project.get("project_summary"),
        project.get("location"),
        project.get("project_type"),
    ]
    q = project.get("qualification") or {}
    parts.extend([
        q.get("project_summary"),
        q.get("location"),
        q.get("project_type"),
    ])
    return " ".join(str(x or "") for x in parts).lower()


def _direct_contact(project: dict[str, Any]) -> bool:
    ce = project.get("contact_enrichment") or {}
    contacts = ce.get("contacts") or (project.get("enrichment") or {}).get("contacts") or []
    return any(
        c.get("name")
        and (c.get("role") or c.get("position"))
        and (c.get("phone") or c.get("email"))
        for c in contacts
    )


def verify_project(project: dict[str, Any]) -> dict[str, Any]:
    text = _text(project)
    q = project.get("qualification") or project
    flags: list[str] = []

    project_score = int(project.get("project_score") or project.get("lead_score") or 0)
    sales_score = int(project.get("sales_score") or 0)

    company_conf = (
        project.get("company_resolution_confidence")
        or (project.get("enrichment") or {}).get("resolution_confidence")
        or "unresolved"
    )

    if company_conf == "unresolved":
        flags.append("company_unresolved")
        sales_score = min(sales_score, 49)

    if any(m in text for m in PAUSED_MARKERS):
        flags.append("project_paused")
        project_score = min(project_score, 35)
        sales_score = min(sales_score, 29)

    stage = q.get("stage") or project.get("stage")
    if stage == "G" or any(m in text for m in STARTED_MARKERS):
        flags.append("construction_started_or_permit")
        project_score = min(project_score, 45)
        sales_score = min(sales_score, 39)

    land = q.get("land_status") or project.get("land_status")
    if land == "land_defined":
        flags.append("land_already_defined")
        sales_score = min(sales_score, 59)

    if any(m in text for m in MODERNIZATION_MARKERS):
        flags.append("existing_site_modernization")
        project_score = min(project_score, 30)
        sales_score = min(sales_score, 29)

    if not _direct_contact(project):
        flags.append("no_direct_lpr_contact")

    # Final commercial grade after all checks.
    if sales_score >= 90 and _direct_contact(project):
        final_grade = "A_ready"
    elif sales_score >= 70:
        final_grade = "B_high"
    elif sales_score >= 50:
        final_grade = "C_verify"
    else:
        final_grade = "D_low"

    out = dict(project)
    out["project_score"] = project_score
    out["sales_score"] = sales_score
    out["final_grade"] = final_grade
    out["final_verification_flags"] = flags
    out["final_verification_passed"] = not any(
        f in flags
        for f in (
            "company_unresolved",
            "project_paused",
            "construction_started_or_permit",
            "existing_site_modernization",
        )
    )
    return out


def verify_and_rank(projects: list[dict[str, Any]]) -> dict[str, Any]:
    verified = [verify_project(p) for p in projects]
    verified.sort(
        key=lambda p: (
            p.get("sales_score") or 0,
            p.get("project_score") or 0,
        ),
        reverse=True,
    )
    return {
        "projects": verified,
        "verified_count": len(verified),
        "passed_count": sum(1 for p in verified if p.get("final_verification_passed")),
        "needs_attention_count": sum(1 for p in verified if not p.get("final_verification_passed")),
    }
