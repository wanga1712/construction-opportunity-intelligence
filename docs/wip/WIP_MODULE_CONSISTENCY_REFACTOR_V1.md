# WIP MODULE_CONSISTENCY_REFACTOR_V1 — единая authority модулей и файлы >450 строк

Status: **PHASE 0 AUDIT DONE / IMPLEMENTATION NOT STARTED**.

Owner: repository architecture, Python runtime, CRM UI, routing and document pipeline.

Master plan: `docs/MODULE_CONSISTENCY_REFACTORING_PLAN.md`.

## Контекст

Аудит 2026-10-25 подтвердил, что проект синтаксически целостен, но содержит:

- один импорт отсутствующего внутреннего модуля;
- две точные пары копий и несколько расходящихся UI/service shadow-копий;
- неявный dependency contract одного deep-link route;
- прямые импорты, не полностью покрытые dependency manifests;
- 68 production/operations файлов и 11 тестов длиннее 450 строк;
- три раздельных migration roots без общего applied-state ledger;
- backup/temp artifacts внутри рабочего дерева;
- локальный Python 3.12 при обязательном Python 3.13 проекта.

Этот WIP задаёт порядок исправления. Он не разрешает массовый рефакторинг и
не заменяет текущий этап `docs/REFACTORING_PLAN.md`.

## Scope

В scope:

1. import, route и dependency consistency;
2. canonical module authority и удаление подтверждённых копий;
3. декомпозиция всех production/operations Python-файлов >450 строк;
4. декомпозиция крупных тестов;
5. статический migration inventory и repository hygiene;
6. обновление документации и acceptance evidence.

## Out of scope

- изменение коммерческой логики, medal/scoring/admission;
- новые категории, правила нормализации или model prompts;
- DDL, backfill, production DB writes;
- deploy, SSH, systemd restart/install;
- массовое переименование public APIs в одной фазе;
- удаление historical reports и scratch без отдельной проверки.

## Frozen invariants

- root `app.py` остаётся production Streamlit entrypoint;
- current sidebar authority — `src/ui/nav.py`;
- category opportunity остаётся единицей коммерческой аналитики;
- MODEL/EXPERT/RULE authority и field provenance не смешиваются;
- source DB, CRM DB и document intelligence writes не переносятся между
  контурами;
- document queue states/completion guard/retention semantics сохраняются;
- Streamlit route names, session keys и deep links сохраняются либо получают
  compatibility mapping;
- рефакторинг не меняет SQL и бизнес-результат одновременно.

## Phase gates

Каждая следующая фаза начинается только после отдельного явного запроса
пользователя. После каждой фазы в этот файл добавляется `## RESULT` с evidence,
acceptance, deviations и follow-up.

### Phase 0 — read-only inventory — DONE

Выполнено:

- AST parse 968 Python-файлов;
- внутренние absolute-import checks;
- comparison `PAGES` / `_render_page` / `PAGE_DEPENDENCY`;
- exact hash и AST duplicate scan;
- same-basename/near-copy review;
- dependency import inventory;
- полный список файлов >450 строк.

### Phase 1 — consistency blockers

Задачи:

1. Проверить dynamic callers `crm_procurements_repository.py`.
2. Удалить orphan либо заменить отсутствующий `session_crm_db` на
   существующий DB boundary.
3. Явно внести `procurement_card` в `PAGE_DEPENDENCY`.
4. Спроектировать dependency extras: base/documents/learning/training/dev.
5. Выполнить изменения только в Python 3.13 environment.

Acceptance:

```text
UNRESOLVED_INTERNAL_IMPORTS=0
ALL_HANDLED_ROUTES_HAVE_EXPLICIT_DEPENDENCY=YES
DIRECT_IMPORTS_DECLARED_IN_PROFILE=YES
PYTHON_RUNTIME=3.13
BUSINESS_LOGIC_CHANGED=NO
DB_WRITES=0
```

Проверки:

- syntax/import изменённых файлов;
- targeted route/bootstrap tests;
- targeted dependency/import audit;
- тесты затронутого repository, если модуль сохраняется.

### Phase 2 — duplicate authority

Подфазы выполняются отдельными изменениями:

1. exact copies: `card_compact`, `crm_profiles_page`;
2. nav/app/bootstrap family;
3. Analytics V2/card tabs/tabs UI-in-services family;
4. product subcategory semantic duplicate;
5. hidden `src/.../test_torgi_tab.py`;
6. backup/temp artifacts.

До удаления каждого файла:

- проверить static imports, string/dynamic references, systemd/CLI entrypoints;
- выбрать canonical path;
- при необходимости оставить thin compatibility facade;
- зафиксировать recoverable commit/preimage;
- выполнить targeted tests под Python 3.13.

Acceptance:

```text
EXACT_DUPLICATE_RUNTIME_GROUPS=0
CANONICAL_APP_AUTHORITY=app.py+src/ui/app_bootstrap.py
CANONICAL_NAV_AUTHORITY=src/ui/nav.py
UI_CODE_IN_SERVICES_DUPLICATION=0
PRODUCT_SUBCATEGORY_SCHEMA_AUTHORITY=ONE
UNDISCOVERED_TEST_COPIES=0
DB_WRITES=0
```

### Phase 3 — critical files >900

Каждый subsystem получает child-WIP с characterization tests и явными seams.
Очередь:

