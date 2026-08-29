# Zemlya AI Agent – Product V2

Крупный продуктовый апгрейд поверх работающего persistence MVP.

## Что добавлено

### 1. Два независимых рейтинга
- `project_score` – насколько проект подходит услугам «Земля без торгов».
- `sales_score` – насколько лид готов к коммерческой работе прямо сейчас.

Анонимный проект больше не может автоматически считаться идеальным sales-лидом только из-за хорошего земельного сигнала.

### 2. Company resolution + contact enrichment
Новый сервис `company_enrichment.py`:
- пытается определить инвестора/компанию для анонимного проекта;
- сохраняет resolved company отдельно, не ломая fingerprint старой записи;
- ищет юридическое наименование, ИНН, ОГРН, сайт;
- ищет публичные контакты и ЛПР;
- допускает только сведения, подтвержденные поисковыми результатами;
- использует существующие `TAVILY_API_KEY` и `OPENAI_API_KEY`;
- ошибки enrichment не роняют весь pipeline.

По умолчанию enrichment выполняется максимум для 10 проектов с Project Score >= 45 за один запуск.

### 3. Temporal Filter V2
`qualification.py` больше не считает любую дату в теле страницы датой проекта.
Для stale-фильтра используются только более надежные даты:
- Tavily `published_date`;
- дата в URL;
- дата в заголовке;
- дата рядом с проектными действиями: строительство, проектирование, запуск, инвестиции и т.д.

Юридические ссылки, футеры, регистрационные даты, постановления и похожий шум игнорируются.

### 4. Защита от агрегаторов и смешанных проектов
`lead_gate.py` отправляет в verification pool:
- generic страницы «Инвестиционно-строительная активность»;
- обзоры/перечни проектов;
- записи, где квалификация смешала несколько проектов в одну сущность.

### 5. PostgreSQL enrichment schema
Без ручного SQL автоматически добавляются поля:
- `project_score`
- `sales_score`
- `sales_priority`
- `resolved_company_name`
- `legal_name`
- `inn`
- `ogrn`
- `website`
- `enrichment_status`
- `last_enriched_at`

И таблица:
- `lead_project_contacts`

Старые `lead_projects` и UUID сохраняются.

### 6. Web UI
После деплоя открывается:

`/projects/dashboard`

В интерфейсе есть:
- список проектов;
- Project Score / Sales Score;
- фильтры;
- company / ИНН;
- карточка проекта;
- источники;
- контакты;
- verification pool;
- кнопка «Запустить поиск»;
- статус Celery task;
- Excel export.

### 7. Production-like запуск из UI/API
Новые endpoints:
- `POST /projects/search-runs/start`
- `GET /projects/tasks/{task_id}`
- `GET /projects/search-runs/{run_id}`
- `GET /projects/dashboard`

Старый `POST /qualification/discovery-test` можно оставить – он не мешает.

## Какие файлы заменить/добавить

Заменить:
- `app/services/qualification.py`
- `app/services/lead_gate.py`
- `app/services/project_persistence.py`
- `app/tasks/qualification.py`
- `app/api/routes/projects.py`

Добавить:
- `app/services/company_enrichment.py`
- `app/services/sales_scoring.py`
- `app/services/temporal_quality.py`

Опционально добавить тест:
- `tests/test_product_v2.py`

## Что НЕ нужно менять

`app/main.py` менять не требуется, если там уже есть:

```python
from app.api.routes.projects import router as projects_router
app.include_router(projects_router)
```

Новые переменные окружения не нужны.
Используются уже существующие:
- `DATABASE_URL`
- `REDIS_URL`
- `TAVILY_API_KEY`
- `OPENAI_API_KEY`

## Деплой

1. Загрузить файлы из ZIP в репозиторий с сохранением путей.
2. Redeploy `zemlya-ai-agent`.
3. Redeploy `zemlya-worker`.
4. Открыть `/projects/dashboard`.
5. Нажать «Запустить поиск».

При первом обращении к persistence автоматически выполняются `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` и создание `lead_project_contacts`. Ручной SQL не нужен.

## Что проверять после запуска

Успешный Product V2 run должен вернуть:
- `pipeline_version = product-v2`
- блок `enrichment`
- блок `sales_scoring`
- `persistence.active_saved`

В `GET /projects` появятся:
- `project_score`
- `sales_score`
- `sales_priority`
- `company_name` – resolved name, если удалось надежно установить компанию
- `source_company_name` – исходное имя из qualification
- `inn`, `website`, `enrichment_status`

## Важная оговорка

Это публичный web enrichment через Tavily + OpenAI, а не реестровый enrichment через Saby/Kontur/DaData. Поэтому ИНН/ЛПР/контакты сохраняются только если они прямо обнаружены в публичных источниках. Следующий уровень точности – подключение специализированного B2B/ЕГРЮЛ API.
