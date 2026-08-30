# Rescore Hard Guard V7.4

Исправляет корневую ошибку V7.3:

старый `raw.qualification` мог иметь приоритет над актуальными колонками
`lead_projects.stage` и `lead_projects.land_status`.

V7.4 не вызывает sales_scoring/final_verification при пересчёте базы.
Он применяет финальные hard rules непосредственно к текущим колонкам PostgreSQL.

## Ключевое правило

Если `lead_projects.stage = 'V'`:
– `land_status = 'land_defined'`;
– `sales_score <= 59`.

Это применяется независимо от старого raw JSON.

## Контакты

– прямой телефон/email конкретного ЛПР – direct LPR;
– имя ЛПР без прямого канала – не direct;
– общий корпоративный email/телефон – general contact.

## Установка

Заменить только:

app/services/project_rescore.py

Redeploy только API `zemlya-ai-agent`.

После деплоя снова вызвать:
POST /projects/rescore-current

В Response body появится `diagnostics`, где для Мулти Милк будут показаны
stage_from_db, sales_before/after, land_before/after и rules_applied.
