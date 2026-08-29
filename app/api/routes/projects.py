from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from app.services.project_persistence import (
    get_project,
    list_projects,
    list_search_runs,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def projects_list(
    bucket: str | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    stage: str | None = None,
    company: str | None = None,
    project_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    projects = list_projects(
        bucket=bucket,
        min_score=min_score,
        stage=stage,
        company=company,
        project_type=project_type,
        limit=limit,
        offset=offset,
    )
    return {
        "count": len(projects),
        "limit": limit,
        "offset": offset,
        "projects": projects,
    }


@router.get("/search-runs")
def search_runs(limit: int = Query(default=50, ge=1, le=200)):
    runs = list_search_runs(limit=limit)
    return {"count": len(runs), "runs": runs}


@router.get("/export.xlsx")
def projects_export_xlsx(
    bucket: str | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    stage: str | None = None,
    company: str | None = None,
    project_type: str | None = None,
):
    projects = list_projects(
        bucket=bucket,
        min_score=min_score,
        stage=stage,
        company=company,
        project_type=project_type,
        limit=500,
        offset=0,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Projects"

    headers = [
        "ID",
        "Bucket",
        "Lead Score",
        "Priority",
        "Company",
        "Project Type",
        "Summary",
        "Location",
        "Investment RUB",
        "Stage",
        "Land Status",
        "Signal Status",
        "Confidence",
        "Recommended Action",
        "First Seen",
        "Last Seen",
    ]
    ws.append(headers)

    for p in projects:
        ws.append([
            p.get("id"),
            p.get("bucket"),
            p.get("lead_score"),
            p.get("priority"),
            p.get("company_name"),
            p.get("project_type"),
            p.get("project_summary"),
            p.get("location"),
            p.get("investment_rub"),
            p.get("stage"),
            p.get("land_status"),
            p.get("signal_status"),
            p.get("confidence"),
            p.get("recommended_action"),
            p.get("first_seen_at"),
            p.get("last_seen_at"),
        ])

    widths = {
        "A": 38, "B": 18, "C": 12, "D": 16, "E": 28, "F": 38,
        "G": 70, "H": 42, "I": 18, "J": 10, "K": 18, "L": 18,
        "M": 14, "N": 24, "O": 22, "P": 22,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition":
                'attachment; filename="zemlya-projects.xlsx"'
        },
    )


@router.get("/{project_id}")
def project_detail(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
