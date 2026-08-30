from __future__ import annotations
from typing import Any


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
)
MODERNIZATION_MARKERS = (
    "модернизац",
    "реконструкц",
    "техническ перевооруж",
)


def _text(project: dict[str, Any]) -> str:
    q = project.get("qualification") or {}
    return " ".join(
        str(x or "")
        for x in (
            project.get("project_summary"),
            project.get("location"),
            project.get("project_type"),
            q.get("project_summary"),
            q.get("location"),
            q.get("project_type"),
        )
    ).lower()


def _contact_state(project: dict[str, Any]) -> dict[str, bool]:
    e = project.get("enrichment") or {}
    ce = project.get("contact_enrichment") or {}

    contacts = ce.get("contacts") or e.get("contacts") or project.get("contacts") or []

    has_named_lpr = any(
        c.get("name") and (c.get("role") or c.get("position"))
        and c.get("contact_type") in {"decision_maker", "executive", None}
        for c in contacts
    )

    has_direct_lpr = any(
        c.get("name")
        and (c.get("role") or c.get("position"))
        and (c.get("phone") or c.get("email"))
        and c.get("contact_type") in {"decision_maker", "executive", None}
        for c in contacts
    )

    has_general_contact = bool(
        ce.get("general_company_email")
        or ce.get("general_company_phone")
        or e.get("general_company_email")
        or e.get("general_company_phone")
        or any(
            (c.get("phone") or c.get("email"))
            and c.get("contact_type") == "company_general"
            for c in contacts
        )
    )

    return {
        "has_named_lpr": has_named_lpr,
        "has_direct_lpr": has_direct_lpr,
        "has_general_contact": has_general_contact,
        "has_any_contact": has_direct_lpr or has_general_contact,
    }


def verify_project(project: dict[str, Any]) -> dict[str, Any]:
    text = _text(project)
    q = project.get("qualification") or project

    project_score = int(project.get("project_score") or project.get("lead_score") or 0)
    sales_score = int(project.get("sales_score") or 0)
    flags: list[str] = []

    cs = _contact_state(project)

    company_conf = (
        project.get("company_resolution_confidence")
        or (project.get("enrichment") or {}).get("resolution_confidence")
        or "unresolved"
    )

    stage = q.get("stage") or project.get("stage")
    land = q.get("land_status") or project.get("land_status")

    # ------------------------------------------------------------
    # BUSINESS CONSISTENCY
    # ------------------------------------------------------------
    # Stage V means the site has already been selected/provided.
    # It cannot simultaneously be treated as an early land-search lead.
    if stage == "V":
        flags.append("stage_v_site_defined")
        if land in {"confirmed_needed", "high_probability", "unknown", None}:
            land = "land_defined"
            flags.append("land_status_corrected_to_defined")
        sales_score = min(sales_score, 59)

    if land == "land_defined":
        flags.append("land_already_defined")
        sales_score = min(sales_score, 59)

    # ------------------------------------------------------------
    # CONTACT READINESS – FINAL HARD CAPS
    # ------------------------------------------------------------
    # These caps are repeated here intentionally. This makes the final output
    # correct even if an older sales_scoring implementation is accidentally
    # deployed.
    if not cs["has_named_lpr"] and not cs["has_any_contact"]:
        sales_score = min(sales_score, 49)
        flags.append("no_lpr_no_contact")
    elif cs["has_named_lpr"] and not cs["has_any_contact"]:
        sales_score = min(sales_score, 59)
        flags.append("named_lpr_no_contact")
    elif cs["has_general_contact"] and not cs["has_direct_lpr"]:
        sales_score = min(sales_score, 79)
        flags.append("general_contact_only")
    elif not cs["has_direct_lpr"]:
        sales_score = min(sales_score, 79)
        flags.append("no_direct_lpr_contact")

    # ------------------------------------------------------------
    # PROJECT QUALITY GUARDS
    # ------------------------------------------------------------
    if company_conf == "unresolved":
        flags.append("company_unresolved")
        sales_score = min(sales_score, 49)

    if any(m in text for m in PAUSED_MARKERS):
        flags.append("project_paused")
        project_score = min(project_score, 35)
        sales_score = min(sales_score, 29)

    if stage == "G" or any(m in text for m in STARTED_MARKERS):
        flags.append("construction_started")
        project_score = min(project_score, 45)
        sales_score = min(sales_score, 39)

    if any(m in text for m in MODERNIZATION_MARKERS):
        flags.append("existing_site_modernization")
        project_score = min(project_score, 30)
        sales_score = min(sales_score, 29)

    sales_score = max(0, min(100, int(sales_score)))

    if sales_score >= 90 and cs["has_direct_lpr"]:
        final_grade = "A_ready"
        sales_priority = "A_hot"
        recommended_action = "contact_now"
    elif sales_score >= 70:
        final_grade = "B_high"
        sales_priority = "B_work"
        recommended_action = "find_decision_maker"
    elif sales_score >= 50:
        final_grade = "C_verify"
        sales_priority = "C_verify"
        recommended_action = "verify_project_status"
    else:
        final_grade = "D_low"
        sales_priority = "D_research"
        recommended_action = "research_later"

    out = dict(project)
    out["project_score"] = project_score
    out["sales_score"] = sales_score
    out["sales_priority"] = sales_priority
    out["recommended_action"] = recommended_action
    out["final_grade"] = final_grade
    out["final_verification_flags"] = flags
    out["final_verification_passed"] = not any(
        f in flags
        for f in (
            "company_unresolved",
            "project_paused",
            "construction_started",
            "existing_site_modernization",
        )
    )
    out["sales_contact_state"] = cs

    # Correct inconsistent land status in the visible top-level output and
    # nested qualification payload.
    out["land_status"] = land
    if out.get("qualification"):
        nested = dict(out["qualification"])
        nested["land_status"] = land
        out["qualification"] = nested

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
