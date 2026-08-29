from __future__ import annotations

import re
from datetime import date
from typing import Any


LAUNCH_PATTERNS = (
    re.compile(r"запуск\w*[^.]{0,80}?(20\d{2})", re.I),
    re.compile(r"ввод\w*[^.]{0,80}?(20\d{2})", re.I),
    re.compile(r"открыт\w*[^.]{0,80}?(20\d{2})", re.I),
)

COMPLETION_SIGNALS = (
    "введен в эксплуатацию", "введён в эксплуатацию", "запущено производство",
    "запустил производство", "объект открыт", "строительство завершено",
)


def assess_temporal_quality(project: dict[str, Any]) -> dict[str, Any]:
    text = "\n".join([
        str(project.get("project_summary") or ""),
        " ".join(str(x) for x in (project.get("evidence") or [])),
    ]).lower()
    current_year = date.today().year
    launch_years: list[int] = []
    for pattern in LAUNCH_PATTERNS:
        launch_years.extend(int(m.group(1)) for m in pattern.finditer(text))

    explicit_completed = any(marker in text for marker in COMPLETION_SIGNALS)
    latest_launch_year = max(launch_years) if launch_years else None
    needs_check = bool(
        explicit_completed
        or (latest_launch_year is not None and latest_launch_year <= current_year)
    )

    out = dict(project)
    out["temporal_quality"] = {
        "latest_launch_year": latest_launch_year,
        "explicit_completed_signal": explicit_completed,
        "needs_current_status_check": needs_check,
    }
    return out


def assess_temporal_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [assess_temporal_quality(p) for p in projects]
