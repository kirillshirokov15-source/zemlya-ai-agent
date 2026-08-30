from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


_ENGINE: Engine | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


def _engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            _db_url(),
            pool_pre_ping=True,
            pool_recycle=300,
            future=True,
        )
    return _ENGINE


DDL = """
CREATE TABLE IF NOT EXISTS lead_search_runs (
    id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    queries_used INTEGER,
    discovered_count INTEGER,
    extracted_count INTEGER,
    qualified_count INTEGER,
    active_count INTEGER,
    verification_count INTEGER,
    rejected_count INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS lead_projects (
    id UUID PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    bucket TEXT NOT NULL,
    company_name TEXT,
    project_type TEXT,
    project_summary TEXT,
    location TEXT,
    investment_rub NUMERIC,
    stage TEXT,
    land_status TEXT,
    signal_status TEXT,
    confidence TEXT,
    lead_score INTEGER,
    priority TEXT,
    recommended_action TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    last_search_run_id UUID REFERENCES lead_search_runs(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_lead_projects_bucket ON lead_projects(bucket);
CREATE INDEX IF NOT EXISTS ix_lead_projects_lead_score ON lead_projects(lead_score DESC);
CREATE INDEX IF NOT EXISTS ix_lead_projects_stage ON lead_projects(stage);
CREATE INDEX IF NOT EXISTS ix_lead_projects_company_name ON lead_projects(company_name);
CREATE INDEX IF NOT EXISTS ix_lead_projects_last_seen_at ON lead_projects(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS lead_project_sources (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES lead_projects(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    title TEXT,
    domain TEXT,
    source_tier TEXT,
    search_query TEXT,
    search_score DOUBLE PRECISION,
    published_date TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE(project_id, url)
);

CREATE INDEX IF NOT EXISTS ix_lead_project_sources_project_id
    ON lead_project_sources(project_id);

CREATE TABLE IF NOT EXISTS lead_project_history (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES lead_projects(id) ON DELETE CASCADE,
    search_run_id UUID REFERENCES lead_search_runs(id) ON DELETE SET NULL,
    changed_at TIMESTAMPTZ NOT NULL,
    changed_fields JSONB NOT NULL,
    snapshot JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_lead_project_history_project_id_changed_at
    ON lead_project_history(project_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS lead_project_contacts (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES lead_projects(id) ON DELETE CASCADE,
    name TEXT,
    role TEXT,
    email TEXT,
    phone TEXT,
    profile_url TEXT,
    source_url TEXT NOT NULL,
    confidence TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    UNIQUE(project_id, source_url, name, role, email, phone)
);

CREATE INDEX IF NOT EXISTS ix_lead_project_contacts_project_id
    ON lead_project_contacts(project_id);
"""

SCHEMA_UPGRADES = [
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS project_score INTEGER",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS sales_score INTEGER",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS sales_priority TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS resolved_company_name TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS legal_name TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS inn TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS ogrn TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS website TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS enrichment_status TEXT",
    "ALTER TABLE lead_projects ADD COLUMN IF NOT EXISTS last_enriched_at TIMESTAMPTZ",
]


PROJECT_FIELDS = (
    "bucket",
    "company_name",
    "project_type",
    "project_summary",
    "location",
    "investment_rub",
    "stage",
    "land_status",
    "signal_status",
    "confidence",
    "lead_score",
    "project_score",
    "sales_score",
    "priority",
    "sales_priority",
    "resolved_company_name",
    "legal_name",
    "inn",
    "ogrn",
    "website",
    "enrichment_status",
    "recommended_action",
)


def ensure_schema() -> None:
    engine = _engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(DDL)
        for statement in SCHEMA_UPGRADES:
            conn.exec_driver_sql(statement)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(s.split())


def _fingerprint(project: dict[str, Any]) -> str:
    # Stable enough for MVP while staying conservative.
    # Company is the strongest identity signal when known.
    company = _norm(project.get("company_name"))
    ptype = _norm(project.get("project_type"))
    location = _norm(project.get("location"))
    summary = _norm(project.get("project_summary"))

    if company:
        seed = f"company|{company}|{ptype}|{location}"
    else:
        # Keep only a compact summary prefix to reduce accidental drift
        # from minor LLM rewording.
        summary_tokens = summary.split()[:18]
        seed = f"anon|{ptype}|{location}|{' '.join(summary_tokens)}"

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _snapshot(project: dict[str, Any]) -> dict[str, Any]:
    return {field: project.get(field) for field in PROJECT_FIELDS}


