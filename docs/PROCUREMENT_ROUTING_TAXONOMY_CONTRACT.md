# Procurement Routing Taxonomy Contract (v1)

```text
WIP=PROCUREMENT-ROUTING-TAXONOMY-CONTRACT-V1
MODE=SPEC_ONLY   (no code change, no inference, no training, no doc reprocess)
STATUS=WAITING_USER_REVIEW
```

Цель: зафиксировать однозначную первичную бизнес-схему классификации закупки
**до** дальнейшего inference / fine-tuning. Документ — нормативный контракт осей.
Доказательство = running code + production DB (ссылки на файлы/колонки ниже).

---

## 0. Шесть осей и их текущее состояние

| Axis | Значения | Где живёт | Состояние |
|---|---|---|---|
| `PROCUREMENT_FORM` | 9 | `src/domain/commercial_routing_v3.py` → `ProcurementForm` | ЕСТЬ в коде. Канон. Не переопределять |
| `COMMERCIAL_TRACK` | 6 | `src/domain/commercial_routing_v3.py` → `OpportunityTrack` | ЕСТЬ в коде. Канон |
| `PROJECT_STAGE` | 7 | — | НЕТ canonical enum. **Коллизия имени** с `crm_object_ai_classifications.project_stage` (см. §3) |
| `SERVICE_TYPE` | 9 | — | НЕТ ни в коде, ни в БД. Новый axis |
| `WORK_STAGE` | 8 де-факто | `src/services/commercial_routing_v3/object_mode_routing.py:87` `classify_work_stage()` + `prompt_v6.py` | ЕСТЬ де-факто. Не менять молча (§5) |
| `OBJECT_TYPE` | — | `object_mode_routing.classify_object()` | Следующий WIP. В этом контракте не тестируется |

Дубликат-риск: файл `src/services/commercial_routing_v3/commercial_routing_v3.py` побайтово совпадает
с доменным модулем (236 строк) и **никем не импортируется** — мёртвая копия. Не трогать в этом WIP, но не
добавлять в неё новые оси.

---

## 1. `PROCUREMENT_FORM` — бизнес-смысл (канон, 9 значений)

```text
DIRECT_GOODS_PURCHASE      предмет = поставка товара
CONSTRUCTION_WORKS         строительство / реконструкция / капремонт / ремонт /
                           монтаж и устройство строительных и инженерных систем объекта
DESIGN_ONLY                проектирование / ПД / РД / ПСД без основных СМР в этом же контракте
SURVEY_AND_DESIGN          один контракт = изыскания + проектирование
DESIGN_AND_BUILD           один контракт = проектирование + реальные СМР
DESIGN_EXPERTISE_AND_BUILD один контракт = проектирование/экспертиза И реальные СМР
WORKS_OTHER                работы, которые НЕ являются строительными/ремонтными/монтажными
SERVICES_OTHER             услуги, не являющиеся поставкой, проектированием или СМР
UNKNOWN                    реально недостаточно данных
```

Инварианты (обязательные):

1. **Монтаж/пусконаладка как сопутствующая услуга НЕ превращает поставку в `CONSTRUCTION_WORKS`.**
   «Поставка и монтаж …», «Поставка и установка …» → `DIRECT_GOODS_PURCHASE`.
   Доказано на 5/5 кейсах bucket E (`wip_routing_contract30.tsv`): рубрика ставила
   `CONSTRUCTION_WORKS`, корректно — `DIRECT_GOODS_PURCHASE`.
2. **`WORKS_OTHER` — не fallback.** Запрещено использовать как «не разобрался».
   Если это СМР объекта — `CONSTRUCTION_WORKS`; если услуга — `SERVICES_OTHER`; если непонятно — `UNKNOWN`.
   Дефект baseline: `WORKS_OTHER` выдан как catch-all в 3/5 кейсах bucket F (240133, 250588, 298259) и в 2 кейсах
   bucket B (894, 6470).
3. **Слова «экспертиза / строительство / реконструкция / капремонт», описывающие БУДУЩИЙ объект,
   НЕ означают `DESIGN_AND_BUILD` / `DESIGN_EXPERTISE_AND_BUILD`.**
   Нужны признаки реальных СМР **в предмете этого контракта** («выполнение строительно-монтажных работ»,
   «выполнение работ по строительству»), а не в названии объекта.
   Контрольные кейсы: `34569`, `34575` (в названии «…на строительство блочно-модульной котельной…», но
   предмет = разработка ПСД + госэкспертиза → `DESIGN_ONLY`), `16481` (проектные работы + повторная
   экспертиза сметы → `DESIGN_ONLY`).

