# Zemlya MVP schema fix v2

Cause of the 502:
the previous table-name replacement accidentally renamed Python symbols too.

This patch restores the public Python API:
- list_projects
- list_search_runs
- active_scored_projects

SQL tables remain isolated:
- lead_search_runs
- lead_projects
- lead_project_sources
- lead_project_history

## Apply
Replace only:
app/services/project_persistence.py

Then redeploy BOTH:
- zemlya-ai-agent API
- zemlya-worker

No SQL commands are required.

After deploy:
1. Open API root/health endpoint to confirm Uvicorn is alive.
2. POST /qualification/discovery-test
3. GET /tasks/{task_id}
4. GET /projects
5. GET /projects/search-runs
