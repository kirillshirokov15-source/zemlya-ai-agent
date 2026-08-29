from __future__ import annotations

from datetime import date
from typing import Any


def _has_decision_maker(enrichment: dict[str, Any]) -> bool:
    markers = (
        "генераль", "директор", "владел", "собствен", "развити",
        "инвест", "строител", "недвиж", "земел",
    )
    for contact in enrichment.get("contacts") or []:
        role = str(contact.get("role") or "").lower()
        if contact.get("name") and any(m in role for m in markers):
            return True
    return False


def _has_direct_contact(enrichment: dict[str, Any]) -> bool:
    return any(
        c.get("email") or c.get("phone")
        for c in (enrichment.get("contacts") or [])
    )


def _priority(score: int) -> str:
    if score >= 80:
        return "A_hot"
    if score >= 65:
        return "B_work"
    if score >= 50:
        return "C_verify"
    return "D_research"


def _action(score: int, project: dict[str, Any]) -> str:
    enrichment = project.get("enrichment") or {}
    if not (project.get("company_name") or project.get("resolved_company_name")):
        return "resolve_company"
    if score >= 80 and _has_direct_contact(enrichment):
        return "contact_now"
    if score >= 65:
        return "find_decision_maker"
    if score >= 50:
        return "verify_project_status"
    return "research_later"


def score_sales_project(project: dict[str, Any]) -> dict[str, Any]:
    project_score = int(project.get("lead_score") or 0)
    enrichment = project.get("enrichment") or {}
    company_known = bool(project.get("company_name") or project.get("resolved_company_name"))
    resolution = enrichment.get("resolution_confidence")

    adjustments: dict[str, int] = {}
    adjustments["company_identity"] = 8 if company_known else -18
    adjustments["identity_resolution"] = 4 if resolution == "high" else (2 if resolution == "medium" else 0)
    adjustments["legal_identity"] = 3 if (project.get("inn") or project.get("ogrn")) else 0
    adjustments["decision_maker"] = 7 if _has_decision_maker(enrichment) else 0
    adjustments["direct_contact"] = 5 if _has_direct_contact(enrichment) else 0

    land_status = project.get("land_status")
    adjustments["land_already_defined"] = -8 if land_status == "land_defined" else 0

    # A project whose stated launch is already around/past the current period needs status verification,
    # not immediate sales outreach. The temporal quality stage can set this marker.
    temporal = project.get("temporal_quality") or {}
    adjustments["status_uncertainty"] = -10 if temporal.get("needs_current_status_check") else 0

    sales_score = max(0, min(100, project_score + sum(adjustments.values())))
    out = dict(project)
    out["project_score"] = project_score
    out["sales_score"] = sales_score
    out["sales_priority"] = _priority(sales_score)
    out["recommended_action"] = _action(sales_score, out)
    out["sales_score_breakdown"] = {
        "base_project_score": project_score,
        "adjustments": adjustments,
        "total": sales_score,
        "scored_at": date.today().isoformat(),
    }
    return out


def score_sales_projects(projects: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [score_sales_project(p) for p in projects]
    scored.sort(key=lambda x: (x.get("sales_score") or 0, x.get("project_score") or 0), reverse=True)
    return {
        "projects_scored_count": len(scored),
        "priority_counts": {
            key: sum(1 for p in scored if p.get("sales_priority") == key)
            for key in ("A_hot", "B_work", "C_verify", "D_research")
        },
        "projects": scored,
    }
