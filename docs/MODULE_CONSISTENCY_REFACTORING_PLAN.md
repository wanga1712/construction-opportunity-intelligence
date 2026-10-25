# План согласования модулей и декомпозиции файлов >450 строк

Дата: **2026-10-25**

Статус: **план подготовлен; кодовые фазы не начаты**

Исполнительный WIP: `docs/wip/WIP_MODULE_CONSISTENCY_REFACTOR_V1.md`

Этот план является follow-up к `docs/PROJECT_OVERVIEW_AND_AUDIT.md`. Он не
заменяет текущий этап `docs/REFACTORING_PLAN.md` и не разрешает переходить к
следующей фазе без отдельного запроса пользователя.

## 1. Цели

1. Устранить разрывы внутренних импортов и неоднозначные module authorities.
2. Удалить подтверждённые копии и изолировать осознанные одноимённые модули.
3. Привести dependency manifests и фактические импорты к одному контракту.
4. Декомпозировать 68 production/operations Python-файлов длиннее 450 строк.
5. Отдельно уменьшить 11 тестовых модулей длиннее 450 строк.
6. Сохранить поведение UI, routing, document pipeline, scoring, provenance и
   DB boundaries.

## 2. Базовый аудит

Статический аудит выполнен без импорта runtime-кода, БД и инфраструктуры:

```text
Python files inspected                         968
Python AST syntax errors                         0
Production/operations files >450 lines          68
Test files >450 lines                            11
Exact duplicate implementation groups            2
Unresolved internal imports                       1
Sidebar routes without handler/dependency         0
Handled route relying on dependency fallback      1
Local Python                                  3.12.10
Required Python                            >=3.13,<3.14
```

Следствие: синтаксис и статические связи проверены, но runtime/test acceptance
должен выполняться в Python 3.13. Результат запуска под локальным 3.12 не может
быть каноническим для проекта.

## 3. Выявленные проблемы согласованности

### 3.1. Разрыв импорта

`src/services/crm_procurements_repository.py` импортирует отсутствующий
`src.services.session_crm_db`. Других импортов самого repository в рабочем коде
не найдено. Это либо orphan legacy, либо незавершённая миграция DB boundary.

Решение принимается только после проверки dynamic entrypoints:

- предпочтительно удалить orphan-модуль;
- если он нужен — перевести его на актуальный `session_deps`/`db_bootstrap`
  контракт без создания ещё одного DB singleton.

### 3.2. Dependency drift

Корневые `pyproject.toml` и `requirements.txt` совпадают между собой, но не
полностью покрывают прямые импорты `src/`: `PyPDF2`, `pypdf`, `python-docx`,
`PyMuPDF`, `psutil`; ML-профиль также использует scipy. Training использует
`torch`, `transformers`, `peft`, `bitsandbytes` в отдельном окружении.

Целевая схема:

- base/runtime — обязательный запуск Streamlit;
- `documents` — PDF/Office/OCR;
- `learning` — numpy/scipy/scikit-learn/catboost;
- `training` — torch/transformers/peft/bitsandbytes;
- `dev` — pytest/ruff/mypy.

Прямо импортируемый пакет должен быть явно объявлен в своём профиле, даже если
сейчас он случайно приходит транзитивно.

### 3.3. Routing drift

Все 14 sidebar routes имеют handler и явный dependency-класс. Deep-link
`procurement_card` имеет handler, но отсутствует в `PAGE_DEPENDENCY` и получает
`COMPANIES_SERVICE` через fallback. Поведение сейчас определено, но контракт
неявный.

### 3.4. Migration drift

Миграции лежат в `migrations/`, `src/migrations/` и
`tender_documents_research/migrations/`. Единого applied-state ledger в кодовой
базе не обнаружено. Объединять каталоги без отдельного migration WIP нельзя;
сначала нужен read-only inventory ownership/order/applied state.

## 4. Аудит дублирования

### 4.1. Подтверждённые точные копии

