from __future__ import annotations

from typing import Any

from app.services.sales_scoring import get_contact_state


def _text(project: dict[str, Any]) -> str:
    parts = [
        project.get("project_summary"),
        project.get("project_type"),
        project.get("status_text"),
    ]
    raw = project.get("raw")
    if isinstance(raw, dict):
        parts.extend([
            raw.get("project_summary"),
            raw.get("reason"),
            raw.get("current_status"),
        ])
    return " ".join(str(x or "").lower() for x in parts)


def verify_project(project: dict[str, Any]) -> dict[str, Any]:
    """
    Final Verification V8.

    Important:
    – no blanket max-79 cap for missing direct LPR;
    – stage V always means the site/plot is already defined;
    – stage G, paused and existing-site modernization remain hard business gates.
    """
    out = dict(project)
    score = int(out.get("sales_score") or 0)
    project_score = int(out.get("project_score") or out.get("lead_score") or 0)
    stage = str(out.get("stage") or "")
    land = out.get("land_status")
    text = _text(out)
    flags: list[str] = []

    cs = get_contact_state(out)

    if stage == "V":
        land = "land_defined"
        flags.extend(["stage_v_site_defined", "land_status_forced_to_defined"])

    if land == "land_defined":
        flags.append("land_already_defined")

    paused = any(x in text for x in ("приостанов", "заморож", "отложен", "suspended", "paused"))
    modernization = any(x in text for x in (
        "модернизац", "реконструкц", "техническое перевооруж",
        "техперевооруж", "существующей площадк", "существующего производ"
    ))

    if paused:
        project_score = min(project_score, 35)
        score = min(score, 29)
        flags.append("project_paused")

    if stage == "G":
        project_score = min(project_score, 45)
        score = min(score, 39)
        flags.append("construction_started")

    if modernization:
        project_score = min(project_score, 30)
        score = min(score, 35)
        flags.append("existing_site_modernization")

    # Readiness is a status, not a blanket score cap.
    if score >= 90 and cs["has_direct_lpr"]:
        priority, action, grade = "A_hot", "contact_now", "A_ready"
    elif score >= 70:
        priority = "B_work"
        action = "contact_now" if cs["has_direct_lpr"] else "find_decision_maker"
        grade = "B_high"
    elif score >= 50:
        priority, action, grade = "C_verify", "verify_project_status", "C_verify"
    else:
        priority, action, grade = "D_research", "research_later", "D_low"

    out.update({
        "sales_score": max(0, min(100, score)),
        "project_score": project_score,
        "land_status": land,
        "sales_priority": priority,
        "recommended_action": action,
        "final_grade": grade,
        "final_verification_passed": not (paused or stage == "G" or modernization),
        "final_verification_flags": flags,
        "sales_contact_state": cs,
        "final_verification_version": "v8",
    })

    q = out.get("qualification")
    if isinstance(q, dict):
        q = dict(q)
        q["stage"] = stage
        q["land_status"] = land
        out["qualification"] = q

    return out
