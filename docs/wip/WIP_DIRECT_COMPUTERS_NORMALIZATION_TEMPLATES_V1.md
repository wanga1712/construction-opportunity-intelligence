# WIP DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1

Created: 2026-10-13. Owner: CRM procurement card / DIRECT normalizer + templater.

## Problem

Для режима «Прямая поставка товара» (`DIRECT_GOODS` / `DIRECT_SUPPLY`) по категории
`computers`, подкатегория `servers`, текущий вывод карточки нечитаемый: вместо
состава сервера пользователь получает плоский список техпараметров, а
нормализованная сущность выглядит как артикул.

Контрольная закупка:

- CRM ID 449936 · № 32616434043
- `auction_name`: «Поставка сервера с целью расширения технических мощностей программно-аппаратного комплекса управления основными данными Заказчика»
- ОКПД2: `26.20.14.120`
- scope authority: `procurement_scope_type=DIRECT_GOODS`, confidence 0.9
- opportunity: `computers / servers`, `DIRECT_SUPPLY`, CURRENT, medal BRONZE,
  priority 90, action `PRIORITY_DOCS`

Наблюдаемые дефекты (read-only, live DB):

1. `structured_entities` для 449936:
   - `product_name_raw = UR-LE-SRV-1`
   - `product_name_normalized = UR-LE-SRV-1`
   - `brand_normalized`, `manufacturer_normalized`, `model_article_normalized` пустые
   - `structured_attributes = []`
   - `product_relation = EMBEDDED`, хотя закупка DIRECT_GOODS
   - `source_quote` содержит полный состав: «Сервер | URSA | UR-LE-SRV-1 |
     сервер для высокопроизводительных вычислений и AI/ML … тип: стоечный …
     2 сокета … GPU-ускорители … AMD EPYC 9554 … 64 ядра …»
   То есть человекочитаемое имя и характеристики есть в цитате, но не
   материализованы в нормализованные поля.

   Причина/адрес правок:
   - общий writer `tender_documents_research/document_processor/embedded_persistence.py:145`
     жёстко пишет литерал `'EMBEDDED'` для всех фактов, включая
     `direct_runtime.direct_facts → persist_facts`; в домене значением
     является `PRIMARY_SUBJECT` / `EMBEDDED_IN_WORKS`, а `'EMBEDDED'` — не enum;
   - `brand_normalized` / `manufacturer_normalized` / `model_article_normalized`
     заполняет семантический нормализатор
     `tender_documents_research/document_processor/structured_fact_repository.py:125`,
     а не DIRECT-экстрактор; серверное правило должно жить именно там.
2. Прямой вывод вкладки «Товар и поставка» строится из
   `direct_document_extractor` → `direct_requirement_classifier` →
   `render_product_delivery`. Без явной колонки товара записи `tech`
   группируются только по маркерным `PRODUCT_GROUPS`, поэтому сервер
   распадается на строки «Параметр / Значение / Ед. изм. / Источник», а не
   на позиции и их конфигурации.
3. «Коммерческий слой» нечитаем: рядом с текущей возможностью
   `computers/servers/DIRECT_SUPPLY` в находках лежат legacy-категории по
   чужому профилю. Для 449936 `document_match_details`: lighting 62,
   waterproofing 33, flooring 9, composite_structures 5, cable_support_systems 1;
   computers = 0. В UI эти сырые коды выглядят как отдельный коммерческий
   сигнал, хотя авторитетная возможность уже определена.

## Identity / authority

- Режим закупки берём только из подтверждённого источника:
  `crm_procurement_scope_authority.procurement_scope_type = DIRECT_GOODS`
  и/или `crm_procurement_category_opportunities.opportunity_track = DIRECT_SUPPLY`.
  Название закупки и ОКПД2 не являются authority.
- Категория/подкатегория — из CURRENT-строки
  `crm_procurement_category_opportunities`.
- Фазовая трасса 0–4 фиксируется в `docs/REFACTORING_PLAN.md` до старта
  Phase 1; без записи в план (или явной пометки об отклонении) фазы с
  правками общего нормализатора/UI не начинаем.
- Нормализованный товар — из `structured_entities` + `structured_attributes`
  (document_intelligence), когда они есть; сырой разбор документа — вторичный
  источник для цитаты и fallback. Провенанс и trust state не подменяем.
- Скoring, медали, очередь и исторические записи не меняем.

## Task

Работаем строго последовательно; следующая фаза начинается только после
приёмки предыдущей.

### Phase 0 — read-only audit (target: computers/servers, DIRECT)

Для контрольной 449936 и выборки N до 15 текущих
`computers/servers/DIRECT_SUPPLY` зафиксировать:

- mode source, scope/track/form;
- `load_direct_extraction`: `spec/tech/requirements/sections/terms`,
  количество строк, наличие `item`, распределение `product_group`;
- `build_estimate`: позиции, цены, provenance;
- `structured_entities`: `product_name_raw/normalized`, brand, manufacturer,
  model/article, `product_relation`, trust, `structured_attributes`;
- точный хранимый литерал `product_relation`, writer
  (`embedded_persistence.py`) и семантический нормализатор
  (`structured_fact_repository.py`);
- `document_match_details`: категории и `provenance_status` против CURRENT
  opportunity;
- доступность parse cache и какие документы дали TZ (docx/pdf).

Приёмка Phase 0:

