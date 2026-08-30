from __future__ import annotations

from typing import Any


LPR_ROLE_MARKERS = (
    "генераль", "директор", "собствен", "владел", "учредител",
    "руководител", "development", "развити", "инвест",
    "строител", "недвижим", "земел", "project manager",
)

GENERAL_CONTACT_MARKERS = (
    "корпоратив", "общий", "company", "офис", "приемн",
    "приёмн", "контакт", "info",
)


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _lower(v: Any) -> str:
    return _norm(v).lower()


def _collect_contacts(project: dict[str, Any]) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []

    for key in ("contacts", "lead_project_contacts"):
        value = project.get(key)
        if isinstance(value, list):
            contacts.extend([x for x in value if isinstance(x, dict)])

    for container_key in ("contact_enrichment", "enrichment"):
        container = project.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("contacts", "decision_makers", "people"):
            value = container.get(key)
            if isinstance(value, list):
                contacts.extend([x for x in value if isinstance(x, dict)])

        email = container.get("general_company_email")
        phone = container.get("general_company_phone")
        if email or phone:
            contacts.append({
                "name": "Общий корпоративный контакт",
                "role": "Общий корпоративный контакт",
                "email": email,
                "phone": phone,
                "contact_type": "company_general",
            })

    return contacts


def _is_lpr(c: dict[str, Any]) -> bool:
    name = _norm(c.get("name"))
    role = _lower(c.get("role") or c.get("position"))
    ctype = _lower(c.get("contact_type"))
    if not name:
        return False
    if ctype in {"decision_maker", "executive", "owner", "beneficiary"}:
        return True
    return any(marker in role for marker in LPR_ROLE_MARKERS)


def _is_general(c: dict[str, Any]) -> bool:
    has_channel = bool(c.get("email") or c.get("phone"))
    if not has_channel:
        return False
    ctype = _lower(c.get("contact_type"))
    if ctype == "company_general":
        return True
    text = f"{_lower(c.get('name'))} {_lower(c.get('role') or c.get('position'))}"
    return any(marker in text for marker in GENERAL_CONTACT_MARKERS) or not _is_lpr(c)


def get_contact_state(project: dict[str, Any]) -> dict[str, bool]:
    contacts = _collect_contacts(project)
    named_lpr = [c for c in contacts if _is_lpr(c)]
    direct_lpr = [c for c in named_lpr if c.get("email") or c.get("phone")]
    general = [c for c in contacts if _is_general(c)]

    return {
        "has_named_lpr": bool(named_lpr),
        "has_direct_lpr": bool(direct_lpr),
        "has_general_contact": bool(general),
        "has_any_contact": bool(direct_lpr or general),
    }


def _project_quality_component(project: dict[str, Any]) -> int:
    # Existing Project Score already summarizes fit, signal quality, source quality,
    # stage and completeness. Convert it to a 0–35 component.
    ps = project.get("project_score")
    if ps is None:
        ps = project.get("lead_score")
    try:
        ps = max(0.0, min(100.0, float(ps or 0)))
    except Exception:
        ps = 0.0
    return round(ps * 0.35)


def _land_fit_component(project: dict[str, Any]) -> int:
    stage = _norm(project.get("stage"))
    land = _norm(project.get("land_status"))

    if stage == "G":
        return 0
    if stage == "V":
        return 3

    return {
        "confirmed_needed": 25,
        "high_probability": 20,
        "unknown": 10,
        "land_defined": 3,
        "": 8,
    }.get(land, 8)


def _company_identity_component(project: dict[str, Any]) -> int:
    company = (
        project.get("resolved_company_name")
        or project.get("legal_name")
        or project.get("company_name")
    )
    legal_name = project.get("legal_name")
    inn = _norm(project.get("inn"))
    resolution_conf = _lower(project.get("company_resolution_confidence"))

    if inn and (legal_name or company):
        return 15
    if company and resolution_conf == "high":
        return 12
    if company:
        return 7
    return 0