| Копия | Канонический кандидат | Основание |
|---|---|---|
| `src/services/card_compact.py` | `src/ui/components/analytics_v2/card_compact.py` | Побайтно и AST-идентичны; тесты ссылаются на UI-путь |
| `src/services/crm_profiles_page.py` | `src/ui/crm_profiles_page.py` | Побайтно и AST-идентичны; bootstrap импортирует UI-путь |

Копии в `src/services` не удаляются до проверки production reconciliation
scripts/manifests и Python 3.13 acceptance.

### 4.2. Почти полные или расходящиеся shadow-копии

| Семейство | Наблюдение | План |
|---|---|---|
| `src/services/card_tabs_medals.py` и `src/ui/components/analytics_v2/card_tabs_medals.py` | Сходство 99.9%; отличается пользовательский текст AI/business authority | Канонизировать UI-версию, проверить, что service-копия не является production entrypoint |
| `nav.py`, `src/services/nav.py`, `src/ui/nav.py` | Три поколения меню; сходство 79.6–90.6%; runtime импортирует `src/ui/nav.py` | Оставить `src/ui/nav.py`; root/service версии удалить или превратить в явные compatibility facades только при наличии внешних потребителей |
| `src/services/app.py` и root `app.py` + `src/ui/app_bootstrap.py` | Старый монолитный bootstrap сосуществует с новым entrypoint | Проверить внешние entrypoints; systemd запускает root `app.py`, затем архивировать/удалить service-монолит |
| `src/services/analytics_contour_v2_page.py` и `src/ui/analytics_contour_v2_page.py` | Старый mock-based экран против актуального queue-first UI | Канонический путь — `src/ui`; удалить legacy после проверки deep links |
| `src/services/card_tabs_ai.py`, `card_tabs_medals.py`, `tabs.py` | UI-код находится в services и расходится с `src/ui/components/analytics_v2/` | Перенести authority в UI; shared pure logic вынести в domain/service без Streamlit |
| `src/ui/product_subcategories_service.py` и `src/services/product_subcategories_service.py` | Не копии: две расходящиеся реализации одной таблицы/DDL и seed-модели; прямых импортов не найдено | Высокорисковый semantic duplicate: определить schema authority по migrations и реальным callers, затем оставить один сервис |
| `tests/test_torgi_tab.py` и `src/ui/components/analytics_v2/test_torgi_tab.py` | Разошедшиеся тесты; pytest настроен только на `tests/`, src-копия не обнаруживается | Перенести недостающие кейсы в `tests/`, удалить src-копию |

### 4.3. Одноимённые, но допустимые модули

Следующие пары не признаны дублями автоматически: `dto`, `projection`,
`scoring`, `queue_repository`, `commercial_routing_v3`, `hydro_daily_sync`,
`v3_analytics_refresh`, `object_card`, `object_detail`, `sidebar`, `header`.
Они принадлежат разным bounded contexts или являются парой CLI → service.

Для них требуется только явное именование импортов. Удаление по совпадению
basename запрещено.

### 4.4. Backup/temporary artifacts

В рабочем кодовом дереве присутствуют:

- `src/services/category_overview_service.py.bak_local_20261009_090128`;
- `src/ui/analytics_contour_v2_page.py.bak_local_20261009_090128`;
- `src/ui/components/analytics_v2/annotation_card.py.bak_local_20261008_103703`;
- `tender_documents_research/document_processor/downloader.py.backup`;
- `tender_documents_research/document_processor/http_client.py.backup`;
- `src/services/computers_service.py.tmp_path_issue/`.

Удаление выполняется отдельно после проверки tracked-state, WIP и наличия
уникальных изменений. Исторические копии в `scratch/` не считаются runtime.

## 5. Стратегия декомпозиции

### Обязательные правила каждой декомпозиции

- один subsystem за фазу;
- сначала characterization/contract tests, затем перенос;
- публичные callable/import paths сохраняются facade-модулем до миграции всех
  потребителей;
- DB SQL, transaction boundaries, cache keys, Streamlit session keys,
  provenance и enum/string contracts не меняются одновременно со split;
