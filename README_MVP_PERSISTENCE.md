# Zemlya AI Agent – persistence MVP pack

This package adds persistent PostgreSQL storage without requiring an Alembic
revision. Tables are created idempotently with CREATE TABLE IF NOT EXISTS on
first use.

## Files to upload

Overwrite:
- app/tasks/qualification.py
- app/services/lead_gate.py

Add:
- app/services/project_persistence.py
- app/api/routes/projects.py

Merge into requirements.txt:
- openpyxl>=3.1,<4

Edit app/main.py manually:
```python
from app.api.routes.projects import router as projects_router
app.include_router(projects_router)
```

## Existing test endpoint
POST /qualification/discovery-test

The returned result now contains:
```json
{
  "search_run_id": "...",
  "persistence": {
    "active_saved": 1,
    "verification_saved": 3
  }
}
```

## New API
GET /projects
GET /projects?bucket=active
GET /projects?bucket=verification_pool
GET /projects?min_score=65
GET /projects?stage=A
GET /projects?company=ЭТМ
GET /projects?project_type=логист

GET /projects/{project_id}
Returns the project plus source history and field-change history.

GET /projects/search-runs
Shows historical discovery runs.

GET /projects/export.xlsx
Supports the same basic filters and downloads the current project database.

## Storage model
search_runs
projects
project_sources
project_history

Every project receives a stable UUID and a deterministic fingerprint.
Repeated discovery updates the same project when the fingerprint matches.
Changed fields are written to project_history.
