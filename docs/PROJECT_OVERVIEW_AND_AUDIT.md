# CRM Streamlit: устройство проекта и аудит согласованности

Дата снимка: **2026-10-25**. Этот документ описывает фактическую структуру
текущего рабочего дерева. Проект активно меняется; незавершённые инициативы и
их статусы находятся в `docs/wip/` и `docs/REFACTORING_PLAN.md`.

## 1. Что это за система

Репозиторий объединяет несколько связанных контуров:

1. **CRM Streamlit** — интерфейс менеджера для закупок, категорий, объектов,
   аналитики, мониторинга и специализированных вертикалей.
2. **Commercial Routing V3** — определение коммерческой релевантности,
   жизненного цикла, приоритета и медали возможности на уровне пары
   «закупка × товарная категория».
3. **Tender Documents Research** — очередь, скачивание, разбор и анализ
   закупочной документации, включая таблицы, OCR, архивы, сметы и
   структурированные факты.
4. **Обучение и shadow-контуры** — OKPD Prior, классификация объекта,
   калибровка и теневые прогоны моделей.
5. **Эксплуатационный контур** — systemd units/drop-ins, сбор health-снимков,
   периодические синхронизации, пакетные и восстановительные скрипты.
6. **Отдельный лендинг `injekt-pro-landing/`** — статический сайт и небольшой
   Python-сервер заявок; он не является частью Streamlit runtime.

Канонические правила хостов, SSH/DB/service identities и доступа находятся
только в [PROJECT_OPERATING_RULES.md](PROJECT_OPERATING_RULES.md). Этот обзор
намеренно не дублирует секреты, адреса и identities.

## 2. Сквозная архитектура

```text
Источники закупок / реестры
          │
          ▼
CRM projection (`crm_procurements`) ──► категории и opportunity
          │                                  │
          │                                  ▼
          └──────────────► очередь документов и routing jobs
                                             │
                                             ▼
                         скачивание → парсинг → evidence / structured facts
                                             │
                                             ▼
                           правила + модели + экспертное подтверждение
                                             │
                                             ▼
                           canonical card / medal / UI projection / cache
                                             │
                                             ▼
                          Streamlit workspace, аналитика и мониторинг
```

Ключевые инварианты:

- коммерческая единица аналитики — **category opportunity**, а не просто
  закупка;
- source/history, CRM projection и document intelligence — разные контуры с
  явными границами записи;
- UI не должен выполнять SSH или инфраструктурные команды;
- сырые документы удаляются retention-политикой, поэтому извлечение фактов
  должно выполняться во время парсинга;
- модель предлагает результат, а authority, provenance и экспертное решение
  хранятся отдельно;
- `.env` — runtime-конфигурация, но не источник полномочий или человеческой
  identity.

## 3. Точки входа и запуск

| Точка входа | Назначение |
|---|---|
| `app.py` | Основной Streamlit entrypoint; настраивает страницу, стили и передаёт управление `src.ui.app_bootstrap.main()` |
| `src/ui/app_bootstrap.py` | Маршрутизация страниц, ленивое подключение БД, session service и watchdog соединений |
| `src/ui/nav.py` | Фактическое боковое меню и начальная страница `table_workspace` |
| `pages/AI_╨░╨╜╨░╨╗╨╕╤В╨╕╨║╨░.py` | Отдельная legacy/shadow Streamlit-страница; имя файла повреждено двойной перекодировкой |
| `tender_documents_research/document_processor/daemon.py` | Основной цикл document worker |
| `src/services/ai_assessment_runner.py` и `src/services/commercial_routing_v3/*worker*.py` | Фоновые AI/routing workers |
| `src/api/commercial_portal_api.py` | API коммерческого портала |
| `injekt-pro-landing/server.py` | Сервер отдельного лендинга |

Локальная базовая последовательность:

```powershell
python -m pip install -r requirements.txt
streamlit run app.py --server.port 8503
```

Проект требует Python `>=3.13,<3.14`. До запуска должен быть задан существующий
`CRM_SOURCE_ROOT`; `src/bootstrap.py` загружает корневой `.env`, добавляет этот
внешний исходник в `sys.path` и повторно утверждает настройки собственного
`.env`. Значения `.env` нельзя переносить в документацию.

## 4. Текущая навигация Streamlit

| Route | Экран | Зависимость |
|---|---|---|
| `table_workspace` | Таблица закупок | CRM DB |
| `pipeline` | Конвейер | локальный/snapshot-контур |
| `analytics_v3` | Аналитика V3 | CompaniesService |
| `opportunity_radar` | Радар объектов | CompaniesService |
| `computers` | Контур компьютеров | CompaniesService |
| `waterproofing` | Гидроизоляция | CompaniesService |
| `map` | Карта | CompaniesService |
| `infrastructure` | Инфраструктурное представление | DB handles, без тяжёлой загрузки компаний |
| `system_health` | Состояние серверов | health snapshot |
| `customers` | Заказчики | parking/session DB |
| `export_pdf` | PDF-очередь | CompaniesService |
| `crm_profiles` | Профили поиска | локальная CRM-конфигурация |
| `category_registry` | Товарные категории | CRM DB |
| `okpd_prior_analytics` | Диагностика OKPD Prior | без CompaniesService |

