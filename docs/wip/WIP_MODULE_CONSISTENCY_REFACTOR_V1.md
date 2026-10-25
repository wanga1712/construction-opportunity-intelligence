# WIP MODULE_CONSISTENCY_REFACTOR_V1 — единая authority модулей и файлы >450 строк

Status: **PHASE 1 ACCEPTED / PHASE 2 DUPLICATE AUTHORITY DONE — READY FOR REVIEW**.

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

## RESULT (2026-10-25) — PHASE 1

STATUS: **DONE AFTER REVIEW REWORK — consistency blockers closed. Phase 2 not started.**

CHANGES:

- deleted orphan `src/services/crm_procurements_repository.py`; repository-wide
  search found no Python callers, only historical documentation references;
- added explicit `"procurement_card": PageDependency.CRM_DB_ONLY` to
  `PAGE_DEPENDENCY`;
- removed fragile `QueueManager`/`DaemonMaintenance` delegation from
  `src/services/queue_repository.py`; legacy methods now use canonical
  `tender_documents_research.document_processor.queue_claim` and their existing
  `DatabaseManager` boundary;
- `LegacyQueueRepository.claim_batch` now passes the full required
  `claim_batch_ids` contract: `where_extra=""` and `extra_params=[]`;
- `document_processor.queue_manager` and `database_work.database_connection`
  explicitly support both import contracts: canonical project package mode and
  production top-level mode (`python -m document_processor.daemon`);
- the method-level contract test actually calls the real unmodified
  `claim_batch_ids` through fake DB, then calls `mark_no_links` and
  `reset_stale_tasks`; it asserts the generated claim SQL and parameters; a
  subprocess test loads the same runtime in both import modes without a special
  document-runtime `PYTHONPATH`;
- canonicalized `annotation_state_service` import in
  `scripts/audit_annotation_states.py` to
  `src.services.annotation_state_service`;
- defined dependency profiles:
  - **base** = `[project].dependencies` / `requirements.txt`;
  - **documents** = `pyproject.toml[documents]` /
    `requirements-documents.txt`;
  - **learning** = `pyproject.toml[learning]` /
    `requirements-learning.txt`;
  - **training** = `pyproject.toml[training]` /
    `requirements-training.txt`;
  - **dev** = `pyproject.toml[dev]` / `requirements-dev.txt`;
- added `psutil` to base; Python 3.13-compatible learning versions;
- added `scripts/audit_module_consistency_phase1.py`;
- added `tests/test_module_consistency_phase1.py`;
- audit recursively opens all five requirements files and compares effective
  profiles with `pyproject.toml` in both directions by package name and exact
  version specifier;
- removed accidental empty file `$null`;
- synchronized `README.md` and `docs/PROJECT_OVERVIEW_AND_AUDIT.md` with the
  five dependency profiles and closed Phase 1 findings.

PYTHON 3.13 COMMANDS:

