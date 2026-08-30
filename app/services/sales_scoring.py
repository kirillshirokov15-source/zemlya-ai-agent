from __future__ import annotations
from typing import Any


def _payload(project: dict[str, Any]) -> dict[str, Any]:
    return project.get("qualification") or project


def _priority(score: int, has_direct_contact: bool = False) -> str:
    if score >= 90 and has_direct_contact:
        return "A_hot"
    if score >= 70:
        return "B_work"
    if score >= 50:
        return "C_verify"
    return "D_research"


def _action(
    score: int,
    has_direct_contact: bool,
    has_general_contact: bool,
    has_named_lpr: bool,
) -> str:
    if has_direct_contact and score >= 90:
        return "contact_now"
    if has_named_lpr and not has_direct_contact:
        return "find_decision_maker"
    if has_general_contact and not has_direct_contact:
        return "find_decision_maker"
    if score >= 50:
        return "verify_project_status"
    return "research_later"


def _contact_state(project: dict[str, Any]) -> dict[str, bool]:
    e = project.get("enrichment") or {}
    ce = project.get("contact_enrichment") or {}

    contacts = (
        ce.get("contacts")
        or e.get("contacts")
        or project.get("contacts")
        or []
    )

    has_named_lpr = any(
        c.get("name")
        and (c.get("role") or c.get("position"))
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

    general_email = (
        ce.get("general_company_email")
        or e.get("general_company_email")
    )
    general_phone = (
        ce.get("general_company_phone")
        or e.get("general_company_phone")
    )

    # A contact row explicitly marked company_general also counts as general.
    row_general = any(
        (c.get("phone") or c.get("email"))
        and c.get("contact_type") == "company_general"
        for c in contacts
    )

    has_general_contact = bool(general_email or general_phone or row_general)

    return {
        "has_named_lpr": has_named_lpr,
        "has_direct_lpr": has_direct_lpr,
        "has_general_contact": has_general_contact,
        "has_any_contact": has_direct_lpr or has_general_contact,
    }


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

    # 1. Identity – max 20
    if company:
        score += 10
        reasons.append("Компания установлена")
    if inn:
        score += 10
        reasons.append("Юрлицо подтверждено по ИНН")

    # 2. Project quality / relevance – max 30
    confidence = p.get("confidence") or project.get("confidence")
    if confidence == "high":
        score += 8
    elif confidence == "medium":
        score += 5

    signal = p.get("signal_status") or project.get("signal_status")
    if signal == "confirmed_project":
        score += 8
        reasons.append("Проект подтвержден")
    elif signal == "early_signal":
        score += 3

    land = p.get("land_status") or project.get("land_status")
    if land == "confirmed_needed":
        score += 14
        reasons.append("Подтверждена потребность в участке")
    elif land == "high_probability":
        score += 10
    elif land == "unknown":
        score += 5
    elif land == "land_defined":
        score += 1
        reasons.append("Участок уже определен")

    # 3. Temporal quality – max 10
    temporal = project.get("temporal_quality") or {}
    if not temporal.get("needs_current_status_check"):
        score += 10
    else:
        reasons.append("Нужно перепроверить текущий статус")

    # 4. Contact readiness – max 40 and mandatory caps below.
    cs = _contact_state(project)
    if cs["has_direct_lpr"]:
        score += 40
        reasons.append("Есть ЛПР с прямым телефоном/email")
    elif cs["has_general_contact"] and cs["has_named_lpr"]:
        score += 24
        reasons.append("ЛПР известен, есть общий корпоративный контакт")
    elif cs["has_general_contact"]:
        score += 18
        reasons.append("Есть общий корпоративный контакт")
    elif cs["has_named_lpr"]:
        score += 10
        reasons.append("ЛПР установлен, но прямого контакта нет")
    else:
        reasons.append("ЛПР и контакты не найдены")

    # 5. Business relevance penalties
    if q.get("existing_site_modernization"):
        score -= 35
        reasons.append("Модернизация существующей площадки")
    if q.get("land_already_secured"):
        score -= 15
    if q.get("needs_current_status_check"):
        score -= 10

    # HARD READINESS CAPS.
    # These caps are the key semantic rule:
    # Sales Score measures ability to actually start a sale, not just project quality.
    if not cs["has_any_contact"] and not cs["has_named_lpr"]:
        score = min(score, 49)
        reasons.append("Оценка ограничена: нет ЛПР и способа связи")
    elif cs["has_named_lpr"] and not cs["has_any_contact"]:
        score = min(score, 59)
        reasons.append("Оценка ограничена: ЛПР известен, но связаться с ним пока нельзя")
    elif cs["has_general_contact"] and not cs["has_direct_lpr"]:
        score = min(score, 79)
        reasons.append("Оценка ограничена: есть только общий канал связи, нет прямого контакта ЛПР")
    elif not cs["has_direct_lpr"]:
        score = min(score, 79)

    score = max(0, min(100, int(score)))

    priority = _priority(score, cs["has_direct_lpr"])
    action = _action(
        score,
        cs["has_direct_lpr"],
        cs["has_general_contact"],
        cs["has_named_lpr"],
    )

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
    out["sales_contact_state"] = cs
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


def score_sales_readiness(projects: list[dict[str, Any]]) -> dict[str, Any]:
    return score_sales_projects(projects)