- циклические импорты запрещены;
- целевой размер нового модуля — до 300 строк; 300–450 допустимо при цельности;
- файл >450 после фазы требует записанного обоснования;
- после каждой фазы обновляются WIP evidence и этот inventory.

### Предпочтительные seams

| Тип файла | Выделяемые части |
|---|---|
| Worker/runner | config, claim/load, orchestration, model call, persistence, CLI |
| Repository/service | DTO/query builder, reads, writes, policy/domain rules |
| Streamlit page | data loader, state/actions, section renderers, formatting |
| Document parser | format adapters, extraction, normalization, persistence |
| Audit script | query layer, computations, report renderer, CLI |

## 6. Полный inventory файлов >450 строк

### 6.1. Commercial Routing V3 — 15

```text
 944 autonomous_learning_loop.py
 632 candidate_scoring.py
 626 canonical_card.py
 886 document_needs_plan_v2.py
 504 engine.py
 550 learning_observer.py
 574 legacy_okpd_knowledge.py
 711 object_mode_routing.py
 509 opportunity_lifecycle_sync.py
 506 opportunity_persistence.py
 461 projection.py
 952 projection_writer.py
1057 queue_producer.py
 629 research_ui_projection.py
 561 shadow_predictor.py
```

### 6.2. Прочие `src/services` — 23

```text
 882 ai_assessment_runner.py
 731 analytics_command_center.py
 871 analytics_table_workspace_service.py
 465 annotation_queue_service.py
 471 annotation_state_service.py
 463 category_opportunity_service.py
1932 crm_ai_assessment_runner.py
 735 crm_procurements_sync.py
1003 direct_document_extractor.py
 584 expert_annotation_service.py
 609 expert_object_taxonomy.py
 468 medal_semantics_v2.py
 649 object_classification.py
 465 objects_service.py
1090 procurement_card_dossier_service.py
 483 procurement_opportunity_store.py
 471 product_candidate_materializer.py
 790 product_ontology.py
 712 queue_first_service.py
 544 queue_policy_v2a_migration.py
 518 research_queue_priority.py
 568 system_health_probes.py
 520 v3_analytics_okpd.py
```

### 6.3. UI — 12

```text
 714 analytics_contour_v2_page.py
 864 analytics_table_workspace_page.py
 694 category_registry_page.py
 951 components/analytics_v2/annotation_card.py
 638 components/analytics_v2/card_detail.py
 829 components/analytics_v2/card_tabs_ai_expert_form.py
 593 components/analytics_v2/command_center.py
 507 components/analytics_v2/dashboard_header.py
 580 components/analytics_v2/stage_workspace.py
1152 components/analytics_v2/tabs.py
1081 object_detail.py
1006 procurement_card_page.py
```

### 6.4. Document intelligence — 11

```text
 604 backends/queue_repository.py
 812 context_validator.py
 570 context_validator_service.py
 824 daemon.py
 919 downloader.py
 700 eis_rate_limit_store.py
1440 embedded_extraction.py
 599 http_client.py
 604 matcher.py
 650 queue_manager.py
 523 structured_fact_extractor.py
```

### 6.5. Operations/audit scripts — 7

```text
1227 scripts/_phase8_build_audit.py
 513 scripts/_phase9_full_registry_shadow.py
 662 scripts/build_queue_v2_plan.py
 734 scripts/export_procurement_title_repeats.py
 553 scripts/run_second_pass_calibration_v2.py
 641 scripts/run_second_pass_quality_gate.py
 874 scripts/simulate_document_needs_plan_v2.py
```

### 6.6. Tests >450 — 11

```text
841 tests/test_category_opportunity_cards.py
685 tests/test_waterproofing_uk_crm.py
621 tests/test_structured_fact_extractor.py
585 tests/test_dwrr_claim_correction.py
571 tests/test_medal_semantics_v2.py
519 tests/test_object_classification.py
497 tests/test_v3_okpd_product_branch_and_awarded_direct_supply.py
488 tests/test_structured_fact_contract.py
487 tests/test_v3_medal_lineage_and_inference_reliability.py
466 tests/test_crm_sync1.py
457 tests/test_okpd_prior_learning.py
```