```text
tar -czf module_consistency_phase1_snapshot_final.tar.gz \
  app.py nav.py pyproject.toml requirements*.txt src scripts \
  tender_documents_research training pages tests deploy

/opt/CRM_Streamlit/.venv313/bin/python -m py_compile \
  app.py src/ui/page_deps.py src/services/queue_repository.py \
  scripts/audit_annotation_states.py \
  scripts/audit_module_consistency_phase1.py

PYTHONPATH=<snapshot> \
/opt/CRM_Streamlit/.venv313/bin/python \
  scripts/audit_module_consistency_phase1.py

PYTHONPATH=<snapshot> \
/opt/CRM_Streamlit/.venv313/bin/python -m pytest -q \
  tests/test_module_consistency_phase1.py

git archive --format=tar.gz -o prephase_98a0fe5.tar.gz 98a0fe5

CRM_SOURCE_ROOT=/opt/pythonProject89 \
PYTHONPATH=/opt/pythonProject89:<prephase-snapshot>:/opt/tender_documents_research \
/opt/CRM_Streamlit/.venv313/bin/python -m pytest -q --tb=short \
  tests/test_app_bootstrap_relocation.py \
  tests/test_production_entrypoint.py \
  tests/test_ui_interactive_performance.py \
  tests/test_ui_resource_policy_contract.py

CRM_SOURCE_ROOT=/opt/pythonProject89 \
PYTHONPATH=/opt/pythonProject89:<phase1-snapshot>:/opt/tender_documents_research \
/opt/CRM_Streamlit/.venv313/bin/python -m pytest -q --tb=short \
  tests/test_app_bootstrap_relocation.py \
  tests/test_production_entrypoint.py \
  tests/test_ui_interactive_performance.py \
  tests/test_ui_resource_policy_contract.py

git archive --format=tar.gz -o prephase_0f99be0.tar.gz 0f99be0

CRM_SOURCE_ROOT=/opt/pythonProject89 \
PYTHONPATH=/opt/pythonProject89:<prephase-0f99be0-snapshot>:/opt/tender_documents_research \
/opt/CRM_Streamlit/.venv313/bin/python -m pytest -q --tb=short \
  tests/test_app_bootstrap_relocation.py \
  tests/test_production_entrypoint.py \
  tests/test_ui_interactive_performance.py \
  tests/test_ui_resource_policy_contract.py
```

RESULTS:

```text
PYTHON_RUNTIME=3.13.14
PYTHON_FILES=795
UNRESOLVED_INTERNAL_IMPORTS=0
HANDLED_ROUTES=21
MISSING_ROUTE_DEPENDENCIES=0
UNDECLARED_DIRECT_IMPORTS=0
PROFILE_MANIFEST_GAPS=0
PROFILE_MANIFEST_TWO_WAY=PASS
PROFILE_MANIFEST_VERSION_SPECIFIERS=PASS
PROFILE_MANIFEST_DETAIL=base/documents/learning/training/dev:PASS
TARGETED_PHASE1_TEST=4_passed
LEGACY_QUEUE_METHODS_TESTED=claim_batch,mark_no_links,reset_stale_tasks
NO_DOC_RUNTIME_PYTHONPATH=YES
PROJECT_PACKAGE_IMPORT_MODE=PASS
PRODUCTION_TOP_LEVEL_IMPORT_MODE=PASS
MANIFEST_NEGATIVE_CONTROL=PASS
PY_COMPILE=PASS
NULL_FILE_PRESENT=NO
REAL_CLAIM_BATCH_IDS_PATH=PASS
CLAIM_BATCH_MONKEYPATCH=NO
```

ACCEPTANCE:

```text
UNRESOLVED_INTERNAL_IMPORTS=0
ALL_HANDLED_ROUTES_HAVE_EXPLICIT_DEPENDENCY=YES
DIRECT_IMPORTS_DECLARED_IN_PROFILE=YES
PYTHON_RUNTIME=3.13
REAL_LEGACY_CLAIM_PATH_TESTED=YES
BUSINESS_LOGIC_CHANGED=NO
DB_WRITES=0
```

DEVIATIONS:

- local Windows interpreter is Python 3.12.10, so all Python 3.13 checks were
  executed against a temporary read-only repository snapshot using the S13
  Python 3.13.14 venv; production files were not deployed;
- regression evidence is anchored at pre-Phase-1 `0f99be0`; while review was
  in progress the branch advanced through independent direct-supply commit
  `6f6052a`. Phase 1 remained uncommitted above that HEAD. Reviewer repeated
  the read-only consistency audit on the combined worktree: 796 scanned files,
  manifest/import/route gaps 0; the only local audit failure is the expected
  Python 3.12 runtime gate. Direct-supply commits remain otherwise unmodified;
- the earlier unsupported statement about “9 old failures” is withdrawn. The
  executed selection contains 24 tests and has exactly **17 passed / 7 failed**
  on both pre-Phase-1 `0f99be0` and the Phase 1 snapshot:

