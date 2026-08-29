# Quality Gate V4.1
Финальная часть шага 1 из 5.

Добавить/заменить:
– app/services/final_quality_gate.py
– app/services/sales_scoring.py
– app/tasks/qualification.py

Исправляет:
– дубли после определения компании – по ИНН + компании + проекту;
– разные проекты одной компании не объединяются автоматически;
– модернизация существующей площадки получает сильный штраф;
– уже определённая земля снижает Sales Score;
– Sales Score 100 теперь требует прямого контакта ЛПР и полной готовности лида.

После push: Redeploy zemlya-ai-agent и zemlya-worker.
Новых Railway variables не требуется.