def _changed_fields(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    changes = {}
    for field in PROJECT_FIELDS:
        if old.get(field) != new.get(field):
            changes[field] = {
                "from": old.get(field),
                "to": new.get(field),
            }
    return changes


def create_search_run(
    *,
    queries_used: int | None,
    discovered_count: int | None,
    metadata: dict[str, Any] | None = None,
) -> str:
    ensure_schema()
    run_id = str(uuid.uuid4())
    now = _now()
    with _engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO lead_search_runs (
                    id, started_at, status, queries_used,
                    discovered_count, metadata
                )
                VALUES (
                    CAST(:id AS uuid), :started_at, 'running',
                    :queries_used, :discovered_count,
                    CAST(:metadata AS jsonb)
                )
            """),
            {
                "id": run_id,
                "started_at": now,
                "queries_used": queries_used,
                "discovered_count": discovered_count,
                "metadata": json.dumps(_jsonable(metadata or {}), ensure_ascii=False),
            },
        )
    return run_id


def finish_search_run(
    run_id: str,
    *,
    status: str,
    extracted_count: int | None = None,
    qualified_count: int | None = None,
    active_count: int | None = None,
    verification_count: int | None = None,
    rejected_count: int | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> None:
    now = _now()
    with _engine().begin() as conn:
        conn.execute(
            text("""
                UPDATE lead_search_runs
                SET finished_at = :finished_at,
                    status = :status,
                    extracted_count = :extracted_count,
                    qualified_count = :qualified_count,
                    active_count = :active_count,
                    verification_count = :verification_count,
                    rejected_count = :rejected_count,
                    metadata = metadata || CAST(:metadata_patch AS jsonb)
                WHERE id = CAST(:id AS uuid)
            """),
            {
                "id": run_id,
                "finished_at": now,
                "status": status,
                "extracted_count": extracted_count,
                "qualified_count": qualified_count,
                "active_count": active_count,
                "verification_count": verification_count,
                "rejected_count": rejected_count,
                "metadata_patch": json.dumps(
                    _jsonable(metadata_patch or {}),
                    ensure_ascii=False,
                ),
            },
        )


def _source_rows(project: dict[str, Any]) -> list[dict[str, Any]]:
    sources = project.get("sources") or []
    if not sources:
        primary = project.get("primary_source")
        if isinstance(primary, dict):
            sources = [primary]
    return [x for x in sources if isinstance(x, dict) and x.get("url")]


def upsert_project(
    project: dict[str, Any],
    *,
    bucket: str,
    search_run_id: str,
) -> str:
    ensure_schema()
    now = _now()

    payload = dict(project)
    payload["bucket"] = bucket
    enrichment = payload.get("enrichment") or {}
    payload["enrichment_status"] = enrichment.get("status")

    fingerprint = _fingerprint(payload)
    snapshot = _snapshot(payload)

    with _engine().begin() as conn:
        existing = conn.execute(
            text("""
                SELECT *
                FROM lead_projects
                WHERE fingerprint = :fingerprint
                FOR UPDATE
            """),
            {"fingerprint": fingerprint},
        ).mappings().first()

        if existing:
            project_id = str(existing["id"])
            old = {field: existing.get(field) for field in PROJECT_FIELDS}
            changes = _changed_fields(old, snapshot)

            conn.execute(
                text("""
                    UPDATE lead_projects
                    SET bucket = :bucket,
                        company_name = :company_name,
                        project_type = :project_type,
                        project_summary = :project_summary,
                        location = :location,
                        investment_rub = :investment_rub,
                        stage = :stage,
                        land_status = :land_status,
                        signal_status = :signal_status,
                        confidence = :confidence,
                        lead_score = :lead_score,
                        project_score = :project_score,
                        sales_score = :sales_score,
                        priority = :priority,
                        sales_priority = :sales_priority,
                        resolved_company_name = :resolved_company_name,
                        legal_name = :legal_name,
                        inn = :inn,
                        ogrn = :ogrn,
                        website = :website,
                        enrichment_status = :enrichment_status,
                        last_enriched_at = CASE WHEN :enrichment_status IS NOT NULL THEN :last_seen_at ELSE last_enriched_at END,
                        recommended_action = :recommended_action,
                        last_seen_at = :last_seen_at,
                        last_search_run_id = CAST(:last_search_run_id AS uuid),
                        is_active = TRUE,
                        raw = CAST(:raw AS jsonb)
                    WHERE id = CAST(:id AS uuid)
                """),
                {
                    "id": project_id,
                    **snapshot,
                    "last_seen_at": now,
                    "last_search_run_id": search_run_id,
                    "raw": json.dumps(_jsonable(project), ensure_ascii=False),
                },
            )

            if changes:
                conn.execute(
                    text("""
                        INSERT INTO lead_project_history (
                            id, project_id, search_run_id, changed_at,
                            changed_fields, snapshot
                        )
                        VALUES (
                            CAST(:id AS uuid), CAST(:project_id AS uuid),
                            CAST(:search_run_id AS uuid), :changed_at,
                            CAST(:changed_fields AS jsonb),
                            CAST(:snapshot AS jsonb)
                        )
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "project_id": project_id,
                        "search_run_id": search_run_id,
                        "changed_at": now,
                        "changed_fields": json.dumps(
                            _jsonable(changes),
                            ensure_ascii=False,
                        ),
                        "snapshot": json.dumps(
                            _jsonable(snapshot),
                            ensure_ascii=False,
                        ),
                    },
                )
        else:
            project_id = str(uuid.uuid4())
            conn.execute(
                text("""
                    INSERT INTO lead_projects (
                        id, fingerprint, bucket, company_name, project_type,
                        project_summary, location, investment_rub, stage,
                        land_status, signal_status, confidence, lead_score,
                        project_score, sales_score, priority, sales_priority,
                        resolved_company_name, legal_name, inn, ogrn, website, enrichment_status, last_enriched_at,
                        recommended_action, first_seen_at,
                        last_seen_at, last_search_run_id, is_active, raw
                    )
                    VALUES (
                        CAST(:id AS uuid), :fingerprint, :bucket,
                        :company_name, :project_type, :project_summary,
                        :location, :investment_rub, :stage, :land_status,
                        :signal_status, :confidence, :lead_score, :project_score,
                        :sales_score, :priority, :sales_priority, :resolved_company_name, :legal_name, :inn,
                        :ogrn, :website, :enrichment_status,
                        CASE WHEN :enrichment_status IS NOT NULL THEN :first_seen_at ELSE NULL END,
                        :recommended_action, :first_seen_at, :last_seen_at,
                        CAST(:last_search_run_id AS uuid), TRUE,
                        CAST(:raw AS jsonb)
                    )
                """),
                {
                    "id": project_id,
                    "fingerprint": fingerprint,
                    **snapshot,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "last_search_run_id": search_run_id,
                    "raw": json.dumps(_jsonable(project), ensure_ascii=False),
                },
            )

            conn.execute(
                text("""
                    INSERT INTO lead_project_history (
                        id, project_id, search_run_id, changed_at,
                        changed_fields, snapshot
                    )
                    VALUES (
                        CAST(:id AS uuid), CAST(:project_id AS uuid),
                        CAST(:search_run_id AS uuid), :changed_at,
                        CAST(:changed_fields AS jsonb),
                        CAST(:snapshot AS jsonb)
                    )
                """),
                {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "search_run_id": search_run_id,
                    "changed_at": now,
                    "changed_fields": json.dumps(
                        {"created": True},
                        ensure_ascii=False,
                    ),
                    "snapshot": json.dumps(
                        _jsonable(snapshot),
                        ensure_ascii=False,
                    ),
                },
            )

        for source in _source_rows(project):
            conn.execute(
                text("""
                    INSERT INTO lead_project_sources (
                        id, project_id, url, title, domain, source_tier,
                        search_query, search_score, published_date,
                        first_seen_at, last_seen_at, evidence
                    )
                    VALUES (
                        CAST(:id AS uuid), CAST(:project_id AS uuid),
                        :url, :title, :domain, :source_tier, :search_query,
                        :search_score, :published_date, :first_seen_at,
                        :last_seen_at, CAST(:evidence AS jsonb)
                    )
                    ON CONFLICT (project_id, url)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        domain = EXCLUDED.domain,
                        source_tier = EXCLUDED.source_tier,
                        search_query = EXCLUDED.search_query,
                        search_score = EXCLUDED.search_score,
                        published_date = EXCLUDED.published_date,
                        last_seen_at = EXCLUDED.last_seen_at,
                        evidence = EXCLUDED.evidence
                """),
                {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "url": source.get("url"),
                    "title": source.get("title"),
                    "domain": source.get("domain"),
                    "source_tier": source.get("source_tier"),
                    "search_query": source.get("search_query"),
                    "search_score": source.get("search_score"),
                    "published_date": source.get("published_date"),
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "evidence": json.dumps(
                        _jsonable(source.get("evidence") or []),
                        ensure_ascii=False,
                    ),
                },
            )

        enrichment = project.get("enrichment") or {}
        for contact in enrichment.get("contacts") or []:
            if not isinstance(contact, dict) or not contact.get("source_url"):
                continue
            conn.execute(
                text("""
                    INSERT INTO lead_project_contacts (
                        id, project_id, name, role, email, phone, profile_url,
                        source_url, confidence, first_seen_at, last_seen_at
                    )
                    VALUES (
                        CAST(:id AS uuid), CAST(:project_id AS uuid),
                        :name, :role, :email, :phone, :profile_url,
                        :source_url, :confidence, :first_seen_at, :last_seen_at
                    )
                    ON CONFLICT (project_id, source_url, name, role, email, phone)
                    DO UPDATE SET
                        profile_url = EXCLUDED.profile_url,
                        confidence = EXCLUDED.confidence,
                        last_seen_at = EXCLUDED.last_seen_at
                """),
                {
                    "id": str(uuid.uuid4()),
                    "project_id": project_id,
                    "name": contact.get("name"),
                    "role": contact.get("role"),
                    "email": contact.get("email"),
                    "phone": contact.get("phone"),
                    "profile_url": contact.get("profile_url"),
                    "source_url": contact.get("source_url"),
                    "confidence": contact.get("confidence"),
                    "first_seen_at": now,
                    "last_seen_at": now,
                },
            )

    return project_id