```text
test_app_bootstrap_relocation.py::test_canonical_function_exports_and_signatures
test_app_bootstrap_relocation.py::test_relocated_page_selection_and_orchestration_order
test_app_bootstrap_relocation.py::test_relocated_unknown_route_behavior
test_production_entrypoint.py::test_bootstrap_runs_watchdog_navigation_and_renderer_once
test_ui_interactive_performance.py::test_companies_pages_require_service
test_ui_interactive_performance.py::test_objects_v2_still_gets_companies_service
test_ui_resource_policy_contract.py::test_background_slice_excludes_interactive_cpus
```

  The `0f99be0` and Phase 1 runs have the same failure set and counts. The
  7-failure set is therefore baseline, not a Phase 1 regression;
- dependency profile versions target Python 3.13 but packages were not installed
  or resolved from the network during this read-only audit.

EVIDENCE FILES:

```text
docs/reports/module_consistency_phase1/phase1_audit_py313.json
docs/reports/module_consistency_phase1/prephase_98a0fe5_pytest.txt
docs/reports/module_consistency_phase1/prephase_0f99be0_pytest.txt
docs/reports/module_consistency_phase1/phase1_pytest.txt
docs/reports/module_consistency_phase1/phase1_targeted_pytest.txt
docs/reports/module_consistency_phase1/phase1_import_contract_py313.txt
```

NEXT: Phase 2 only after explicit user request.

## REVIEW (2026-10-25) — ACCEPTED

Reviewer reproduced the real, unpatched call
`LegacyQueueRepository(FakeDb()).claim_batch(17, 1, ["open_active"])` and
verified the returned row mapping, generated `UPDATE document_processing_queue`,
lane predicate and parameters `(17, 17, "open_active", 1)`. `mark_no_links`
and `reset_stale_tasks` were also executed against the fake DB boundary.

```text
REAL_CLAIM_BATCH_IDS_PATH=PASS
CLAIM_BATCH_MONKEYPATCH=NO
LOCAL_COMBINED_TREE_FILES=796
LOCAL_MANIFEST_GAPS=0
LOCAL_UNRESOLVED_IMPORTS=0
LOCAL_MISSING_ROUTE_DEPENDENCIES=0
PYTHON_3_13_EVIDENCE=4 passed
PHASE_1_REVIEW=ACCEPTED
PHASE_2_STARTED=NO
DB_WRITES=0
```

## RESULT (2026-10-25) — PHASE 2

STATUS: **DONE — duplicate authorities and runtime backup artifacts removed.**

CHANGES:

- removed exact service copies:
  - `src/services/card_compact.py`;
  - `src/services/crm_profiles_page.py`;
- canonicalized app/navigation:
  - kept root `app.py` as Streamlit entrypoint;
  - kept `src/ui/app_bootstrap.py` and `src/ui/nav.py`;
  - removed root `nav.py`, `src/services/app.py`, `src/services/nav.py`;
- removed UI implementations from services:
  - `analytics_contour_v2_page.py`;
  - `card_tabs_ai.py`;
  - `card_tabs_medals.py`;
  - `tabs.py`;
- removed legacy service-page mock-card tests and the obsolete service fallback
  assertion; canonical UI/repository coverage remains in `tests/`;
- removed `src/ui/product_subcategories_service.py`; canonical schema/service
  authority is `src/services/product_subcategories_service.py`;
- removed undiscovered `src/ui/components/analytics_v2/test_torgi_tab.py`;
  discoverable `tests/test_torgi_tab.py` remains the broader/newer suite;
- removed tracked runtime backup artifacts: three `.bak` files, two
  `downloader/http_client.backup` files and
  `src/services/computers_service.py.tmp_path_issue/`;
- backup audit recognizes `.bak`, `.bak_*`, `.bak.*`, `.backup`, `.orig` and
  any path component ending in `.tmp_path_issue`; it also reports an empty
  legacy temp directory;
- physically removed leftover
  `src/services/computers_service.py.tmp_path_issue/__pycache__`;
