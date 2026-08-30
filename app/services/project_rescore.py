from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text

from app.core.config import settings
from app.services.sales_scoring import score_sales_project
from app.services.final_verification import verify_project


def _engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


def _load_contacts(conn, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("""
            SELECT
                name,
                role,
                email,
                phone,
                profile_url,
                source_url,
                confidence
            FROM lead_project_contacts
            WHERE project_id = CAST(:project_id AS uuid)
            ORDER BY id
        """),
        {"project_id": project_id},
    ).mappings().all()

    contacts = []
    for r in rows:
        c = dict(r)
        role = str(c.get("role") or "").lower()
        if any(x in role for x in (
            "генераль", "директор", "собствен", "владел", "учредител",
            "руководител", "development", "развити", "инвест",
            "строител", "недвижим", "земел", "project manager",
        )):
            c["contact_type"] = "decision_maker"
        elif c.get("email") or c.get("phone"):
            c["contact_type"] = "company_general"
        contacts.append(c)
    return contacts


def _merge_current_columns(row: dict[str, Any], contacts: list[dict[str, Any]]) -> dict[str, Any]:
    raw = dict(row.get("raw") or {})

    # Current PostgreSQL columns are authoritative.
    raw.update({
        "id": str(row["id"]),
        "bucket": row.get("bucket"),
        "company_name": row.get("company_name"),
        "resolved_company_name": row.get("resolved_company_name"),
        "legal_name": row.get("legal_name"),
        "inn": row.get("inn"),
        "ogrn": row.get("ogrn"),
        "website": row.get("website"),
        "project_type": row.get("project_type"),
        "project_summary": row.get("project_summary"),
        "location": row.get("location"),
        "investment_rub": row.get("investment_rub"),
        "stage": row.get("stage"),
        "land_status": row.get("land_status"),
        "signal_status": row.get("signal_status"),
        "confidence": row.get("confidence"),
        "lead_score": row.get("lead_score"),
        "project_score": row.get("project_score") or row.get("lead_score") or 0,
        "company_resolution_confidence": row.get("company_resolution_confidence"),
        "company_relation_confidence": row.get("company_relation_confidence"),
        "contacts": contacts,
    })

    if isinstance(raw.get("qualification"), dict):
        q = dict(raw["qualification"])
        q["stage"] = row.get("stage")
        q["land_status"] = row.get("land_status")
        raw["qualification"] = q

    return raw


def rescore_current_projects() -> dict[str, Any]:
    """
    Recalculate all currently visible rows using Sales Score V8.
    Database only – no Tavily, OpenAI, Redis, Celery or web requests.
    """
    rows_seen = 0
    rows_updated = 0
    changed_examples: list[dict[str, Any]] = []

    with _engine().begin() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    id,
                    bucket,
                    company_name,
                    resolved_company_name,
                    legal_name,
                    inn,
                    ogrn,
                    website,
                    project_type,
                    project_summary,
                    location,
                    investment_rub,
                    stage,
                    land_status,
                    signal_status,
                    confidence,
                    lead_score,
                    project_score,
                    sales_score,
                    sales_priority,
                    recommended_action,
                    company_resolution_confidence,
                    company_relation_confidence,
                    raw
                FROM lead_projects
                WHERE is_active = TRUE
                ORDER BY sales_score DESC NULLS LAST
            """)
        ).mappings().all()

        for dbrow in rows:
            rows_seen += 1
            row = dict(dbrow)
            contacts = _load_contacts(conn, str(row["id"]))
            project = _merge_current_columns(row, contacts)

            scored = score_sales_project(project)
            final = verify_project(scored)

            old_sales = int(row.get("sales_score") or 0)
            old_project = int(row.get("project_score") or row.get("lead_score") or 0)
            old_land = row.get("land_status")

            new_sales = int(final.get("sales_score") or 0)
            new_project = int(final.get("project_score") or 0)
            new_land = final.get("land_status")

            new_raw = dict(final)
            # Do not duplicate the transient DB contacts list unnecessarily.
            new_raw.pop("lead_project_contacts", None)

            conn.execute(
                text("""
                    UPDATE lead_projects
                    SET
                        sales_score = :sales_score,
                        project_score = :project_score,
                        sales_priority = :sales_priority,
                        recommended_action = :recommended_action,
                        land_status = :land_status,
                        final_grade = :final_grade,
                        final_verification_passed = :final_verification_passed,
                        raw = CAST(:raw AS jsonb),
                        last_seen_at = NOW()
                    WHERE id = CAST(:project_id AS uuid)
                """),
                {
                    "project_id": str(row["id"]),
                    "sales_score": new_sales,
                    "project_score": new_project,
                    "sales_priority": final.get("sales_priority"),
                    "recommended_action": final.get("recommended_action"),
                    "land_status": new_land,
                    "final_grade": final.get("final_grade"),
                    "final_verification_passed": bool(final.get("final_verification_passed")),
                    "raw": json.dumps(new_raw, ensure_ascii=False, default=str),
                },
            )
            rows_updated += 1

            if (
                old_sales != new_sales
                or old_project != new_project
                or old_land != new_land
            ):
                changed_examples.append({
                    "company": row.get("resolved_company_name") or row.get("company_name"),
                    "stage": row.get("stage"),
                    "sales_before": old_sales,
                    "sales_after": new_sales,
                    "project_score": new_project,
                    "land_before": old_land,
                    "land_after": new_land,
                    "breakdown": final.get("sales_score_breakdown"),
                    "contact_state": final.get("sales_contact_state"),
                    "final_grade": final.get("final_grade"),
                    "recommended_action": final.get("recommended_action"),
                })

    changed_examples.sort(key=lambda x: x.get("sales_after", 0), reverse=True)

    return {
        "status": "success",
        "mode": "database_only_sales_score_v8",
        "rows_seen": rows_seen,
        "rows_updated": rows_updated,
        "changed_count": len(changed_examples),
        "changed_examples": changed_examples,
    }
