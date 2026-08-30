# Tavily Quota Safe V7.1

Причина текущего падения:
Tavily возвращает HTTP 432 – достигнут usage limit аккаунта.

Это не ошибка Railway, Redis, Celery или OpenAI.

## Что исправлено

1. Discovery больше не уничтожает текущий список при частично выполненном поиске.
   Если Tavily закончился на 2-й из 4 поисковых фраз, задача возвращает
   `blocked_tavily_quota`, а предыдущий успешный список остаётся активным.

2. Tavily discovery:
   – 4 поисковых запроса вместо прежних 6;
   – basic search вместо advanced;
   – до 6 результатов на запрос.

3. Full-page Extract:
   – максимум 25 URL вместо 45.

4. Company Resolution:
   – максимум 12 сильных проектов;
   – только Project Score >= 50.

5. Contact search:
   – максимум 8 сильнейших проектов;
   – только Project Score >= 60;
   – уже добавленный V7 cache по ИНН продолжает работать 30 дней.

## Заменить

app/services/tavily_search.py
app/services/page_enrichment.py
app/tasks/qualification.py

## Railway

Redeploy:
– zemlya-ai-agent
– zemlya-worker

Новых переменных нет.

## Важно

Если Tavily usage limit уже полностью исчерпан, новый поиск всё равно не
сможет получить свежие данные, пока лимит не будет увеличен/сброшен.
Патч предотвращает повреждение текущей выдачи и уменьшает расход после
восстановления доступного лимита.
