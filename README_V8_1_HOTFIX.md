# V8.1 hotfix

Исправляет ImportError после V8.

Существующий `app/tasks/qualification.py` импортирует историческую функцию
`score_sales_projects`, а V8 оставил только `score_sales_project`.

V8.1 возвращает batch-wrapper:

    def score_sales_projects(projects):
        return [score_sales_project(project) for project in projects]

Логика V8 не меняется.

## Установка
Заменить только:
app/services/sales_scoring.py

После этого redeploy:
– zemlya-ai-agent
– zemlya-worker