def persist_pipeline_results(
    *,
    search_run_id: str,
    active_scored_projects: list[dict[str, Any]],
    verification_items: list[dict[str, Any]],
) -> dict[str, Any]:
    active_ids = []
    verification_ids = []

    for project in active_scored_projects:
        active_ids.append(
            upsert_project(
                project,
                bucket="active",
                search_run_id=search_run_id,
            )
        )

    for item in verification_items:
        q = item.get("qualification") or {}
        project = {
            "company_name": q.get("company_name"),
            "project_type": q.get("project_type"),
            "project_summary": q.get("project_summary"),
            "location": q.get("location"),
            "investment_rub": q.get("investment_rub"),
            "stage": q.get("stage"),
            "land_status": q.get("land_status"),
            "signal_status": q.get("signal_status"),
            "confidence": q.get("confidence"),
            "lead_score": None,
            "project_score": None,
            "sales_score": None,
            "priority": None,
            "sales_priority": None,
            "resolved_company_name": None,
            "legal_name": None,
            "inn": None,
            "ogrn": None,
            "website": None,
            "enrichment": {"status": "not_run", "contacts": []},
            "recommended_action": "manual_verification",
            "sources": [{
                "title": item.get("title"),
                "url": item.get("url"),
                "domain": None,
                "source_tier": None,
                "search_query": item.get("query"),
                "search_score": item.get("score"),
                "published_date": item.get("published_date"),
                "evidence": q.get("evidence") or [],
            }],
            "lead_gate": item.get("lead_gate"),
            "raw_source": item,
        }
        verification_ids.append(
            upsert_project(
                project,
                bucket="verification_pool",
                search_run_id=search_run_id,
            )
        )

    # Reconcile the "current list" only after all rows of this run were
    # persisted successfully. Previous rows remain in the database/history,
    # but are no longer shown as current leads.
    with _engine().begin() as conn:
        deactivated = conn.execute(
            text("""
                UPDATE lead_projects
                SET is_active = FALSE
                WHERE is_active = TRUE
                  AND (
                      last_search_run_id IS NULL
                      OR last_search_run_id <> CAST(:search_run_id AS uuid)
                  )
            """),
            {"search_run_id": search_run_id},
        ).rowcount

    return {
        "active_saved": len(active_ids),
        "verification_saved": len(verification_ids),
        "stale_rows_deactivated": int(deactivated or 0),
        "project_ids": {
            "active": active_ids,
            "verification_pool": verification_ids,
        },
    }


