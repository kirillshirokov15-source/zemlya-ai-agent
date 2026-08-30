# Zemlya AI – Sales Score V8

Финальная модель Sales Score.

## Что исправлено

Удалён искусственный hard cap `79` для всех лидов без прямого контакта ЛПР.

Теперь Sales Score отвечает на вопрос:
**насколько это сильная коммерческая возможность для услуг «Земля без торгов»?**

А статус `A_ready / B_high / C_verify / D_low` отдельно показывает,
насколько лид готов к непосредственному контакту.

## Формула

- Project quality – 0–35
- Land/service fit – 0–25
- Company identity – 0–15
- Contactability – 0–25

Итого – 100.

### Contactability

- конкретный ЛПР + его прямой phone/email – 25
- ЛПР известен + есть общий корпоративный канал – 15
- только общий корпоративный канал – 10
- ЛПР известен, но каналов нет – 6
- контактов нет – 0

### Land/service fit

- confirmed_needed – 25
- high_probability – 20
- unknown – 10
- land_defined – 3
- stage V – автоматически land_defined и 3 балла
- stage G – 0

## Жёсткие business gates

Они сохраняются только там, где проект действительно поздний или слабый:

- paused – Sales <= 29
- stage G – Sales <= 39
- modernization existing site – Sales <= 35

Нет hard cap 79.

## Статусы

- A_ready – score >= 90 И есть прямой контакт конкретного ЛПР
- B_high – score >= 70
- C_verify – score >= 50
- D_low – score < 50

У B_high может не быть прямого ЛПР. Тогда действие – `find_decision_maker`.

## Установка

Заменить три файла:

- app/services/sales_scoring.py
- app/services/final_verification.py
- app/services/project_rescore.py

Redeploy:

1. `zemlya-ai-agent`
2. `zemlya-worker`

После деплоя НЕ запускать новый Tavily search.

В Swagger выполнить:

POST /projects/rescore-current

Endpoint пересчитает текущую активную базу только по PostgreSQL и уже найденным контактам.

После этого обновить `/projects/dashboard`.