```
TARGET_CATEGORY=computers
TARGET_SUBCATEGORY=servers
DIRECT_MODE_SOURCE=scope_authority
TECH_ROWS_WITH_ITEM=X
TECH_ROWS_WITH_GROUP=Y
ENTITIES_WITH_HUMAN_NAME=0/1
ENTITIES_WITH_ATTRIBUTES=0
RELATION_EMBEDDED_IN_DIRECT=YES/NO
RELATION_WRITER=embedded_persistence.py
RELATION_LITERAL=EMBEDDED
DOMAIN_RELATION_ENUM=PRIMARY_SUBJECT/EMBEDDED_IN_WORKS
SEMANTIC_IDENTITY_WRITER=structured_fact_repository.py
MISMATCH_MATCH_CATEGORIES=...
INPUT_ROWS=OUTPUT_ROWS
```

### Phase 1 — deterministic product normalization for servers

- Из `source_quote`/raw tech строк строить человекочитаемое имя:
  `тип | производитель/бренд | модель/артикул` → например
  `Сервер URSA UR-LE-SRV-1`.
- Заполнять `brand_normalized` / `manufacturer_normalized` /
  `model_article_normalized` в `structured_fact_repository.py` (семантический
  нормализатор), не в direct-экстракторе, и не выбрасывать сырые поля.
- Править общий персист: `embedded_persistence.py` должен принимать relation
  от вызывающего пути и писать для DIRECT_GOODS `PRIMARY_SUBJECT`, а для
  EMBEDDED-контура `EMBEDDED_IN_WORKS` (дефолт для EMBEDDED). Литерал
  `'EMBEDDED'` для прямой закупки считать дефектом нормализации.
- Из `source_quote`/`tech` извлекать серверные характеристики в
  `structured_attributes` по детерминированным группам:
  form factor, sockets/CPU, cores/frequency, GPU, RAM, storage/RAID,
  network, power/cooling, management, warranty. Модель (qwen) использовать
  только как добор там, где детерминированного правила нет.
- Сохранять `source_quote`, `extractor_version`, `structured_fact_trust_state`;
  ничего не писать в скоринг/медали/очередь.

### Phase 2 — readable «Товар и поставка»

Не переписывать вкладку с нуля: `render_product_delivery` уже умеет
раскладывать записи по колонке `item`. Плоская таблица на 449936 получается
потому, что `item` пуст. Поэтому сначала:

0. для DIRECT детерминированно восстановить колонку товара в `tech`-записях
   (`item`), используя шаблоны T2/T6/T7 после подтверждения сметой/структурой;
   непривязанное показывать как «остаток».

Затем отобразить существующим механизмом позиций:

1. «Позиции и состав» — карточки/таблицы позиций: человекочитаемое имя,
   бренд/модель, количество, цена, характеристики по группам с цитатой.
2. «Условия поставки» — отдельно, как сейчас.
3. «Ненормализованный остаток» — сырые строки, которые не удалось привязать;
   потерь `input = output` не допускаем.

При отсутствии явной колонки товара использовать T6/T7-гипотезы только после
подтверждения сметой/структурой; сомнительное не привязываем, показываем как
остаток.

### Phase 3 — понятный коммерческий слой

- Отдельный блок «Коммерческая оценка» с человекочитаемыми значениями:
  Категория `Компьютеры / Серверы`, Режим `Прямая поставка`, медаль `BRONZE`,
  priority `90/100`, action `Приоритетные документы`.
- Переиспользовать существующий DIRECT-guard
  `src/services/commercial_routing_v3/direct_product_evidence.py:116`; не
  создавать параллельный коммерческий блок/ветку.
- Сырые enum-коды не показывать как primary UI; provenance/trust — подпиской.
- Находки из `document_match_details` выводить как evidence, а не как
  конкурирующие коммерческие гипотезы; при расхождении с CURRENT opportunity
  помечать их как «не подтверждено / legacy», не смешивать слои.

### Phase 4 — аналоги / сопоставимые позиции (опционально)

«Взять аналоги» делать только из существующих данных, не выдумывая каталог:
искать TRUSTED `structured_entities` той же подкатегории `servers` по
совпадению нормализованного типа/бренда/модели или близкому набору атрибутов.
Если источника нет — честно показывать «аналогов пока нет», а не генерировать
список моделью без подтверждения. Фаза запускается только после Phase 2.

## Acceptance

Контроль 449936:

```
PRODUCT_NAME_READABLE=YES        (не голый артикул)
BRAND_OR_MANUFACTURER_PRESENT=YES
MODEL_ARTICLE_PRESENT=YES
DIRECT_PRODUCT_RELATION=PRIMARY_SUBJECT
SERVER_ATTRIBUTES_PRESENT>=1
SOURCE_QUOTE_PRESERVED=YES
TECH_INPUT_ROWS=TECH_OUTPUT_OR_RAW_ROWS
COMMERCIAL_LAYER_HUMAN_READABLE=YES
COMPUTERS_OPPORTUNITY_NOT_MIXED_WITH_LEGACY_MATCHES=YES
```

Генерализация: N=15 current `computers/servers/DIRECT_SUPPLY` без падения
карточки, без изменения скоринга/медалей, `DB_WRITES=0` (кроме явно
согласованного Phase 1 reparse/persist).

## Out of scope

- Другие категории DIRECT и весь EMBEDDED-контур.
- Скоринг, медали, пороги, lifecycle, timing, очередь.
- Массовый reparse/backfill без отдельного явного запроса.
- Создание внешнего каталога аналогов.

## RESULT
