# V8.2 Compatibility Hotfix

Исправляет совместимость Sales Score V8 с существующим `app/tasks/qualification.py`.

## Исправлено

1. Возвращена функция:
   `score_sales_projects(projects)`

Она снова возвращает словарь:
- projects_scored_count
- priority_counts
- projects

2. Возвращена функция:
   `verify_and_rank(projects)`

Она возвращает:
- projects
- verified_count
- passed_count
- needs_attention_count

3. Добавлен legacy alias:
   `score_sales_readiness(projects)`

Формула Sales Score V8 не изменена.

## Установка

Заменить:

- app/services/sales_scoring.py
- app/services/final_verification.py
- app/services/project_rescore.py

Затем redeploy:
- zemlya-ai-agent
- zemlya-worker

После успешного деплоя:
POST /projects/rescore-current

Новый Tavily search пока не запускать.
