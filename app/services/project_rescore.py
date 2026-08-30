from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text

from app.core.config import settings


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
    return [dict(r) for r in rows]


def _is_lpr(contact: dict[str, Any]) -> bool:
    name = str(contact.get("name") or "").strip()
    role = str(contact.get("role") or "").lower()
    if not name:
        return False
    return any(x in role for x in (
        "генераль", "директор", "собствен", "владел", "учредител",
        "руководител", "development", "развити", "инвест",
        "строител", "недвижим", "земел", "project manager",
    ))


def _is_general_contact(contact: dict[str, Any]) -> bool:
    role = str(contact.get("role") or "").lower()
    name = str(contact.get("name") or "").lower()
    has_channel = bool(contact.get("email") or contact.get("phone"))
    if not has_channel:
        return False
    return any(x in role or x in name for x in (
        "корпоратив", "общий", "company", "офис", "приемн",
        "приёмн", "контакт", "info",
    )) or not _is_lpr(contact)


def _contact_state(contacts: list[dict[str, Any]], raw: dict[str, Any]) -> dict[str, bool]:
    named_lpr = [c for c in contacts if _is_lpr(c)]
    direct_lpr = [c for c in named_lpr if c.get("email") or c.get("phone")]

    general_rows = [c for c in contacts if _is_general_contact(c)]
    ce = raw.get("contact_enrichment") or {}
    enr = raw.get("enrichment") or {}

    has_general = bool(
        general_rows
        or ce.get("general_company_email")
        or ce.get("general_company_phone")
        or enr.get("general_company_email")
        or enr.get("general_company_phone")
    )

    return {
        "has_named_lpr": bool(named_lpr),
        "has_direct_lpr": bool(direct_lpr),
        "has_general_contact": has_general,
        "has_any_contact": bool(direct_lpr) or has_general,
    }


def _final_priority(score: int, has_direct_lpr: bool) -> tuple[str, str, str]:
    if score >= 90 and has_direct_lpr:
        return "A_hot", "contact_now", "A_ready"
    if score >= 70:
        return "B_work", "find_decision_maker", "B_high"
    if score >= 50:
        return "C_verify", "verify_project_status", "C_verify"
    return "D_research", "research_later", "D_low"


