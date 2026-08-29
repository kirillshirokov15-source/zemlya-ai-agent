# Zemlya AI – Quality Engine V4

Это шаг 1 из последних 5 до готового продукта.

## Что изменено
– Tavily Search теперь используется только для discovery.
– До AI-квалификации система забирает полный текст найденных страниц через Tavily Extract.
– Исходный search snippet сохраняется отдельно.
– Усилен детектор страниц с несколькими проектами и обзорных страниц.
– Лимит атомарного extraction увеличен с 12 до 20 источников.
– Если extraction не выполнен из-за лимита/ошибки, запись не попадает в active автоматически.
– Официальные источники mosreg/gov и крупные СМИ больше не отбрасываются только из-за несовпадения title/content.
– Если дата запуска/ввода уже прошла или относится к текущему году, проект уходит на дополнительную проверку актуального статуса.
– OpenAI-клиент в project_extraction создается лениво.

## Замена файлов
Заменить/добавить:
app/services/page_enrichment.py
app/services/project_extraction.py
app/services/candidate_ranking.py
app/services/temporal_quality.py
app/services/lead_gate.py
app/tasks/qualification.py
tests/test_quality_v4.py

## Railway
Новых переменных не требуется.
Используются существующие:
TAVILY_API_KEY
OPENAI_API_KEY
DATABASE_URL
REDIS_URL

После push:
1. Redeploy zemlya-ai-agent
2. Redeploy zemlya-worker
3. В панели нажать «Запустить поиск»

## Что прислать для проверки
После завершения поиска достаточно прислать список из панели или JSON результата запуска.
Проверяем не сам факт SUCCESS, а качество 10–20 верхних проектов.