Скрытые/deep-link routes: `objects`, `objects_copy`, `objects_v2`, `companies`,
`ai_review`, `procurement_card`, `expert_annotation`. Старый Analytics V2
сохранён в коде, но текущая стартовая рабочая область — `table_workspace`.

## 5. Карта каталогов

| Путь | Содержимое и ответственность |
|---|---|
| `src/api/` | HTTP/API boundary коммерческого портала |
| `src/constants/` | Стабильные словари сегментов, групп и правил качества |
| `src/domain/` | Чистые доменные правила lifecycle, routing и taxonomy |
| `src/infrastructure/` | Низкоуровневое подключение к CRM DB |
| `src/learning/` | Обучение и скоринг OKPD Prior, procurement scope |
| `src/models/` | Доменные модели правил таксономии |
| `src/repositories/` | SQL/read-write adapters для analytics, taxonomy и predictions |
| `src/services/` | Основная бизнес-логика, интеграции, фоновые процессы и projections |
| `src/services/commercial_routing_v3/` | V3 pipeline: admission, evidence, scoring, lifecycle, model runs, medal, projection и workers |
| `src/services/document_learning/` | Разметка и обучение на документных сигналах |
| `src/services/first_pass/` | Первый проход анализа |
| `src/services/hydro/` | Домен гидроизоляции |
| `src/ui/` | Streamlit pages, форматирование и session boundaries |
| `src/ui/components/analytics_v2/` | Компоненты legacy Analytics V2 и annotation workspace |
| `src/migrations/` | Основные CRM schema/data migrations |
| `tender_documents_research/` | Самостоятельный document-intelligence runtime |
| `scripts/` | Аудиты, backfill, reconciliation, canary, batch и recovery-команды |
| `systemd/` | Базовые unit-файлы сервисов и таймеров |
| `deploy/systemd/` | Production drop-ins, resource policy и отключённые units |
| `migrations/` | Ранние/общие миграции вне `src` |
| `tests/` | Основной контрактный и unit/integration test corpus |
| `training/object_routing_v1/` | Dataset, LoRA training и evaluation object-routing модели |
| `docs/` | Канонические правила, дизайн, планы, WIP и отчёты |
| `data/` | Локальные runtime/shadow-данные; не источник кода |
| `logs/`, `scratch/`, `tmp_*` | Диагностика и временные рабочие артефакты |
| `worktrees/`, `.codex_worktrees/` | Вспомогательные checkout/worktree; не часть production runtime |

## 6. Основные сервисные области

### CRM и аналитика

- `companies_service.py`, `objects_service.py`, `objects_loader*.py` — загрузка
  и представление компаний/объектов;
- `analytics_*`, `v3_analytics_*` — снимки, KPI, funnel, category workspace и
  кэш аналитики;
- `crm_procurements_*` — canonical projection, синхронизация и lifecycle;
- `category_*`, `product_*`, `taxonomy_*` — реестр категорий, ontology,
  subcategory resolution и экспертная настройка;
- `system_health_*`, `pipeline_observability.py` — чтение и отображение
  эксплуатационных снимков;
- `pdf_export.py`, `export_queue_*` — генерация и очередь PDF.

### Commercial Routing V3

Пакет `src/services/commercial_routing_v3/` разделяет этапы:

1. нормализация закупки и source lifecycle;
2. category admission и hard veto;
3. сбор evidence, document needs и source enrichment;
4. подготовка model input/prompt и запуск inference;
5. проверка model JSON/result и запись model run;
6. arbitration, scoring, commercial timing и medal lineage;
7. запись canonical card, opportunity и UI projection;
8. shadow, observer, learning, factual feeder и autonomous worker.

`decision_authorities.py`, `field_provenance.py` и `medal_lineage.py` важны для
разделения вычисленного результата, источника и окончательной authority.

### Документный pipeline

`tender_documents_research/document_processor/` содержит:

- queue lifecycle: `queue_manager.py`, `queue_claim.py`,
  `queue_populate_coordinator.py`, `task_completion.py`;
- получение файлов: `downloader.py`, `http_client.py`, EIS rate-limit/recovery;
- форматы: `parser_factory.py`, `parsers/`, `format_converter.py`, OCR;
- архивы и валидацию: `archive_extractor.py`, `file_validator.py`, skip policy;
- matching: `matcher.py`, `match_engine.py`, `matching/`;
- извлечение фактов: `parse_extractors.py`, `embedded_extraction.py`,
  `structured_fact_*`, `project_metadata_reader.py`, `smeta_forma_4b.py`;