def list_projects(
    *,
    bucket: str | None = None,
    min_score: int | None = None,
    min_sales_score: int | None = None,
    sales_priority: str | None = None,
    stage: str | None = None,
    company: str | None = None,
    project_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_schema()

    clauses = ["is_active = TRUE"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if bucket:
        clauses.append("bucket = :bucket")
        params["bucket"] = bucket
    if min_score is not None:
        clauses.append("COALESCE(lead_score, 0) >= :min_score")
        params["min_score"] = min_score
    if min_sales_score is not None:
        clauses.append("COALESCE(sales_score, 0) >= :min_sales_score")
        params["min_sales_score"] = min_sales_score
    if sales_priority:
        clauses.append("sales_priority = :sales_priority")
        params["sales_priority"] = sales_priority
    if stage:
        clauses.append("stage = :stage")
        params["stage"] = stage
    if company:
        clauses.append("COALESCE(resolved_company_name, company_name) ILIKE :company")
        params["company"] = f"%{company}%"
    if project_type:
        clauses.append("project_type ILIKE :project_type")
        params["project_type"] = f"%{project_type}%"

    sql = f"""
        SELECT
            id::text AS id,
            bucket,
            COALESCE(resolved_company_name, company_name) AS company_name,
            company_name AS source_company_name,
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
            priority,
            sales_priority,
            legal_name,
            inn,
            ogrn,
            website,
            enrichment_status,
            recommended_action,
            first_seen_at,
            last_seen_at
        FROM lead_projects
        WHERE {' AND '.join(clauses)}
        ORDER BY
            sales_score DESC NULLS LAST,
            project_score DESC NULLS LAST,
            lead_score DESC NULLS LAST,
            last_seen_at DESC
        LIMIT :limit OFFSET :offset
    """

    with _engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def get_project(project_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with _engine().connect() as conn:
        project = conn.execute(
            text("""
                SELECT
                    id::text AS id,
                    bucket,
                    COALESCE(resolved_company_name, company_name) AS company_name,
                    company_name AS source_company_name,
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
                    priority,
                    sales_priority,
                    legal_name,
                    inn,
                    ogrn,
                    website,
                    enrichment_status,
                    last_enriched_at,
                    recommended_action,
                    first_seen_at,
                    last_seen_at,
                    raw
                FROM lead_projects
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": project_id},
        ).mappings().first()

        if not project:
            return None

        sources = conn.execute(
            text("""
                SELECT
                    id::text AS id,
                    url, title, domain, source_tier, search_query,
                    search_score, published_date, first_seen_at,
                    last_seen_at, evidence
                FROM lead_project_sources
                WHERE project_id = CAST(:id AS uuid)
                ORDER BY last_seen_at DESC
            """),
            {"id": project_id},
        ).mappings().all()

        contacts = conn.execute(
            text("""
                SELECT
                    id::text AS id, name, role, email, phone, profile_url,
                    source_url, confidence, first_seen_at, last_seen_at
                FROM lead_project_contacts
                WHERE project_id = CAST(:id AS uuid)
                ORDER BY
                    CASE WHEN email IS NOT NULL OR phone IS NOT NULL THEN 0 ELSE 1 END,
                    last_seen_at DESC
            """),
            {"id": project_id},
        ).mappings().all()

        history = conn.execute(
            text("""
                SELECT
                    id::text AS id,
                    search_run_id::text AS search_run_id,
                    changed_at, changed_fields, snapshot
                FROM lead_project_history
                WHERE project_id = CAST(:id AS uuid)
                ORDER BY changed_at DESC
                LIMIT 100
            """),
            {"id": project_id},
        ).mappings().all()

    result = dict(project)
    result["sources"] = [dict(x) for x in sources]
    result["contacts"] = [dict(x) for x in contacts]
    result["history"] = [dict(x) for x in history]
    return result


def get_search_run(run_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with _engine().connect() as conn:
        row = conn.execute(
            text("""
                SELECT
                    id::text AS id, started_at, finished_at, status, queries_used,
                    discovered_count, extracted_count, qualified_count,
                    active_count, verification_count, rejected_count, metadata
                FROM lead_search_runs
                WHERE id = CAST(:id AS uuid)
            """),
            {"id": run_id},
        ).mappings().first()
    return dict(row) if row else None


def list_search_runs(limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema()
    with _engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    id::text AS id,
                    started_at, finished_at, status, queries_used,
                    discovered_count, extracted_count, qualified_count,
                    active_count, verification_count, rejected_count,
                    metadata
                FROM lead_search_runs
                ORDER BY started_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()
    return [dict(x) for x in rows]