## 7. Очередь выполнения

### Phase 0 — inventory and freeze: DONE

- AST/syntax inventory;
- import resolution;
- route/dependency comparison;
- dependency manifests comparison;
- exact/near duplicate scan;
- >450 inventory.

Никаких runtime/DB изменений.

### Phase 1 — correctness before refactoring

1. Решить судьбу `crm_procurements_repository.py` и отсутствующего импорта.
2. Добавить явный dependency для `procurement_card`.
3. Разделить/дополнить dependency profiles.
4. Зафиксировать Python 3.13 execution environment для проверок.
5. Добавить узкую статическую проверку import/route/manifests.

### Phase 2 — duplicate authority cleanup

1. Удалить две exact service-копии после проверки callers.
2. Канонизировать nav/app/Analytics V2.
3. Канонизировать card tabs и вынести pure logic из Streamlit-кода.
4. Разрешить конфликт двух product subcategory services.
5. Слить torgi tests в discoverable `tests/`.
6. Удалить backup artifacts отдельным recoverable commit.

### Phase 3 — critical production files >900

Отдельные child-WIP по одному subsystem:

- `crm_ai_assessment_runner.py`;
- `embedded_extraction.py`;
- `queue_producer.py`;
- `procurement_card_dossier_service.py`;
- `object_detail.py`;
- `procurement_card_page.py`;
- `direct_document_extractor.py`;
- `projection_writer.py`;
- `annotation_card.py`;
- `autonomous_learning_loop.py`;
- `downloader.py`;
- `analytics_v2/tabs.py`;
- `_phase8_build_audit.py` — после runtime-файлов.

### Phase 4 — files 700–900

Разделять по subsystem, начиная с active runtime paths: assessment/table
workspace → routing → document workers → UI → scripts.

### Phase 5 — files 451–699

Группировать только по связанным contracts. Не дробить механически цельные
policy/DTO модули; для оставшихся >450 записывать justification.

### Phase 6 — test decomposition

Разделить 11 крупных тестов по behavior contract, не по внутренним функциям.
Fixtures/builders вынести в `tests/helpers` или `conftest.py` только при
повторном использовании.

### Phase 7 — migration/docs/hygiene closure

- inventory миграций и ownership без DDL;
- удалить/игнорировать временные и backup artifacts;
- обновить overview, README и module maps;
- финальная проверка exact duplicates, imports, routes, manifests и размеров.

## 8. Проверки по фазам

Минимальный набор после каждого изменения:

1. Python 3.13 syntax/import check только изменённых модулей.
2. Targeted tests для изменённого subsystem.
3. Проверка public import paths и отсутствия циклов.
4. Для UI — route/dependency/session-key contract.
5. Для DB-кода — SQL shape/transaction tests без production writes.
6. Для document pipeline — queue state, provenance, completion guard и parser
   contract tests.
7. Для финала — полный test suite только в согласованном Python 3.13
   environment.

Ни одна фаза не включает deploy, production DB writes или systemd actions без
отдельного разрешения и чтения `docs/PROJECT_OPERATING_RULES.md`.

## 9. Итоговые acceptance criteria

- `UNRESOLVED_INTERNAL_IMPORTS=0`;
- `EXACT_DUPLICATE_RUNTIME_GROUPS=0` либо каждое исключение документировано;
- один canonical app/nav/UI authority;
- один canonical product subcategory service/schema authority;
- все runtime imports покрыты dependency profile;
- все handlers имеют явный dependency contract;
- каждый production Python-файл `<=450` строк либо имеет актуальное
  justification;
- целевой размер новых модулей `<=300` строк;
- тесты находятся только в discoverable test roots;
- syntax/import/targeted tests проходят под Python 3.13;
- DB schema, commercial scoring, medals, queue states и provenance не изменены
  неявно;
- README и overview соответствуют фактическим entrypoints.
