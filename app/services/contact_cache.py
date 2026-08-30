from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import create_engine, text

from app.core.config import settings


CACHE_TTL_DAYS = 30


def _engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


def ensure_contact_cache_schema() -> None:
    with _engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS company_contact_cache (
                inn TEXT PRIMARY KEY,
                legal_name TEXT,
                payload JSONB NOT NULL,
                checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_company_contact_cache_checked_at
            ON company_contact_cache (checked_at DESC)
        """))


def get_cached_contacts(inn: str | None, max_age_days: int = CACHE_TTL_DAYS) -> dict[str, Any] | None:
    if not inn:
        return None
    ensure_contact_cache_schema()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    with _engine().begin() as conn:
        row = conn.execute(
            text("""
                SELECT payload, checked_at
                FROM company_contact_cache
                WHERE inn = :inn
                  AND checked_at >= :cutoff
                LIMIT 1
            """),
            {"inn": inn, "cutoff": cutoff},
        ).mappings().first()
    if not row:
        return None
    payload = dict(row["payload"] or {})
    payload["cache_hit"] = True
    payload["cache_checked_at"] = row["checked_at"].isoformat() if row["checked_at"] else None
    return payload


def set_cached_contacts(inn: str | None, legal_name: str | None, payload: dict[str, Any]) -> None:
    if not inn:
        return
    ensure_contact_cache_schema()
    clean = dict(payload)
    clean.pop("cache_hit", None)
    clean.pop("cache_checked_at", None)
    with _engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO company_contact_cache (inn, legal_name, payload, checked_at)
                VALUES (:inn, :legal_name, CAST(:payload AS jsonb), NOW())
                ON CONFLICT (inn) DO UPDATE SET
                    legal_name = EXCLUDED.legal_name,
                    payload = EXCLUDED.payload,
                    checked_at = NOW()
            """),
            {
                "inn": inn,
                "legal_name": legal_name,
                "payload": json.dumps(clean, ensure_ascii=False),
            },
        )