def _apply_hard_rules(
    *,
    old_sales: int,
    old_project: int,
    stage: str | None,
    land_status: str | None,
    contacts: list[dict[str, Any]],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """
    Final deterministic guard based on CURRENT DB columns.

    It intentionally does not trust raw.qualification.stage/land_status,
    because those values can be historical/stale.
    """
    score = int(old_sales or 0)
    project_score = int(old_project or 0)
    land = land_status
    flags: list[str] = []

    cs = _contact_state(contacts, raw)

    # Stage V is authoritative: the plot/site is already selected/provided.
    if stage == "V":
        land = "land_defined"
        score = min(score, 59)
        flags.extend(["stage_v_site_defined", "land_status_forced_to_defined"])

    # Land already defined is low readiness for the core land-acquisition sale.
    if land == "land_defined":
        score = min(score, 59)
        if "land_already_defined" not in flags:
            flags.append("land_already_defined")

    # Contact-readiness caps.
    if not cs["has_named_lpr"] and not cs["has_any_contact"]:
        score = min(score, 49)
        flags.append("no_lpr_no_contact")
    elif cs["has_named_lpr"] and not cs["has_any_contact"]:
        score = min(score, 59)
        flags.append("named_lpr_no_contact")
    elif cs["has_general_contact"] and not cs["has_direct_lpr"]:
        score = min(score, 79)
        flags.append("general_contact_only")
    elif not cs["has_direct_lpr"]:
        score = min(score, 79)
        flags.append("no_direct_lpr")

    # Stage G is too late for the primary land service.
    if stage == "G":
        project_score = min(project_score, 45)
        score = min(score, 39)
        flags.append("construction_started")

    score = max(0, min(100, score))
    priority, action, grade = _final_priority(score, cs["has_direct_lpr"])

    return {
        "sales_score": score,
        "project_score": project_score,
        "land_status": land,
        "sales_priority": priority,
        "recommended_action": action,
        "final_grade": grade,
        "contact_state": cs,
        "flags": flags,
    }


def rescore_current_projects() -> dict[str, Any]:
    """
    Re-score current PostgreSQL rows only.
    No Tavily, OpenAI, Redis, Celery or external HTTP calls.
    """
    updated = 0
    rows_seen = 0
    changed_examples: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    with _engine().begin() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    id,
                    company_name,
                    resolved_company_name,
                    stage,
                    land_status,
                    project_score,
                    lead_score,
                    sales_score,
                    raw
                FROM lead_projects
                WHERE is_active = TRUE
                ORDER BY sales_score DESC NULLS LAST
            """)
        ).mappings().all()

        for row in rows:
            rows_seen += 1
            p = dict(row)
            project_id = str(p["id"])
            raw = dict(p.get("raw") or {})
            contacts = _load_contacts(conn, project_id)

            old_sales = int(p.get("sales_score") or 0)
            old_project = int(p.get("project_score") or p.get("lead_score") or 0)
            old_land = p.get("land_status")
            stage = p.get("stage")

            result = _apply_hard_rules(
                old_sales=old_sales,
                old_project=old_project,
                stage=stage,
                land_status=old_land,
                contacts=contacts,
                raw=raw,
            )

            new_raw = dict(raw)
            new_raw.update({
                "sales_score": result["sales_score"],
                "project_score": result["project_score"],
                "sales_priority": result["sales_priority"],
                "recommended_action": result["recommended_action"],
                "stage": stage,
                "land_status": result["land_status"],
                "final_grade": result["final_grade"],
                "final_verification_flags": result["flags"],
                "sales_contact_state": result["contact_state"],
            })

            # Make stale nested qualification consistent too.
            if isinstance(new_raw.get("qualification"), dict):
                q = dict(new_raw["qualification"])
                q["stage"] = stage
                q["land_status"] = result["land_status"]
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
                        final_grade = :final_grade,
                        raw = CAST(:raw AS jsonb),
                        last_seen_at = NOW()
                    WHERE id = CAST(:project_id AS uuid)
                """),
                {
                    "project_id": project_id,
                    "sales_score": result["sales_score"],
                    "project_score": result["project_score"],
                    "sales_priority": result["sales_priority"],
                    "recommended_action": result["recommended_action"],
                    "land_status": result["land_status"],
                    "final_grade": result["final_grade"],
                    "raw": json.dumps(new_raw, ensure_ascii=False),
                },
            )
            updated += 1

            changed = (
                old_sales != result["sales_score"]
                or old_project != result["project_score"]
                or old_land != result["land_status"]
            )
            if changed and len(changed_examples) < 50:
                changed_examples.append({
                    "id": project_id,
                    "company": p.get("resolved_company_name") or p.get("company_name"),
                    "stage": stage,
                    "sales_score_before": old_sales,
                    "sales_score_after": result["sales_score"],
                    "project_score_before": old_project,
                    "project_score_after": result["project_score"],
                    "land_before": old_land,
                    "land_after": result["land_status"],
                    "contact_state": result["contact_state"],
                    "rules_applied": result["flags"],
                })

            company_text = str(
                p.get("resolved_company_name") or p.get("company_name") or ""
            ).lower()
            if "мулти" in company_text or "multi" in company_text:
                diagnostics.append({
                    "company": p.get("resolved_company_name") or p.get("company_name"),
                    "stage_from_db": stage,
                    "land_from_db_before": old_land,
                    "sales_before": old_sales,
                    "sales_after": result["sales_score"],
                    "land_after": result["land_status"],
                    "contact_state": result["contact_state"],
                    "rules_applied": result["flags"],
                })

    return {
        "status": "success",
        "mode": "database_only_hard_guard_v7_4",
        "rows_seen": rows_seen,
        "rows_updated": updated,
        "changed_count": len(changed_examples),
        "changed_examples": changed_examples,
        "diagnostics": diagnostics,
    }
