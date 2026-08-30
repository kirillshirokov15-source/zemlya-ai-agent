from __future__ import annotations
from typing import Any


def _payload(project: dict[str, Any]) -> dict[str, Any]:
    return project.get("qualification") or project


def _priority(score: int) -> str:
    if score >= 90:
        return "A_hot"
    if score >= 70:
        return "B_work"
    if score >= 50:
        return "C_verify"
    return "D_research"


def _action(score: int, has_direct_contact: bool) -> str:
    if score >= 90 and has_direct_contact:
        return "contact_now"
    if score >= 70:
        return "find_decision_maker"
    if score >= 50:
        return "verify_project_status"
    return "research_later"


def score_sales_project(project: dict[str, Any]) -> dict[str, Any]:
    p = _payload(project)
    e = project.get("enrichment") or {}
    q = project.get("quality_gate") or {}

    score = 0
    reasons: list[str] = []

    company = (
        e.get("company_legal_name")
        or e.get("legal_name")
        or e.get("company_name")
        or project.get("resolved_company_name")
        or project.get("company_name")
        or p.get("company_name")
    )
    inn = e.get("inn") or project.get("inn") or p.get("inn")

    if company:
        score += 15
        reasons.append("Компания установлена")
    if inn:
        score += 10
        reasons.append("Юрлицо подтверждено по ИНН")

    contacts = e.get("contacts") or project.get("contacts") or []

    direct_contact = any(
        c.get("name")
        and (c.get("role") or c.get("position"))
        and (c.get("phone") or c.get("email"))
        for c in contacts
    )
    any_contact = any(c.get("phone") or c.get("email") for c in contacts)

    if direct_contact:
        score += 25
        reasons.append("Найден ЛПР с прямым контактом")
    elif any_contact:
        score += 15
        reasons.append("Найден контакт для связи")
    else:
        reasons.append("Прямой контакт ЛПР пока не найден")

    confidence = p.get("confidence") or project.get("confidence")
    if confidence == "high":
        score += 10
    elif confidence == "medium":
        score += 6

    signal = p.get("signal_status") or project.get("signal_status")
    if signal == "confirmed_project":
        score += 10
        reasons.append("Проект подтвержден")
    elif signal == "early_signal":
        score += 4

    land = p.get("land_status") or project.get("land_status")
    if land == "confirmed_needed":
        score += 20
        reasons.append("Подтверждена потребность в участке")
    elif land == "high_probability":
        score += 14
    elif land == "unknown":
        score += 7
    elif land == "land_defined":
        score += 2
        reasons.append("Участок уже определен")

    temporal = project.get("temporal_quality") or {}
    if not temporal.get("needs_current_status_check"):
        score += 10
    else:
        reasons.append("Нужно перепроверить текущий статус")

    if q.get("existing_site_modernization"):
        score -= 35
        reasons.append("Модернизация существующей площадки")
    if q.get("land_already_secured"):
        score -= 15
    if q.get("needs_current_status_check"):
        score -= 10

    score = max(0, min(100, score))
    priority = _priority(score)
    action = _action(score, direct_contact)

    out = dict(project)
    out["project_score"] = int(
        project.get("project_score")
        or project.get("lead_score")
        or 0
    )
    out["sales_score"] = score
    out["sales_priority"] = priority
    out["recommended_action"] = action
    out["sales_score_reasons"] = reasons
    return out


def score_sales_projects(projects: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [score_sales_project(p) for p in projects]
    scored.sort(
        key=lambda x: (
            x.get("sales_score") or 0,
            x.get("project_score") or 0,
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


# Alias retained so older code can also call the newer name safely.
def score_sales_readiness(projects: list[dict[str, Any]]) -> dict[str, Any]:
    return score_sales_projects(projects)
