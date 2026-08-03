# AI-классификация объектов CRM

## Базовое правило дат

В CRM у тендерных объектов используются четыре разные даты:

- `start_date` — начало торгов / подачи заявок.
- `end_date` — окончание торгов / подачи заявок.
- `delivery_start_date` — начало поставки / исполнения работ.
- `delivery_end_date` — окончание поставки / исполнения работ.

Коммерческий шанс поставки и приоритет активной продажи считаются по `delivery_end_date`, а не по `end_date`.

Если торги уже прошли, но `delivery_end_date` ещё далеко, объект не является мусором: следующий шаг — работа через победителя/подрядчика.

## Sales action

Модель должна возвращать:

- `direct_bid` — можно готовить прямое участие в торгах.
- `wait_contractor` — торги прошли/почти прошли, но срок исполнения позволяет зайти через победителя.
- `monitor_only` — срок исполнения слишком близко или данных недостаточно; объект не скрывается автоматически.
- `reject` — объект явно нерелевантен товарным направлениям.

## Окно активной продажи

Для поставки материалов активным считается объект, где до `delivery_end_date` не меньше 90 дней.

Если `delivery_end_date < today + 90 days`, объект не переводится в «неинтересные», но получает низкий шанс поставки и режим `monitor_only`.

## Объёмы и доля материалов

Если найденные материалы могут составлять 80% и более суммы закупки, это сильный сигнал прямого участия.

Если объёмы/доля материалов не найдены, модель не должна выдумывать:

- `volume_signal = "неизвестно"`
- `material_share_estimate = null`
- приоритет не должен автоматически улетать в 100.

## Иерархическая классификация

Объект имеет один основной класс и несколько тегов.

Минимальный JSON модели:

```json
{
  "segment": "social",
  "label": "Государственный / социальный",
  "primary_class": "социальные объекты",
  "subcategory": "образование",
  "object_type": "школа",
  "object_subtype": "",
  "social_status": "социальный",
  "work_type": "капитальный ремонт",
  "project_stage": "торги объявлены",
  "infrastructure_tags": ["фасад", "кровля"],
  "confidence": 90,
  "priority_score": 75,
  "delivery_chance": "средний",
  "volume_signal": "неизвестно",
  "material_share_estimate": null,
  "sales_action": "wait_contractor",
  "reason": "..."
}
```

## Хранение

Постоянное состояние хранится в CRM-БД в таблице `crm_object_ai_classifications`.

Поля:

- `primary_class`
- `subcategory`
- `object_type`
- `object_subtype`
- `social_status`
- `work_type`
- `project_stage`
- `infrastructure_tags`
- `priority_score`
- `delivery_chance`
- `volume_signal`
- `sales_action`
- `model_name`
- `model_version`
- `classification_confidence`
- `classification_reason`
- `manager_corrected`
- `manager_correction`

JSONL-файлы в `data/ai_shadow` остаются как журнал и резерв, но не должны быть единственным источником правды.
