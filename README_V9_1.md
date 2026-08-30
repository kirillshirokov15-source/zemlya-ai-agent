# V9.1 – queries_used compatibility hotfix

Исправляет ошибку:

`column "queries_used" is of type integer but expression is of type text[]`

Причина:
новый Tavily discovery возвращает `queries_used` как список строк,
а `lead_search_runs.queries_used` хранится как INTEGER.

Исправление:
`create_search_run()` теперь принимает:
- int
- list[str]
- tuple[str, ...]
- None

Если приходит список, в БД записывается `len(queries_used)`.

## Что заменить

Только:

`app/services/project_persistence.py`

## Redeploy

Нужно redeploy:
- zemlya-ai-agent
- zemlya-worker

После деплоя снова выполнить:
POST /projects/search-runs/start

Затем проверить:
GET /projects/tasks/{task_id}
