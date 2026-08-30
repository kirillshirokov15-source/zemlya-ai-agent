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
            ORDER BY
                CASE WHEN phone IS NOT NULL OR email IS NOT NULL THEN 0 ELSE 1 END,
                id
        """),
        {"project_id": project_id},
    ).mappings().all()

    contacts = []
    for r in rows:
        c = dict(r)
        # Historical schema may not have contact_type. Infer conservatively.
        role = (c.get("role") or "").lower()
        if any(x in role for x in (
            "генераль", "директор", "собствен", "учредител",
            "руководител", "развити", "инвест", "строител"
        )):
            c["contact_type"] = "decision_maker"
        else:
            c["contact_type"] = "other"
        contacts.append(c)
    return contacts


def rescore_current_projects() -> dict[str, Any]:
    """
    Recalculate all currently visible projects from stored DB data only.
    No Tavily, OpenAI or other web/API calls.
    """
    updated = 0
    rows_seen = 0
    changed_examples: list[dict[str, Any]] = []

    with _engine().begin() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    id,
                    company_name,
                    resolved_company_name,
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
                    inn,
                    ogrn,
                    legal_name,
                    website,
                    raw
                FROM lead_projects
                WHERE is_active = TRUE
                ORDER BY sales_score DESC NULLS LAST, project_score DESC NULLS LAST
            """)
        ).mappings().all()

        for row in rows:
            rows_seen += 1
            p = dict(row)
            project_id = str(p["id"])
            raw = dict(p.get("raw") or {})

            # Build the richest possible project object from stored raw + columns.
            project = dict(raw)
            for key in (
                "company_name", "resolved_company_name", "project_type",
                "project_summary", "location", "investment_rub", "stage",
                "land_status", "signal_status", "confidence", "lead_score",
                "project_score", "sales_score", "sales_priority",
                "recommended_action", "company_resolution_confidence",
                "company_relation_confidence", "inn", "ogrn", "legal_name",
                "website",
            ):
                if p.get(key) is not None:
                    project[key] = p.get(key)

            contacts = _load_contacts(conn, project_id)

            enrichment = dict(project.get("enrichment") or {})
            enrichment.setdefault("company_name", p.get("resolved_company_name") or p.get("company_name"))
            enrichment.setdefault("legal_name", p.get("legal_name"))
            enrichment.setdefault("inn", p.get("inn"))
            enrichment.setdefault("ogrn", p.get("ogrn"))
            enrichment.setdefault("website", p.get("website"))
            enrichment["contacts"] = contacts

            # Recover general corporate contact from raw if present.
            ce = dict(project.get("contact_enrichment") or {})
            if ce:
                enrichment.setdefault("general_company_email", ce.get("general_company_email"))
                enrichment.setdefault("general_company_phone", ce.get("general_company_phone"))

            project["enrichment"] = enrichment

            scored = score_sales_project(project)
            verified = verify_project(scored)

            old_sales = int(p.get("sales_score") or 0)
            new_sales = int(verified.get("sales_score") or 0)
            old_project = int(p.get("project_score") or 0)
            new_project = int(verified.get("project_score") or 0)
            new_land = verified.get("land_status") or p.get("land_status")
            new_stage = verified.get("stage") or p.get("stage")

            # Persist corrected raw too, so UI/detail and future calculations agree.
            new_raw = dict(raw)
            new_raw.update({
                "sales_score": new_sales,
                "project_score": new_project,
                "sales_priority": verified.get("sales_priority"),
                "recommended_action": verified.get("recommended_action"),
                "land_status": new_land,
                "stage": new_stage,
                "final_grade": verified.get("final_grade"),
                "final_verification_flags": verified.get("final_verification_flags", []),
                "sales_contact_state": verified.get("sales_contact_state", {}),
            })

            # Keep nested qualification consistent with visible business state.
            if isinstance(new_raw.get("qualification"), dict):
                q = dict(new_raw["qualification"])
                q["land_status"] = new_land
                if new_stage:
                    q["stage"] = new_stage
                new_raw["qualification"] = q

            conn.execute(
                text("""
                    UPDATE lead_projects
                    SET
                        sales_score = :sales_score,
                        project_score = :project_score,
                        sales_priority = :sales_priority,
                        recommended_action = :recommended_action,
                        land_status = :land_status,
                        stage = :stage,
                        final_grade = :final_grade,
                        final_verification_passed = :final_verification_passed,
                        raw = CAST(:raw AS jsonb),
                        last_seen_at = NOW()
                    WHERE id = CAST(:project_id AS uuid)
                """),
                {
                    "project_id": project_id,
                    "sales_score": new_sales,
                    "project_score": new_project,
                    "sales_priority": verified.get("sales_priority"),
                    "recommended_action": verified.get("recommended_action"),
                    "land_status": new_land,
                    "stage": new_stage,
                    "final_grade": verified.get("final_grade"),
                    "final_verification_passed": verified.get("final_verification_passed"),
                    "raw": json.dumps(new_raw, ensure_ascii=False),
                },
            )

            updated += 1
            if (old_sales != new_sales or old_project != new_project or p.get("land_status") != new_land) and len(changed_examples) < 20:
                changed_examples.append({
                    "id": project_id,
                    "company": p.get("resolved_company_name") or p.get("company_name"),
                    "sales_score_before": old_sales,
                    "sales_score_after": new_sales,
                    "project_score_before": old_project,
                    "project_score_after": new_project,
                    "land_before": p.get("land_status"),
                    "land_after": new_land,
                })

    return {
        "status": "success",
        "mode": "database_only_no_web",
        "rows_seen": rows_seen,
        "rows_updated": updated,
        "changed_examples": changed_examples,
    }
