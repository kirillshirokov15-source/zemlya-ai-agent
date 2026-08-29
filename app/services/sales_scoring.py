from __future__ import annotations
from typing import Any

def _payload(project: dict[str, Any]) -> dict[str, Any]:
    return project.get("qualification") or project

def calculate_sales_score(project: dict[str, Any]) -> dict[str, Any]:
    p = _payload(project); e = project.get("enrichment") or {}; q = project.get("quality_gate") or {}
    score, reasons = 0, []
    company = e.get("company_legal_name") or e.get("company_name") or p.get("company_name")
    inn = e.get("inn") or p.get("inn")
    if company: score += 15; reasons.append("Компания установлена")
    if inn: score += 10; reasons.append("Юрлицо подтверждено по ИНН")

    contacts = e.get("contacts") or project.get("contacts") or []
    direct = any((c.get("name") and (c.get("role") or c.get("position")) and (c.get("phone") or c.get("email"))) for c in contacts)
    any_contact = any(c.get("phone") or c.get("email") for c in contacts)
    if direct: score += 25; reasons.append("Найден ЛПР с прямым контактом")
    elif any_contact: score += 15; reasons.append("Найден контакт для связи")
    else: reasons.append("Прямой контакт ЛПР пока не найден")

    if p.get("confidence") == "high": score += 10
    elif p.get("confidence") == "medium": score += 6
    if p.get("signal_status") == "confirmed_project": score += 10; reasons.append("Проект подтвержден")
    elif p.get("signal_status") == "early_signal": score += 4

    land = p.get("land_status")
    if land == "confirmed_needed": score += 20; reasons.append("Подтверждена потребность в участке")
    elif land == "high_probability": score += 14
    elif land == "unknown": score += 7
    elif land == "land_defined": score += 2; reasons.append("Участок уже определен")

    temporal = project.get("temporal_quality") or {}
    if not temporal.get("needs_current_status_check"): score += 10
    else: reasons.append("Нужно перепроверить текущий статус")

    if q.get("existing_site_modernization"): score -= 35; reasons.append("Модернизация существующей площадки")
    if q.get("land_already_secured"): score -= 15
    if q.get("needs_current_status_check"): score -= 10
    score = max(0, min(100, score))

    if score >= 90: label, action = "Готов к контакту", "Связаться с ЛПР"
    elif score >= 70: label, action = "Высокий потенциал", "Дособрать контакт и связаться"
    elif score >= 50: label, action = "Требует проверки", "Проверить недостающие данные"
    else: label, action = "Низкий приоритет", "Оставить на повторную проверку"

    out = dict(project)
    out.update(sales_score=score, sales_priority=label, sales_action=action, sales_score_reasons=reasons)
    return out

def score_sales_readiness(projects):
    return sorted((calculate_sales_score(p) for p in projects),
                  key=lambda p:(p.get("sales_score",0),p.get("project_score",p.get("lead_score",0))), reverse=True)


# Backward compatibility with earlier qualification task imports.
def score_sales_projects(projects):
    return score_sales_readiness(projects)
