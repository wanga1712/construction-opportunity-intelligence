# Construction Opportunity Intelligence
## Аналитический коммерческий контур закупок и строительных объектов

Система собирает закупки и строительные объекты, определяет их коммерческую
релевантность, исследует документацию, выделяет товарные и проектные категории,
формирует доказательные коммерческие возможности и выдаёт их в CRM, карточку
объекта, аналитический контур, kiosk и commercial portal/API.

`CRM Streamlit` и `Tender Documents Research` — компоненты системы, а не
описание всего продукта.

## Главный pipeline

```text
ИСТОЧНИКИ
44-ФЗ / 223-ФЗ / другие контуры
        │
        ▼
SOURCE + LIFECYCLE
OPEN / AWARDED / COMPLETED ...
        │
        ▼
PROCUREMENT SCOPE
DIRECT_GOODS / WORKS_WITH_EMBEDDED_PRODUCTS / DESIGN_PROJECT
        │
        ▼
BUSINESS_RESEARCH_ADMISSION_V2
ELIGIBLE / HOLD / EXCLUDED
        │
        ▼
ROUTING
ACTIVE_OPEN / AWARDED_ADMITTED / REVIEW_DISCOVERY
        │
        ▼
DOCUMENT RESEARCH
скачивание → архивы → parsing → OCR → extraction
        │
        ▼
STRUCTURED FACTS
товары / материалы / оборудование / параметры / объёмы
        │
        ▼
CATEGORY OPPORTUNITIES
1 закупка → N коммерческих категорий
        │
        ├── candidate_initial
        ├── confirmed_base
        └── current_effective
        │
        ▼
COMMERCIAL READ MODEL
объект / категория / медаль / доказательства / стоимость / объёмы
        │
        ├── CRM
        ├── карточка объекта
        ├── аналитический контур
        ├── kiosk
        └── commercial portal/API
```

Короткая mental model: закупка или объект → допуск к исследованию → порядок
исследования → факты из документов → коммерческие категории → текущая сила
каждой возможности.

## Что является коммерческой единицей

```text
PROCUREMENT != COMMERCIAL OPPORTUNITY
```

Закупка — контейнер исходных данных. Коммерческое решение принимается по
категории внутри неё. Одна закупка может содержать несколько независимых
возможностей с разными медалями и доказательствами.

```text
Закупка: строительство школы

├── flooring                SILVER
├── lighting                GOLD
├── waterproofing           BRONZE
└── cable_support_systems   SILVER
```

Canonical unit коммерческого решения:

```text
crm_procurement_category_opportunities
```

Закупку нельзя схлопывать до одной максимальной медали. Max-medal не должен
скрывать независимые категории.

## Business admission

Canonical policy:

```text
BUSINESS_RESEARCH_ADMISSION_V2
```

```text
source lifecycle
+
procurement scope
        ↓
ELIGIBLE / HOLD / EXCLUDED
```

```text
OPEN + DIRECT_GOODS                    → ELIGIBLE
OPEN + WORKS_WITH_EMBEDDED_PRODUCTS    → ELIGIBLE
OPEN + DESIGN_PROJECT                  → ELIGIBLE

AWARDED + WORKS_WITH_EMBEDDED_PRODUCTS → ELIGIBLE
AWARDED + DESIGN_PROJECT               → ELIGIBLE
AWARDED + DIRECT_GOODS                 → EXCLUDED
```

Неизвестные или неоднозначные комбинации закрываются в `HOLD`.

```text
admission != research priority
admission != commercial medal
admission != document confirmation
```

Модель не определяет business admission. Решение materialize-ится в
`crm_procurement_scope_authority` и далее проверяется по сохранённой policy.

## Три уровня коммерческой оценки

```text
CANDIDATE
   ↓
DOCUMENT RESEARCH
   ↓
CONFIRMED BASE
   ↓
CURRENT EFFECTIVE
```

| Слой | Смысл |
| :--- | :--- |
| `candidate_initial` | предварительная оценка после первого анализа |
| `confirmed_base` | оценка только по документированным trusted facts |
| `current_effective` | действующая оценка с учётом подтверждения и времени |

```text
candidate_initial нельзя подменять confirmed_base
confirmed_base NULL означает "не подтверждено"
missing value = NULL, не 0
```

`candidate_initial` фиксирует исходную гипотезу и не перезаписывается
подтверждением. `confirmed_base` появляется только после документального
подтверждения. `current_effective` используется для текущего ранжирования.

## Документальный контур

