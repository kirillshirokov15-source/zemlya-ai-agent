"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("legal_name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("revenue", sa.Numeric(18, 2), nullable=True),
        sa.Column("profit", sa.Numeric(18, 2), nullable=True),
        sa.Column("group_name", sa.String(length=512), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=True),
        sa.Column("is_bankrupt", sa.Boolean(), nullable=False),
        sa.Column("is_liquidating", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inn"),
    )
    op.create_index(op.f("ix_companies_inn"), "companies", ["inn"], unique=False)
    op.create_index(op.f("ix_companies_legal_name"), "companies", ["legal_name"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=800), nullable=False),
        sa.Column("industry", sa.String(length=255), nullable=True),
        sa.Column("description_short", sa.Text(), nullable=True),
        sa.Column("sales_argument_short", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=512), nullable=True),
        sa.Column("stage", sa.String(length=8), nullable=True),
        sa.Column("land_status", sa.String(length=64), nullable=True),
        sa.Column("signal_status", sa.String(length=64), nullable=True),
        sa.Column("investment_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("first_announced_at", sa.Date(), nullable=True),
        sa.Column("last_significant_event_at", sa.Date(), nullable=True),
        sa.Column("needs_manual_review", sa.Boolean(), nullable=False),
        sa.Column("manual_review_reason", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("current_score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_current_score"), "projects", ["current_score"], unique=False)
    op.create_index(op.f("ix_projects_land_status"), "projects", ["land_status"], unique=False)
    op.create_index(op.f("ix_projects_last_significant_event_at"), "projects", ["last_significant_event_at"], unique=False)
    op.create_index(op.f("ix_projects_signal_status"), "projects", ["signal_status"], unique=False)
    op.create_index(op.f("ix_projects_stage"), "projects", ["stage"], unique=False)
    op.create_index(op.f("ix_projects_title"), "projects", ["title"], unique=False)

    op.create_table(
        "search_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("candidates_found", sa.Integer(), nullable=False),
        sa.Column("leads_qualified", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_search_runs_status"), "search_runs", ["status"], unique=False)

    op.create_table(
        "project_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "company_id", "role", name="uq_project_company_role"),
    )
    op.create_index(op.f("ix_project_companies_company_id"), "project_companies", ["company_id"], unique=False)
    op.create_index(op.f("ix_project_companies_project_id"), "project_companies", ["project_id"], unique=False)

    op.create_table(
        "people",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=512), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("priority_reason", sa.Text(), nullable=True),
        sa.Column("current_role_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_people_company_id"), "people", ["company_id"], unique=False)
    op.create_index(op.f("ix_people_full_name"), "people", ["full_name"], unique=False)

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fact_type", sa.String(length=128), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("source_level", sa.Integer(), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_fact_type"), "sources", ["fact_type"], unique=False)
    op.create_index(op.f("ix_sources_project_id"), "sources", ["project_id"], unique=False)

    op.create_table(
        "lead_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lead_scores_project_id"), "lead_scores", ["project_id"], unique=False)
    op.create_index(op.f("ix_lead_scores_total_score"), "lead_scores", ["total_score"], unique=False)

    op.create_table(
        "history_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_history_events_event_type"), "history_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_history_events_project_id"), "history_events", ["project_id"], unique=False)

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_type", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_best", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contacts_company_id"), "contacts", ["company_id"], unique=False)
    op.create_index(op.f("ix_contacts_contact_type"), "contacts", ["contact_type"], unique=False)
    op.create_index(op.f("ix_contacts_person_id"), "contacts", ["person_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_contacts_person_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_contact_type"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_company_id"), table_name="contacts")
    op.drop_table("contacts")

    op.drop_index(op.f("ix_history_events_project_id"), table_name="history_events")
    op.drop_index(op.f("ix_history_events_event_type"), table_name="history_events")
    op.drop_table("history_events")

    op.drop_index(op.f("ix_lead_scores_total_score"), table_name="lead_scores")
    op.drop_index(op.f("ix_lead_scores_project_id"), table_name="lead_scores")
    op.drop_table("lead_scores")

    op.drop_index(op.f("ix_sources_project_id"), table_name="sources")
    op.drop_index(op.f("ix_sources_fact_type"), table_name="sources")
    op.drop_table("sources")

    op.drop_index(op.f("ix_people_full_name"), table_name="people")
    op.drop_index(op.f("ix_people_company_id"), table_name="people")
    op.drop_table("people")

    op.drop_index(op.f("ix_project_companies_project_id"), table_name="project_companies")
    op.drop_index(op.f("ix_project_companies_company_id"), table_name="project_companies")
    op.drop_table("project_companies")

    op.drop_index(op.f("ix_search_runs_status"), table_name="search_runs")
    op.drop_table("search_runs")

    op.drop_index(op.f("ix_projects_title"), table_name="projects")
    op.drop_index(op.f("ix_projects_stage"), table_name="projects")
    op.drop_index(op.f("ix_projects_signal_status"), table_name="projects")
    op.drop_index(op.f("ix_projects_last_significant_event_at"), table_name="projects")
    op.drop_index(op.f("ix_projects_land_status"), table_name="projects")
    op.drop_index(op.f("ix_projects_current_score"), table_name="projects")
    op.drop_table("projects")

    op.drop_index(op.f("ix_companies_legal_name"), table_name="companies")
    op.drop_index(op.f("ix_companies_inn"), table_name="companies")
    op.drop_table("companies")