- restored original Unicode/`None`/empty-string category rows in
  `tests/test_analytics_v2_categories_boundary.py`;
- `scripts/production_reconciliation_audit.py` no longer treats
  `src/services/app.py` as host-local configuration; a production copy is
  classified as `STALE_OLD_CODE`;
- added read-only `scripts/audit_module_consistency_phase2.py` and
  `tests/test_module_consistency_phase2.py`, including negative controls for
  duplicate files, hidden tests and backup detection.

PYTHON 3.13.14 RESULTS:

```text
EXACT_DUPLICATE_RUNTIME_GROUPS=0
CANONICAL_APP_AUTHORITY=app.py+src/ui/app_bootstrap.py
CANONICAL_NAV_AUTHORITY=src/ui/nav.py
UI_CODE_IN_SERVICES_DUPLICATION=0
PRODUCT_SUBCATEGORY_SCHEMA_AUTHORITY=src/services/product_subcategories_service.py
UNDISCOVERED_TEST_COPIES=0
BACKUP_ARTIFACTS=0
BACKUP_PATTERN_NEGATIVE_CONTROLS=PASS
EMPTY_TMP_PATH_ISSUE_DIRECTORY_DETECTED=YES
RESTORED_CATEGORY_COVERAGE=PASS
PHASE2_TARGETED_TEST=5_passed
DB_WRITES=0
```

The expanded targeted selection has 13 failures on Phase 2 versus 15 on
pre-Phase-2 `cfcb657`. Every Phase 2 failure name is present in the baseline;
the two removed failures belonged to the deleted legacy service-page module.
No new failing test was introduced. Existing baseline defects remain recorded in
evidence and are not hidden or converted into passes.

EVIDENCE:

```text
docs/reports/module_consistency_phase2/phase2_audit_py313.json
docs/reports/module_consistency_phase2/phase2_targeted_pytest.txt
docs/reports/module_consistency_phase2/phase2_expanded_pytest.txt
docs/reports/module_consistency_phase2/prephase2_cfcb657_pytest.txt
```

DEVIATIONS:

- `docs/reports/procurement_identity_link_deadline_correctness/s7_required_tags_223_fz.json.bak`
  is a historical evidence snapshot, not runtime code, and was retained;
- historical copies under `scratch/production_reconciliation/` are retained as
  audit snapshots and are outside runtime roots;
- `scripts/repair_lighting_estimate_facts.py` belongs to parallel work and is
  excluded from Phase 2;
- concurrent modifications to `src/services/good_supply_facts_service.py` and
  `src/services/works_vs_goods_service.py` also belong to parallel work and are
  excluded from Phase 2;
- no commit or deploy was performed for Phase 2.

NEXT: Phase 3 only after explicit user request.

## REVIEW (2026-10-25) — PHASE 2 ACCEPTED

Reviewer checks confirmed the corrected backup/path detection, restored category
boundary coverage, and `STALE_OLD_CODE` reconciliation classification. Direct
negative controls detected both `x.py.bak_local_20261025` and empty/non-empty
`foo.tmp_path_issue`; the repository audit reported no runtime backup artifacts,
duplicate authorities, hidden tests, or UI implementations under services.

The saved Python 3.13.14 evidence reports `5 passed`. The local reviewer runtime
is Python 3.12, so its explicit Python 3.13 gate is not a substitute for that
evidence; all non-runtime audit fields and direct negative controls were
reproduced. All 13 current expanded-suite failure names are present in the
pre-Phase-2 baseline.

The accepted changeset is based on current HEAD `5cf084e`; concurrent commits
`a346db4` and `5cf084e` are already in ancestry. The remaining working-tree
change in `src/services/works_vs_goods_service.py` is parallel work and is
explicitly excluded from the Phase 2 commit.

```text
PHASE_2_REVIEW=ACCEPTED
PHASE_2_COMMIT_SCOPE=WHITELISTED
PHASE_2_DEPLOYED=NO
PHASE_3_STARTED=NO
DB_WRITES=0
```