def _contactability_component(project: dict[str, Any]) -> tuple[int, dict[str, bool]]:
    cs = get_contact_state(project)

    if cs["has_direct_lpr"]:
        return 25, cs
    if cs["has_named_lpr"] and cs["has_general_contact"]:
        return 15, cs
    if cs["has_general_contact"]:
        return 10, cs
    if cs["has_named_lpr"]:
        return 6, cs
    return 0, cs


def _has_any_text(project: dict[str, Any], markers: tuple[str, ...]) -> bool:
    chunks = [
        project.get("project_summary"),
        project.get("project_type"),
        project.get("status_text"),
    ]
    raw = project.get("raw")
    if isinstance(raw, dict):
        chunks.extend([
            raw.get("project_summary"),
            raw.get("reason"),
            raw.get("current_status"),
        ])
        fq = raw.get("final_verification_flags")
        if isinstance(fq, list):
            chunks.extend(fq)
    text = " ".join(_lower(x) for x in chunks if x)
    return any(m in text for m in markers)


def score_sales_project(project: dict[str, Any]) -> dict[str, Any]:
    """
    Sales Score V8

    0–35  Project quality
    0–25  Land/service fit
    0–15  Company identity
    0–25  Contactability

    No artificial 79 cap for projects without a direct LPR.
    Contact readiness is represented separately by sales_priority/final_grade.
    """
    result = dict(project)

    pq = _project_quality_component(project)
    land = _land_fit_component(project)
    company = _company_identity_component(project)
    contacts, cs = _contactability_component(project)

    score = pq + land + company + contacts
    penalties: list[dict[str, Any]] = []

    paused = _has_any_text(project, (
        "приостанов", "заморож", "отложен", "suspended", "paused"
    ))
    modernization = _has_any_text(project, (
        "модернизац", "реконструкц", "техническое перевооруж",
        "техперевооруж", "существующей площадк", "существующего производ"
    ))
    stage = _norm(project.get("stage"))

    if paused:
        score -= 30
        penalties.append({"reason": "project_paused", "value": -30})

    if modernization:
        score -= 20
        penalties.append({"reason": "existing_site_modernization", "value": -20})

    if stage == "G":
        score -= 15
        penalties.append({"reason": "construction_started", "value": -15})

    score = max(0, min(100, int(round(score))))

    # Hard business gates are only for genuinely late/irrelevant cases.
    if paused:
        score = min(score, 29)
    if stage == "G":
        score = min(score, 39)
    if modernization:
        score = min(score, 35)

    if score >= 90 and cs["has_direct_lpr"]:
        sales_priority = "A_hot"
        action = "contact_now"
        final_grade = "A_ready"
    elif score >= 70:
        sales_priority = "B_work"
        action = "find_decision_maker" if not cs["has_direct_lpr"] else "contact_now"
        final_grade = "B_high"
    elif score >= 50:
        sales_priority = "C_verify"
        action = "verify_project_status"
        final_grade = "C_verify"
    else:
        sales_priority = "D_research"
        action = "research_later"
        final_grade = "D_low"

    result.update({
        "sales_score": score,
        "sales_priority": sales_priority,
        "recommended_action": action,
        "final_grade": final_grade,
        "sales_score_breakdown": {
            "project_quality": pq,
            "land_service_fit": land,
            "company_identity": company,
            "contactability": contacts,
            "penalties": penalties,
            "total": score,
        },
        "sales_contact_state": cs,
        "sales_scoring_version": "v8",
    })
    return result


def score_sales_projects(projects: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Backward-compatible batch interface expected by app.tasks.qualification.
    """
    scored = [score_sales_project(project) for project in projects]
    scored.sort(
        key=lambda p: (
            p.get("sales_score") or 0,
            p.get("project_score") or 0,
        ),
        reverse=True,
    )
    return {
        "projects_scored_count": len(scored),
        "priority_counts": {
            key: sum(
                1 for p in scored
                if p.get("sales_priority") == key
            )
            for key in ("A_hot", "B_work", "C_verify", "D_research")
        },
        "projects": scored,
    }


def score_sales_readiness(projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Legacy alias kept for compatibility."""
    return score_sales_projects(projects)
