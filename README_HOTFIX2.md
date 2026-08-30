# V4.1 Hotfix 2

Причина FAILURE:
предыдущий hotfix вернул из `score_sales_projects()` список,
а `qualification.py` ожидает словарь с ключами:
– `projects`
– `projects_scored_count`
– `priority_counts`

Из-за этого задача падала после enrichment.

## Заменить три файла
app/services/final_quality_gate.py
app/services/sales_scoring.py
app/tasks/qualification.py

## После push
Redeploy:
1. zemlya-ai-agent
2. zemlya-worker

Новых переменных Railway не нужно.

После redeploy новый поиск должен завершиться SUCCESS.
