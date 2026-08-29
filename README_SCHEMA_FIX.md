# Schema collision fix

Replace:

`app/services/project_persistence.py`

with the file from this patch and redeploy API + worker.

The persistence layer now uses isolated tables:

- lead_search_runs
- lead_projects
- lead_project_sources
- lead_project_history

Existing tables such as `projects` are left untouched.

No manual SQL migration is required.

After deploy run:

POST /qualification/discovery-test

Then check:

GET /projects
GET /projects/search-runs