1. `crm_ai_assessment_runner.py`;
2. `commercial_routing_v3/queue_producer.py`;
3. `commercial_routing_v3/projection_writer.py`;
4. `commercial_routing_v3/autonomous_learning_loop.py`;
5. `direct_document_extractor.py`;
6. `procurement_card_dossier_service.py`;
7. `document_processor/embedded_extraction.py`;
8. `document_processor/downloader.py`;
9. `ui/components/analytics_v2/tabs.py`;
10. `ui/object_detail.py`;
11. `ui/procurement_card_page.py`;
12. `ui/components/analytics_v2/annotation_card.py`;
13. `scripts/_phase8_build_audit.py`.

Общий acceptance каждого child-WIP:

```text
PUBLIC_IMPORT_COMPATIBLE=YES
TARGET_MODULE_LINES<=450_OR_JUSTIFIED
NEW_MODULE_LINES_TARGET<=300
CIRCULAR_IMPORTS=0
TARGETED_TESTS=PASS
SQL_SHAPE_CHANGED=NO
BUSINESS_OUTPUT_CHANGED=NO
```

### Phase 4 — files 700–900

Порядок:

1. active CRM services and table workspace;
2. routing V3;
3. document daemon/context;
4. active UI pages/components;
5. operational scripts.

Не объединять разные subsystem в один diff.

### Phase 5 — files 451–699

- разделять по cohesive responsibilities;
- не создавать passthrough-модули ради числа строк;
- оставшийся файл >450 получает rationale в master plan и WIP RESULT;
- shared helpers вводятся только при двух реальных consumers.

### Phase 6 — tests >450

Разделить 11 тестов по behavior contracts. Не зеркалить структуру реализации.
Duplicate torgi test предварительно канонизируется в Phase 2.

Acceptance:

```text
TESTS_OUTSIDE_CONFIGURED_TEST_ROOT=0
TEST_MODULE_LINES<=450_OR_JUSTIFIED
BEHAVIOR_COVERAGE_LOST=NO
TARGETED_TESTS=PASS
```

### Phase 7 — migration/docs/hygiene closure

1. Read-only migration roots/applied-state inventory.
2. Repository backup/temp policy.
3. Повторный duplicate/import/size scan.
4. Обновление README, overview и module maps.
5. Полный test suite в Python 3.13 environment.

## Полный inventory

Полный список 68 production/operations файлов и 11 тестов с числом строк
находится в `docs/MODULE_CONSISTENCY_REFACTORING_PLAN.md`, раздел 6. Он является
baseline этого WIP. При изменении строк inventory обновляется в RESULT фазы, а
исходный baseline не переписывается.

## Global acceptance

```text
PYTHON_FILES_PARSED=968
SYNTAX_ERRORS=0
UNRESOLVED_INTERNAL_IMPORTS=0
EXACT_DUPLICATE_RUNTIME_GROUPS=0
ALL_ROUTES_EXPLICITLY_CLASSIFIED=YES
DIRECT_IMPORTS_DECLARED=YES
PRODUCTION_FILES_OVER_450=0_OR_JUSTIFIED
TEST_FILES_OVER_450=0_OR_JUSTIFIED
CANONICAL_MODULE_AUTHORITIES_DOCUMENTED=YES
PYTHON_3_13_TARGETED_TESTS=PASS
FULL_SUITE_PYTHON_3_13=PASS
PRODUCTION_DB_WRITES=0
DEPLOY_PERFORMED=NO
```

## Risks

- dynamic imports и external production reconciliation могут не проявляться в
  обычном import graph;
- Streamlit session state и cache decorators чувствительны к перемещению
  callable;
- split transaction/repository кода может незаметно изменить commit/rollback;
- document pipeline зависит от cwd/package mode (`document_processor` против
  `tender_documents_research.document_processor`);
- старые service-копии могут использоваться внешним скриптом, отсутствующим в
  репозитории;
- механическая декомпозиция может увеличить количество циклических импортов.

## Rollback

- одна фаза/подфаза — один recoverable commit;
- public facade удаляется только в следующей фазе после подтверждения callers;
- никакого `git reset --hard` или удаления backup artifacts до inventory;
- при behavioral drift откатывается только текущая подфаза, не весь master WIP.

## RESULT (2026-10-25)

STATUS: **PARTIAL — PHASE 0 DONE, CODE CHANGES NOT STARTED**

EVIDENCE:

```text
ALL_PY=968
SYNTAX_ERRORS=0
PRODUCTION_OPERATIONS_OVER_450=68
TEST_FILES_OVER_450=11
EXACT_DUPLICATE_GROUPS_GT200=2
UNRESOLVED_INTERNAL_IMPORTS=1
NAV_WITHOUT_HANDLER=[]
NAV_WITHOUT_DEP=[]
HANDLER_WITHOUT_EXPLICIT_DEP=['procurement_card']
LOCAL_PYTHON=3.12.10
PROJECT_PYTHON=>=3.13,<3.14
```

ACCEPTANCE:

- Phase 0 inventory complete = YES;
- master plan created = YES;
- code refactoring complete = NO;
- runtime behavior verified = NO;
- tests run = NO.

DEVIATIONS:

- runtime imports and tests intentionally not executed because the available
  interpreter is Python 3.12, while the project requires Python 3.13;
- existing dirty changes in `docs/REFACTORING_PLAN.md`, WIP files and runtime
  modules were not modified.

FOLLOW-UP:

- explicit user request to start **Phase 1**;
- provide/use a Python 3.13 environment before code acceptance.