- шаблоны секций: lighting, drainage, flooring, roads, curbstone, cable
  support, sheets и registry `direct_template_registry.py`;
- bridge/provenance: CRM queue/observation store, evidence aggregator,
  section detector и context validator;
- backend abstractions: `backends/` и pipeline `pipelines/s13_v2_pipeline.py`.

Canonical document DB и допустимые queue statuses определены в
`PROJECT_OPERATING_RULES.md`, а не в старых README модуля.

### Специализированные контуры

- **Computers** — OKPD, subcategories, direct supply и отдельные UI/service
  правила;
- **Waterproofing/Hydro** — 615 store, CRM/funnel/scoring, board и daily sync;
- **Commercial portal** — API + service для внешнего read-oriented
  представления;
- **Search profiles** — профили источников и taxonomy-driven поиск;
- **Expert annotation** — очередь разметки, first decision gate и provenance;
- **System health** — GPU, температуры, SMART, services и S7/S13 snapshots без
  выполнения SSH из интерфейса.

## 7. Данные, БД и миграции

Логические хранилища:

- canonical CRM DB — карточки, opportunities, taxonomy, projections,
  annotations, model runs и analytics cache;
- document intelligence DB — очередь, файлы, результаты парсинга,
  structured facts и extraction runs;
- source/history DB — исходные реестры и lifecycle authority;
- дополнительные radar/parking connections — конфигурируются переменными
  окружения и используются только соответствующими сервисами.

Миграции сейчас распределены по трём местам:

- `src/migrations/` — 46 CRM-миграций;
- `tender_documents_research/migrations/` — 13 document migrations;
- `migrations/` — 3 ранние общие миграции.

Единого migration runner/ledger в репозитории не обнаружено. Порядок
применения определяется WIP/операционными инструкциями конкретного изменения;
по имени файла нельзя предполагать, что миграция уже применена.

## 8. Конфигурация и зависимости

- `pyproject.toml` и корневой `requirements.txt` согласованы по девяти базовым
  пакетам: Streamlit, pandas, psycopg2, dotenv, loguru, reportlab, requests,
  plotly и psutil.
- Profile manifests:
  - `documents` — `requirements-documents.txt`;
  - `learning` — `requirements-learning.txt`;
  - `training` — `requirements-training.txt`;
  - `dev` — `requirements-dev.txt`.
- `tender_documents_research/requirements.txt` отдельно описывает document
  runtime: Office/PDF/OCR/fuzzy matching и системные метрики.
- `psutil` перенесён в base; document/ML/training imports закреплены в
  соответствующих extras/manifests.

Phase 1 consistency audit выполняет двустороннее сравнение каждого effective
profile (`base`, `base+documents`, `base+learning`, `base+training`,
`base+dev`) с соответствующим requirements file по именам пакетов и exact
version specifiers.

## 9. Скрипты, службы и эксплуатация

`scripts/` содержит около 170 Python-команд. По назначению они делятся на:

- read-only audit/acceptance/diagnostics;
- backfill, reconciliation и materialization;
- queue/reprocess/worker launchers;
- calibration, simulation и dataset generation;
- canary, shadow и production-loop operations;
- recovery/admin-команды.

Имя `audit`, `verify` или `smoke` не гарантирует read-only режим: перед запуском
нужно читать код, WIP и operating rules. Скрипты не являются библиотечным API.

`systemd/` хранит базовые units, а `deploy/systemd/` — production drop-ins для
CPU/resource policy, batch scheduling, document bands, timers и disabled
workers. Наличие unit-файла в репозитории не подтверждает его установку или
активность на сервере.

## 10. Документация: что читать

| Документ | Роль |
|---|---|
| `README.md` | Краткая точка входа |
| `docs/PROJECT_OVERVIEW_AND_AUDIT.md` | Полная карта текущего дерева и аудит |
| `docs/MODULE_CONSISTENCY_REFACTORING_PLAN.md` | План устранения дублей, import/dependency drift и декомпозиции файлов >450 строк |
| `docs/wip/WIP_MODULE_CONSISTENCY_REFACTOR_V1.md` | Исполнительный WIP этого плана |
| `docs/PROJECT_OPERATING_RULES.md` | Единственный источник истины по доступу и identities |
| `docs/REFACTORING_PLAN.md` | Текущий этап архитектурного рефакторинга и журнал проверок |
| `docs/PROCUREMENT_ROUTING_TAXONOMY_CONTRACT.md` | Контракт routing/taxonomy |
| `docs/PROCUREMENT_SEARCH_CONTOUR_DESIGN.md` | Дизайн поискового контура |
| `docs/NORMALIZATION_TEMPLATES.md` | Правила нормализации и шаблонов |
| `docs/MODEL_TRAINING_AND_PRIORITY.md` | Обучение и приоритеты |
| `docs/COMMERCIAL_PORTAL_API_CONTRACT.md` | Контракт portal API |
| `docs/wip/README.md` и `docs/wip/WIP_*.md` | Активные локальные инициативы; не стабильный API |
| `docs/reports/` | Результаты конкретных аудитов/прогонов |
| `tender_documents_research/docs/archive/` | Исторические снимки, не источник текущей истины |

