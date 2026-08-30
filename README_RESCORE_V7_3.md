# Zemlya AI – Rescore Existing V7.3

Проблема:
новая формула применялась только во время нового успешного pipeline.
Если Tavily не даёт закончить новый запуск, старые строки PostgreSQL
продолжают показывать старый Sales Score 84.

V7.3 решает это без Tavily и без OpenAI.

## Что делает

Добавляет:
POST /projects/rescore-current

Endpoint:
– читает все текущие `is_active = TRUE` проекты из PostgreSQL;
– подгружает уже сохранённые `lead_project_contacts`;
– применяет новую sales_scoring.py;
– применяет final_verification.py;
– обновляет sales_score, project_score, priority, action, land_status и raw JSON;
– не делает ни одного интернет/API запроса.

## Для Мулти Милк

При stage=V:
– land_status становится land_defined;
– Sales Score принудительно <= 59.

При наличии только общего корпоративного email и гендиректора без прямого
email/телефона:
– лид не может быть готов к контакту.

## Заменить

app/services/project_rescore.py
app/services/sales_scoring.py
app/services/final_verification.py
app/api/routes/projects.py

Redeploy:
– zemlya-ai-agent

Worker для самого пересчёта не нужен, но если оба сервиса используют один repo,
можно redeploy и worker для синхронизации версии.

После деплоя:
1. открыть dashboard;
2. нажать «Пересчитать текущую базу»;
3. дождаться сообщения;
4. страница перезагрузится.

Новый Tavily поиск запускать НЕ НУЖНО.