---

## 2. `COMMERCIAL_TRACK` — отдельная ось (канон `OpportunityTrack`)

```text
DIRECT_SUPPLY | EMBEDDED_MATERIAL | DESIGN_REQUIREMENT | DESIGN_INFLUENCE | NO_COMMERCIAL_ENTRY | UNKNOWN
```

Обязательное минимальное правило контракта:

```text
DIRECT_GOODS_PURCHASE  ->  DIRECT_SUPPLY        (детерминированно, не отдаётся на волю модели)
```

Существующий детерминированный мэппинг в коде (`TRACKS_FOR_FORM`):

| FORM | TRACKS |
|---|---|
| DIRECT_GOODS_PURCHASE | DIRECT_SUPPLY |
| CONSTRUCTION_WORKS | EMBEDDED_MATERIAL |
| DESIGN_ONLY / SURVEY_AND_DESIGN | DESIGN_REQUIREMENT, DESIGN_INFLUENCE |
| DESIGN_AND_BUILD / DESIGN_EXPERTISE_AND_BUILD | DESIGN_REQUIREMENT, EMBEDDED_MATERIAL, DESIGN_INFLUENCE |

**GAP (не закрывать в этом WIP):** `WORKS_OTHER`, `SERVICES_OTHER`, `UNKNOWN` отсутствуют в `TRACKS_FOR_FORM`.
До решения пользователя для этих форм `COMMERCIAL_TRACK = UNKNOWN` (не выводить DIRECT_SUPPLY).
Дефект baseline: модель выдала `DIRECT_SUPPLY` для услуг (894) и для работ (250588, 307871, 319721) — смешение осей.

Оси `PROCUREMENT_FORM` и `COMMERCIAL_TRACK` не сливать: одна закупка = форма + трек, а не одно поле.

---

## 3. `PROJECT_STAGE` — КОЛЛИЗИЯ ИМЕНИ (требует решения пользователя)

Предлагаемая ось (жизненный цикл объекта):

```text
SURVEY                  изыскания / геодезия / геология / первоначальное обследование до проекта
DESIGN                  разработка проектной документации
WORKING_DOCUMENTATION   разработка РД либо ПД + РД (отдельный коммерческий lifecycle-сигнал)
EXPERTISE               стадия экспертизы ПД / результатов изысканий
CONSTRUCTION            строительство / реконструкция / ремонт / капремонт / монтаж
OPERATION               эксплуатация / ТО существующего объекта
UNKNOWN                 стадия не определяется (для DIRECT-ветки = не применимо)
```

**Проблема, найденная в running code + DB (не документация):**

1. Колонка `crm_object_ai_classifications.project_stage TEXT` **уже существует**
   (`src/services/object_ai_classification_store.py`), и её смысл — **стадия торгов/закупки**, а не объекта:
   `src/services/object_ai_prompts.py:66` перечисляет значения
   `экспертиза | подготовка закупки | торги объявлены | прием заявок | подведение итогов | подрядчик определён |
   строительство | поставка | выполнение работ | завершён | неизвестно`.
2. Этот же пайплайн заполняет `project_stage` **из `work_stage`**:
   `src/services/crm_ai_assessment_runner.py:946` → `"project_stage": oc.get("work_stage") or "unknown"`,
   и `field_provenance.py` прямо комментирует `project_stage ... # maps work_stage`.
3. При этом в analytics-v2 модельный результат уже использует `project_stage` в смысле **жизненного цикла объекта**
   (baseline выдаёт `"project_stage":"SURVEY"/"DESIGN"/...`), и UI читает его как «Стадия»:
   `src/ui/components/analytics_v2/annotation_card.py:542` → `nr.get('project_stage') or nr.get('work_stage')`.

Итог: **имя `project_stage` уже имеет два несовместимых смысла в одном продукте.**
Создавать третье поле с тем же именем и новым смыслом — прямое нарушение принципа
«не создавать несовместимый второй enum».

**Требуемое решение пользователя (одно из двух):**

- (A) оставить бизнес-имя `PROJECT_STAGE`, но код-идентификатор сделать отличным
  (напр. `OBJECT_STAGE` / `OBJECT_LIFECYCLE_STAGE`) и переименовать существующий тендерный `project_stage`
  в `TENDER_STAGE`; либо
