# Hotfix V4.1

Причина ошибки:
app/tasks/qualification.py импортирует `score_sales_projects`,
а новый app/services/sales_scoring.py содержал только `score_sales_readiness`.

Что делать:
1. Заменить только `app/services/sales_scoring.py`
2. Push в GitHub
3. Redeploy `zemlya-ai-agent`
4. Redeploy `zemlya-worker`

Новых переменных Railway не требуется.
