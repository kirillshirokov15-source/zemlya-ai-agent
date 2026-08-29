from __future__ import annotations

import re
from datetime import date
from typing import Any


RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
    "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10,
    "ноября": 11, "декабря": 12,
}

FULL_DATE = re.compile(
    r"\b([0-3]?\d)\s+(" + "|".join(RU_MONTHS) + r")\s+(20\d{2})\b", re.I
)
DOT_DATE = re.compile(r"\b([0-3]?\d)[./]([01]?\d)[./](20\d{2})\b")

MILESTONE_MARKERS = (
    "запуск", "запустить", "запланирован", "ввод", "открытие",
    "начало строительства", "подготовка стройплощадки",
    "подготовка строительной площадки", "строительство начн",
)

COMPLETION_SIGNALS = (
    "введен в эксплуатацию", "введён в эксплуатацию",
    "запущено производство", "запустил производство",
    "объект открыт", "строительство завершено", "началось строительство",
    "строительство началось", "ведется строительство", "ведётся строительство",
)


def _project_payload(project: dict[str, Any]) -> dict[str, Any]:
    return project.get("qualification") or project


def _milestone_dates(text: str) -> list[date]:
    found: list[date] = []
    for pattern in (FULL_DATE, DOT_DATE):
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 120):match.end() + 120].lower()
            if not any(marker in window for marker in MILESTONE_MARKERS):
                continue
            try:
                if pattern is FULL_DATE:
                    found.append(date(int(match.group(3)), RU_MONTHS[match.group(2).lower()], int(match.group(1))))
                else:
                    found.append(date(int(match.group(3)), int(match.group(2)), int(match.group(1))))
            except ValueError:
                pass
    return found


def assess_temporal_quality(project: dict[str, Any]) -> dict[str, Any]:
    payload = _project_payload(project)
    text = "\n".join([
        str(payload.get("project_summary") or ""),
        " ".join(str(x) for x in (payload.get("evidence") or [])),
    ]).lower()

    today = date.today()
    milestone_dates = _milestone_dates(text)
    past_milestones = [d for d in milestone_dates if d < today]
    explicit_completed = any(marker in text for marker in COMPLETION_SIGNALS)

    # A current-year launch without an exact date is not proof that the project
    # is still pre-construction. Route it to verification instead of assuming.
    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", text)]
    current_or_past_year = any(y <= today.year for y in years)
    current_status_check = bool(explicit_completed or past_milestones or current_or_past_year)

    out = dict(project)
    out["temporal_quality"] = {
        "milestone_dates": [d.isoformat() for d in sorted(set(milestone_dates))],
        "past_milestone_dates": [d.isoformat() for d in sorted(set(past_milestones))],
        "explicit_completed_signal": explicit_completed,
        "needs_current_status_check": current_status_check,
        "checked_on": today.isoformat(),
    }
    return out


def assess_temporal_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [assess_temporal_quality(p) for p in projects]