- (B) не вводить ось жизненного цикла вообще и ограничиться существующим `work_stage`.

До решения — ось считается `NOT_READY` и в код/БД **не добавляется**.

---

## 4. `SERVICE_TYPE` — новый axis (в коде и БД отсутствует)

```text
CONSTRUCTION_CONTROL    строительный контроль / технический надзор за работами
AUTHOR_SUPERVISION      авторский надзор проектировщика
TECHNICAL_SURVEY        техническое обследование здания/сооружения/конструкций
ENGINEERING_SURVEY      инженерно-геодезические / геологические / топографические изыскания
LAB_TESTING             лабораторные испытания / исследования
MAINTENANCE_SERVICE     эксплуатация, ТО, сервисное обслуживание
OTHER_SERVICE           другая определённая услуга
NONE                    закупка не является услугой
UNKNOWN                 услуга есть, но тип не определён
```

Проверено grep по `src/`: подстроки `service_type` / `SERVICE_TYPE` / `ServiceType` **не встречаются**.
Проверено по БД `information_schema.columns`: колонки с `service_type` нет ни в одной таблице `public`.
→ ось реально новая, конфликта имён нет.

Применение: только для `SERVICES_OTHER` (для остальных форм = `NONE`).
Дефект baseline: 248886 (ТО канализации/ХВС/отопления) — модель вернула `service_type=OTHER_SERVICE`
вместо `MAINTENANCE_SERVICE` и `procurement_form=UNKNOWN` вместо `SERVICES_OTHER`.

---

## 5. `WORK_STAGE` — сохранить как отдельную характеристику (не трогать молча)

Де-факто реализация: `classify_work_stage(*, title, form)` (`src/services/commercial_routing_v3/object_mode_routing.py:87`).
Возвращает: `SURVEY_AND_DESIGN | DESIGN | CAPITAL_REPAIR | REPAIR | NEW_CONSTRUCTION | RECONSTRUCTION | UNKNOWN`.
Дополнительно `prompt_v6.py` эмитит `work_stage = "SUPPLY"` для прямых поставок → фактический набор из 8 значений
(в исходном WIP-списке `SUPPLY` отсутствовал — это gap).

Разделение осей (обязательное):

```text
PROJECT_STAGE = где объект по жизненному циклу
WORK_STAGE    = какой вид работ/изменения объекта выполняется
```

Примеры (подтверждаются на реальных строках):
`PROJECT_STAGE=CONSTRUCTION + WORK_STAGE=CAPITAL_REPAIR` (8938);
`PROJECT_STAGE=CONSTRUCTION + WORK_STAGE=REPAIR` (6470, 298259, 319721);
`PROJECT_STAGE=CONSTRUCTION + WORK_STAGE=DESIGN` (307871, 7990).

Известные слабости функции (не чинить здесь, только зафиксировать):
- чисто keyword-driven по title → ложные срабатывания: `7990` (contract = DESIGN_EXPERTISE_AND_BUILD + СМР)
  получает `SURVEY_AND_DESIGN`, потому что в названии есть «изысканий»;
- для прямых поставок возвращает `UNKNOWN`, тогда как промпт эмитит `SUPPLY` → рассинхрон названий;
- функция не видит формы, если `form` передан пустым.

---

## 6. Цепочка первичной маршрутизации

```text
SOURCE (факт из БД)
   |
PROCUREMENT_FORM
   |
COMMERCIAL_TRACK
   |
PROJECT_STAGE
   |
SERVICE_TYPE
   |
OBJECT_TYPE            (следующий WIP)
```

Ветки:

```text
DIRECT:      DIRECT_GOODS_PURCHASE -> DIRECT_SUPPLY -> OBJECT не обязателен
             -> товарная категория / evidence / medal

SERVICES:    SERVICES_OTHER -> SERVICE_TYPE -> PROJECT_STAGE (если определяется)
             -> OBJECT = context, не основной товарный поток

OBJECT MODE: DESIGN_ONLY | SURVEY_AND_DESIGN | DESIGN_AND_BUILD |
             DESIGN_EXPERTISE_AND_BUILD | CONSTRUCTION_WORKS
             -> OBJECT_TYPE обязателен -> commercial opportunities
```

Правила назначения `PROJECT_STAGE` (детерминированные, из формы + scope):