## 11. Результат статического аудита согласованности

Проверено без импорта runtime-модулей и без подключения к БД:

- 968 Python-файлов, включая основной `tests/` corpus;
- все 968 файлов разбираются Python AST без синтаксических ошибок;
- корневой README содержит 6 локальных ссылок, все существуют;
- все handled routes имеют явные dependency-классы;
- все пять dependency profiles совпадают с requirements manifests в обе
  стороны;
- unresolved internal imports = 0.

### Найденные несоответствия

| Приоритет | Наблюдение | Рекомендация |
|---|---|---|
| Закрыто | Orphan `src/services/crm_procurements_repository.py` с missing import | Удалён в Phase 1; callers не найдены |
| Закрыто | Runtime/ML/training imports отсутствовали в manifests | Добавлены и двусторонне проверены профили `documents`, `learning`, `training`, `dev` |
| Закрыто | Exact service-копии `card_compact`, `crm_profiles_page` и legacy UI/service shadow-модули | Phase 2 оставил canonical UI authority; duplicate runtime groups и UI-code-in-services = 0 |
| Средний | 68 рабочих Python-файлов превышают 450 строк; крупнейшие: `crm_ai_assessment_runner.py` (1932), `embedded_extraction.py` (1440), `analytics_v2/tabs.py` (1152), `procurement_card_dossier_service.py` (1090), `object_detail.py` (1081) | Для затрагиваемых файлов записывать объяснение в плане или декомпозировать по правилу проекта; не начинать массовый рефакторинг вне текущего этапа |
| Средний | 11 тестовых модулей также превышают 450 строк | Декомпозировать после стабилизации production authorities, по behavior contracts |
| Средний | Три каталога миграций не имеют общего ledger/runner | Зафиксировать ownership, порядок и applied-state вне имён файлов |
| Средний | `tender_documents_research/README.md` и `document_processor/README.md` содержали снимок августа 2026, старую БД/топологию и несуществующие имена файлов | README сокращены до актуальной карты и подчинены operating rules |
| Закрыто | Deep-link `procurement_card` полагался на default dependency | Явно задан `CRM_DB_ONLY` в Phase 1 |
| Низкий | Доступный локально Python — 3.12.10 при требовании проекта `>=3.13,<3.14` | Выполнять runtime/import/test acceptance в Python 3.13 environment |
| Низкий | Имя файла `pages/AI_╨░╨╜╨░╨╗╨╕╤В╨╕╨║╨░.py` повреждено перекодировкой | Переименовать отдельным изменением с проверкой Streamlit multipage navigation |
| Закрыто | Runtime backup artifacts `.bak`, `.backup`, `.tmp_path_issue` | Удалены в Phase 2; historical evidence snapshots в `scratch/` и docs сохранены отдельно |
| Низкий | Единственная битая Markdown-ссылка находится в архиве: `tender_documents_research/docs/archive/FULL_PRODUCT_FUNNEL.md` → отсутствующий `FULL_PRODUCT_FUNNEL.sql` | Оставить как исторический дефект либо добавить явную пометку «файл утрачен» |

### Что не проверялось

По правилам проекта автоматические тесты, линтеры, сборки, DB queries и
production probes не запускались. Поэтому аудит подтверждает структурную и
статическую согласованность, но не подтверждает runtime-состояние БД,
активность systemd units, качество данных или прохождение test suite.

## 12. Правила безопасного изменения

1. Перед архитектурным изменением прочитать `docs/REFACTORING_PLAN.md` и
   работать только в текущем этапе.
2. Перед инфраструктурным действием полностью прочитать
   `docs/PROJECT_OPERATING_RULES.md`.
3. Не смешивать source DB, CRM projection и document intelligence writes.
4. Для migration/backfill сначала определить authority, owner, dry-run и
   rollback/preimage.
5. При изменении route синхронно обновлять `src/ui/nav.py`,
   `src/ui/app_bootstrap.py` и `src/ui/page_deps.py`.
6. При изменении document parsing сохранять provenance и учитывать retention.
7. Не считать snapshot/WIP/archive-документ текущей эксплуатационной истиной.
8. После изменения обновлять этот обзор только по подтверждённому коду, а не
   по планируемой архитектуре.