```text
document link
→ materialization
→ download
→ archive traversal
→ parser
→ OCR fallback
→ structured extraction
→ category assignment
→ trust state
→ confirmed facts
```

Основные классы данных:

```text
structured_entities
structured_attributes
confirmed_category_facts
document_match_details
```

| Слой | Назначение |
| :--- | :--- |
| `document_match_details` | найденный контекст и provenance документа |
| `structured_entities` | нормализованный товар, материал или оборудование |
| `structured_attributes` | параметры, характеристики и измерения |
| `confirmed_category_facts` | подтверждённые категорийные факты и значения |

Trust states, которые нельзя смешивать:

```text
TRUSTED_PRODUCTION
MANUAL_PROOF_QUARANTINE
DEV_EXPOSED
QUALITY_REJECTED
```

Только trusted facts участвуют в подтверждённой коммерческой базе. Quarantine
и development artifacts остаются диагностическим материалом.

## Commercial truth / live market

Live commercial market строится на `crm_procurement_scope_authority`:

```text
admission_state = ELIGIBLE
source_lifecycle IN (OPEN, AWARDED)
актуальная admission policy
```

Коммерческие данные берутся из:

```text
crm_procurement_category_opportunities
WHERE status = CURRENT
```

```text
OPEN                         → текущая закупочная возможность
AWARDED project / embedded   → AWARDED_FOLLOWUP
AWARDED DIRECT goods         → закрыто, не live follow-up
```

Проектный НМЦК нельзя использовать как стоимость каждой категории. Числовые
показатели рынка меняются и читаются из audit/read-model, а не хардкодятся в
README.

## Research priority

Research priority отвечает только на вопрос: **что исследовать раньше?**

```text
Research Priority: "что исследовать раньше?"
Business Admission: "имеет ли объект право войти в исследовательский контур?"
Commercial Medal: "насколько интересна конкретная товарная категория?"
```

| Механизм | Вопрос |
| :--- | :--- |
| Admission | Обрабатываем объект вообще? |
| Research priority | В каком порядке? |
| Category opportunity | Что именно можно продать? |
| Commercial medal | Насколько сильна возможность? |
| Confirmed base | Что подтверждено документами? |

Routing lanes: `ACTIVE_OPEN`, `AWARDED_ADMITTED`, `REVIEW_DISCOVERY`.
`REVIEW_DISCOVERY` не входит в обычную 70/30 capacity и используется как
дополнительный источник после primary ready work.

История `OKPD_HIERARCHICAL_PRIOR_V1`, CatBoost, `TITLE_TEXT_BASELINE_V2`,
`TITLE_SEMANTIC_V2`, `research_priority_v2`, формулы и historical benchmark:
[docs/MODEL_TRAINING_AND_PRIORITY.md](docs/MODEL_TRAINING_AND_PRIORITY.md).

## Source-of-truth map

| Смысл | Authority |
| :--- | :--- |
| Lifecycle | source lifecycle authority |
| Scope/admission | `crm_procurement_scope_authority` |
| Category opportunity | `crm_procurement_category_opportunities` |
| Document queue | `document_processing_queue` |
| Extracted entities | `structured_entities` |
| Confirmation | trusted/confirmed facts |
| Commercial read model | existing CRM projections/read services |
| Hosts/access | `docs/PROJECT_OPERATING_RULES.md` |

README не дублирует hosts, identities, SSH routes, DB roles или credentials.
Для infrastructure operations используется
[docs/PROJECT_OPERATING_RULES.md](docs/PROJECT_OPERATING_RULES.md).

## Пользовательские поверхности

### CRM / таблица объектов

Поиск, просмотр и приоритизация закупок и связанных строительных объектов.

### Procurement Card

Основные вкладки:

```text
Обзор / Документы / Категории / Смета
Техпараметры / Требования / История / Модель / Очередь
```

«Находки» не являются основной пользовательской сущностью. Главная единица
карточки — **Категория** с текущей медалью, подтверждением, доказательствами,
объёмами и стоимостью.

### Commercial Portal

Read-only коммерческий слой:

```text
src/services/commercial_portal_service.py
src/services/commercial_portal_facts.py
src/api/commercial_portal_api.py
```

Portal использует существующие category opportunities и не вводит вторую
логику медалей. Missing value возвращается как `null`.

### S13 Kiosk

Физический operational command center: pipeline, commercial result, queue,
model/document throughput, CPU/GPU/RAM/disk.

## AI Card Workspace