```text
DIRECT_GOODS_PURCHASE                 -> UNKNOWN (не применимо)
CONSTRUCTION_WORKS                    -> CONSTRUCTION
DESIGN_AND_BUILD                      -> CONSTRUCTION
DESIGN_EXPERTISE_AND_BUILD            -> CONSTRUCTION
DESIGN_ONLY   + только ПД               -> DESIGN
DESIGN_ONLY   + ПД + РД                 -> WORKING_DOCUMENTATION
DESIGN_ONLY   + ПД + экспертиза         -> EXPERTISE
SURVEY_AND_DESIGN                     -> DESIGN
SERVICES_OTHER + изыскания/обследование -> SURVEY
SERVICES_OTHER + стройконтроль/надзор   -> CONSTRUCTION
SERVICES_OTHER + ТО/эксплуатация        -> OPERATION
```

---

## 7. CONTESTED / GAP — решения пользователя

| # | Пункт | Тип | Требуется |
|---|---|---|---|
| 1 | `PROJECT_STAGE` vs существующий `project_stage` (=такт-стадия, кормится из `work_stage`) | КОЛЛИЗИЯ ИМЁН | выбрать вариант (A) или (B) из §3 |
| 2 | `WORKS_OTHER` / `SERVICES_OTHER` / `UNKNOWN` отсутствуют в `TRACKS_FOR_FORM` | GAP | подтвердить правило (`UNKNOWN` до явного решения) |
| 3 | `work_stage`: в де-факто наборе есть `SUPPLY`, которого нет в списке WIP | GAP | подтвердить добавление `SUPPLY` |
| 4 | `classify_work_stage()` keyword-based: `7990` → `SURVEY_AND_DESIGN` при фактических СМР | ДЕФЕКТ (не правится здесь) | подтвердить, что чинится в следующем WIP |
| 5 | Модель возвращает JSON то в нижнем, то в ВЕРХНЕМ регистре ключей (`procurement_form` vs `PROCUREMENT_FORM`) | ДЕФЕКТ нормализации | подтвердить нормализацию ключей в harness |
| 6 | `DIRECT_GOODS_PURCHASE` → `work_stage=UNKNOWN` у функции, но `SUPPLY` у промпта | рассинхрон | подтвердить единое значение |

---

## 8. Верификация: 30 реальных закупок (без нового inference)

Источник: `/home/sergey/crm-training/stagebase/parsed.jsonl` (148 строк baseline-прогона V2,
модель `qwen2.5:7b`, read-only). Новая разметка осей автором контракта; колонка `WORK_STAGE`
посчитана **реальной** функцией `classify_work_stage(title, contract_form)`.
Артефакт: `wip_routing_contract30.tsv` (30 кейсов + 1 дополнительный OPERATION-кейс).

Состав: 5 DIRECT_GOODS / 5 SERVICES_OTHER / 5 DESIGN_ONLY+SURVEY_AND_DESIGN /
5 DESIGN_AND_BUILD+DESIGN_EXPERTISE_AND_BUILD / 5 CONSTRUCTION_WORKS / 5 сложных.

**Вывод: все 30 строк выражаются схемой без противоречий. `UNREPRESENTABLE_CASES = 0`.**

Побочный результат (важный): контракт вскрыл **9 случаев из 30, где рубрика baseline сама нарушает правила §1** —
5 «поставка+монтаж/установка» (bucket E: 22973, 38097, 51571, 80066, 96330) и 4 «будущий объект»
(7990, 16481, 34569, 34575). То есть часть «ошибок модели» из прошлых WIP — на самом деле ошибки рубрики, а модель
была права. Это надо учесть до fine-tuning (иначе обучаем на шумной метке).

Дополнительно проверено `OPERATION`: 248886 (ТО инженерных систем) — существующий набор значений
модель выразить не смогла (`form=UNKNOWN`, `service_type=OTHER_SERVICE`, `stage=None`), новая ось
выражает однозначно → `SERVICES_OTHER + MAINTENANCE_SERVICE + OPERATION`.

---

## 9. Итог контракта

```text
PROCUREMENT_FORM_CONTRACT=READY
PROJECT_STAGE_TAXONOMY=NOT_READY            (коллизия имён, §3, §7.1)
SERVICE_TYPE_TAXONOMY=READY                 (зафиксирована здесь; в коде/БД ещё нет)
WORK_STAGE_KEPT_SEPARATE=YES
DIRECT_SUPPLY_SEPARATE=YES
REAL_CASES=30
UNREPRESENTABLE_CASES=0
```

Ничего в production не менялось. Code-реализация новых осей — следующий WIP, после решения §7.1.