AI Card Workspace — развиваемый интерфейс работы модели в контексте конкретного
объекта. Источники контекста: CRM, documents, structured facts, evidence и
history. На первом этапе интерфейс read-only и не управляет admission,
очередью, статусами CRM или подтверждённой разметкой.

Архитектура:
[docs/AI_CARD_WORKSPACE_ARCHITECTURE.md](docs/AI_CARD_WORKSPACE_ARCHITECTURE.md).

## Текущее состояние

На canonical code уже существуют:

```text
✓ lifecycle authority
✓ procurement scope
✓ BUSINESS_RESEARCH_ADMISSION_V2
✓ routing lanes
✓ document pipeline
✓ OCR / parsers / archive traversal
✓ structured entities / attributes
✓ category opportunities
✓ candidate_initial medals
✓ confirmed_base
✓ current_effective
✓ procurement category cards
✓ commercial portal read model/API
✓ S13 operational kiosk
```

Развиваются:

```text
→ production reconciliation admission V2
→ queue admission convergence
→ queue band claim policy
→ wider confirmed-fact coverage
→ dynamic category discovery
→ commercial portal production integration
→ kiosk canonical reconciliation
→ systemd source reconciliation
→ 24h SLA
```

Статус проверяется по canonical code и актуальным WIP-документам, а не по
старым roadmap-записям.

## Critical invariants

```text
ONE PROCUREMENT → MANY CATEGORY OPPORTUNITIES
MODEL_CONTROLS_ADMISSION = NO
RESEARCH_PRIORITY != COMMERCIAL_MEDAL
CONTEXT_PRIOR != DOCUMENT_CONFIRMATION
CANDIDATE_INITIAL != CONFIRMED_BASE
WORKS / PROJECT NMCK != CATEGORY VALUE
MISSING FACT = NULL
AWARDED DIRECT GOODS = CLOSED / EXCLUDED FROM LIVE MARKET
AWARDED PROJECT / EMBEDDED = FOLLOW-UP
TRUSTED_PRODUCTION != QUARANTINE
```

Полный НМЦК закупки нельзя дублировать как стоимость всех её категорий.

## Структура репозитория

```text
src/
  services/commercial_routing_v3/   commercial decision/routing
  services/                         CRM read models/domain services
  ui/                               CRM UI
  api/                              external read APIs

tender_documents_research/          acquisition/parsing/extraction
scripts/                            audits/materializers/reconciliation
deploy/                             S13/kiosk/systemd sources
docs/                               architecture/WIP/contracts/rules
tests/                              contracts/regressions/integration
```

Основные точки входа commercial contour:

```text
src/services/commercial_routing_v3/business_research_admission.py
src/services/commercial_routing_v3/routing_eligibility.py
src/services/commercial_routing_v3/routing_backlog.py
src/services/commercial_routing_v3/routing_ready.py
src/services/commercial_routing_v3/projection_writer.py
src/services/procurement_card_category_service.py
src/services/commercial_portal_service.py
```

## Quick start

```text
Python >= 3.13,<3.14
```

```powershell
python -m pip install -r requirements.txt
python -m pytest
streamlit run app.py
```

Production hosts, identities, routes, DB roles и deployment access в README не
описываются. Их authority —
[docs/PROJECT_OPERATING_RULES.md](docs/PROJECT_OPERATING_RULES.md).

## Документация — что читать дальше

1. [README.md](README.md) — что представляет собой система.

2. [docs/PROJECT_OVERVIEW_AND_AUDIT.md](docs/PROJECT_OVERVIEW_AND_AUDIT.md) —
   подробная карта модулей.

3. [docs/PROJECT_OPERATING_RULES.md](docs/PROJECT_OPERATING_RULES.md) — hosts,
   identities, DB и operational authority.

4. [docs/CRM_V3_LAUNCH_ROADMAP.md](docs/CRM_V3_LAUNCH_ROADMAP.md) — этапы
   развития.

5. [docs/wip/](docs/wip/) — выполняемые изменения.

6. [docs/MODEL_TRAINING_AND_PRIORITY.md](docs/MODEL_TRAINING_AND_PRIORITY.md) —
   research-priority/model subsystem.

7. [docs/COMMERCIAL_PORTAL_API_CONTRACT.md](docs/COMMERCIAL_PORTAL_API_CONTRACT.md) —
   commercial external API.

AI Card Workspace:
[docs/AI_CARD_WORKSPACE_ARCHITECTURE.md](docs/AI_CARD_WORKSPACE_ARCHITECTURE.md).
