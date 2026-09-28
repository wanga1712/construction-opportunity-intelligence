## CURRENT WIP — 2026-09-28

**ANALYTICS-V2-PRODUCTION-MAINTENANCE-1** (Phase 6.3) — `[x]` **PASS / STOP**. Scope: закрыть два доказанных остаточных дефекта после восстановления live-flow (Phase 6.1/6.2), не меняя работающую production-архитектуру.
- **Дефект 1 — Shadow/Qwen на мёртвых закупках.** `crm-v3-shadow-predictor` бесконечно прогонял `PRE_RESEARCH_WAITING` (9 265 строк) через Qwen, включая 9 175 неактуальных legacy-строк бэкфилла `DEEP_RESEARCH` от 2026-08-31 (`created_at` = 2026-08-31), до 3 попыток на строку.
  - Классификация бэклога по канонической authority (`submission_window.is_actionable_submission_window`, `MIN_REMAINING_SUBMISSION_DAYS=2`), без изобретения своего определения активности: `CLOSED_WAITING` 7 429, `NON_TORGI_STAGE` 1 177, `EXPIRED_WINDOW_LT2D` 569, `LIVE_ACTIONABLE` 90 (88 в live-lane `id>=148687`).
  - `QUEUE_PROCUREMENT_ID_AUTHORITY = crm_procurements.id`: 9 265/9 265 совпадений; join по `source_id` даёт лишь 692. Смешивание CRM ID / S7 reestr ID / source ID исключено.
  - `QUEUE_ALLOWED_STATUSES` = `PENDING, PROCESSING, COMPLETED, FAILED, NO_LINKS, PRE_RESEARCH_WAITING` (CHECK не менялся). `SHADOW_ALLOWED_TRANSITIONS` = `PRE_RESEARCH_WAITING → PENDING` (`release_pre_research_queue`, SUCCESS/FAILED) для живой обработки.
  - В `src/services/commercial_routing_v3/shadow_predictor.py` добавлен детерминированный eligibility-gate **перед** model call (`classify_shadow_eligibility`) и детерминированный терминальный skip (`skip_non_actionable_queue_row`) в существующий статус `NO_LINKS` с reason `NON_ACTIONABLE_SKIP:<CLASS>`. Новый статус не вводился, массовый `UPDATE` вслепую не выполнялся, история (`documents`, `evidence`, `crm_v3_model_inference_runs`) не удалялась.
  - PENDING как цель skip-перехода **отвергнут**: doc-claim идёт `ORDER BY lane_rank, priority_score DESC, id ASC`, поэтому сброс 9 175 старых строк в `PENDING` вытеснил бы live-lane. Queue ORDER BY не менялся.
  - Live-приоритет сохранён: `ORDER BY id DESC` по-прежнему берёт свежие строки первыми — за час все 58 Qwen-вызовов ушли в `LIVE_ACTIONABLE`, в `NON_ACTIONABLE` — **0**.
- **Дефект 2 — systemd 203/EXEC.** `crm-v3-analytics-refresh.service` и `crm-objects-index-rebuild.service` (оба `Type=oneshot`) стартовали из несуществующего `/opt/CRM_Streamlit/.venv/bin/python`. Фактический production interpreter — `/opt/CRM_Streamlit/.venv313/bin/python` (Python 3.13.14). Оба unit-файла переведены на `.venv313`, `systemctl daemon-reload`, каждый job выполнен один раз: `ExecMainStatus=0`, `203/EXEC=0`. Фальшивый `.venv` не создавался.
- **Проверки.** `tests/test_phase63_shadow_eligibility_gate.py` — **10 тестов PASS** (граница окна, expired, awarded, closed, non-torgi, commission, missing lifecycle, unknown award status); `py_compile` local+prod OK; md5 prod == local (`7d8e671791ba72b0dc3a932dfe612991`). Control batch: 20 historical строк → `HISTORICAL_CONTROL_SKIPPED=20`, `HISTORICAL_CONTROL_QWEN=0`; детерминированный drain 300 строк за 15 s (0 Qwen-вызовов); 320/320 пропущенных строк подтверждены как неактивные (`wrongly_skipped_actionable=0`).
- **Подтверждение автоматического drain:** когда live-lane опустел (`PRE_RESEARCH_WAITING` с `id>=148687` = 0), `crm-v3-shadow-predictor` сам начал детерминированно пропускать legacy-бэклог (`Skipped non-actionable queue row 147174 (procurement 159652): NON_ACTIONABLE_SUBMISSION_CLOSED`). На момент фиксации: 1 097 пропусков (835 SUBMISSION_CLOSED / 216 NON_TORGI_STAGE / 46 WINDOW_LT2D), `PRE_RESEARCH_WAITING` 9 265 → 8 080, `NO_LINKS` → 2 151, live-lane = 0; Qwen-вызовов по неактивным — по-прежнему 0 (всего 92, все LIVE).
- **Регрессия.** `CRM_SYNC` success (`inserted=725, updated=292167, errors=0`, свежая запись `2026-09-28 12:45:08`), 7 × `tender-docs-daemon*` active, `crm-second-pass-worker` active, `CURRENT_V2_ACTIVE_SECOND_PASS=16`, `crm-streamlit` HTTP 200, `NEW_QUEUE_ROWS_1H=0` при отсутствии новых eligible закупок (`admitted_count=0` в фидере).
- **Frozen Authorities Preserved:** Qwen model, First Pass formula, Second Pass v2 prompt/model, MODEL_MEDAL, category medals, effective medal/time decay, CRM authority hierarchy, queue claim order, S7 OKPD admission — не изменялись (mtime `second_pass_service.py` 2026-09-24, `submission_window.py`/`s13_queue.py` 2026-09-05).
- **Отклонения / неблокирующие дефекты (отдельный maintenance WIP):** `procurement_ai_assessments.completed_at` не заполняется новейшим v2-результатам (9 из 16 текущих активных имеют только `projected_at`) → telemetry authority = `COALESCE(completed_at, projected_at)`; `AVG_SHADOW_SECONDS` не измеряется, т.к. в `crm_v3_model_inference_runs` нет `started_at`/`finished_at`; `max(crm_created_at)` по `crm_procurements` не индексируется и не укладывается в таймаут; noncanonical исторические category-результаты (новых после fix: 0).

**WATERPROOFING-UK-CRM-RUNTIME-1** — `[x]` **PASS**. Scope: поднять модуль гидроизоляции внутри общей CRM на рабочей машине и устранить дефекты, выявленные при первом запуске на живых данных.
- **Окружение:** локальный `.env` (git-ignored) направлен на узел `s7` (`100.80.226.124`), где доступны `nspd_parking`, `crm`, `radar_domrf`, `tender_monitor`; `10.0.0.7` из `../nspd_parking_parser/.env` недоступен, поэтому `PARKING_DB_*` переопределены явно. `CRM_SOURCE_ROOT` / `NSPD_SOURCE_ROOT` указывают на соседние проекты.
- **Запуск:** Streamlit поднят на `http://127.0.0.1:8502`, страница `💧 Гидроизоляция` открывается на экране `🔷 CRM-канбан УК`.
- **Дефект 1 (пустой главный экран):** срез доски по умолчанию был `УК в работе`, поэтому до внесения контуров главный экран показывал пустую доску. Теперь при пустой воронке доска стартует на срезе `Все УК из базы` (`_render_filters(..., has_work=...)`), а после появления контуров возвращается к `УК в работе`.
- **Дефект 2 (неуникальные ключи карточек):** `build_card()` для УК без сохранённого состояния возвращал `key = ""`, из-за чего все карточки доски получали один Streamlit widget-key и доска падала с `There are multiple elements with the same key`. Идентичность контура вынесена в `waterproofing_crm.contour_key()`, `build_card()` выводит ключ из строки БД, `waterproofing_contour.contour_key()` делегирует туда же.
- **Проверки:** `py_compile` и `pyflakes` чисто; `tests/test_waterproofing_uk_crm.py` — **36 тестов PASS** (добавлены `test_build_card_derives_key_from_row_when_state_is_absent`, `test_build_card_keys_stay_unique_across_contour_rows`); live-подключение к БД вернуло 217 УК; Streamlit AppTest подтвердил рендер канбана (100 карточек, 0 исключений), открытие разных карточек УК (6 вложенных секций) и сквозной сценарий «Взять УК из базы в работу» → контур появляется на доске.
- **Frozen Authorities Preserved:** `src/ui/nav.py`, роуты `app_bootstrap.py` / `src/services/app.py`, аналитика V2/V3, S7/S13 transport и AI-контур документов не изменялись.

**WATERPROOFING-UK-CRM-KANBAN-1** — `[x]` **PASS / STOP**. Scope: перевести модуль гидроизоляции из объектного интерфейса в классическую CRM-систему, где главная сущность — управляющая компания (УК), а объекты вложены в карточку УК. Главный экран — канбан УК по 11 этапам воронки продажи; карта объектов понижена до вторичного экрана.
- **Единый источник воронки (`src/services/waterproofing_crm.py`, 293 строки):** `CRM_STAGES` — 11 этапов в порядке, заданном заказчиком; `CLOSED_STAGES = (Отложено / отказ,)`; `STAGE_DEFAULT_ACTIONS` и `STAGE_TOUCH_DAYS` задают следующее действие и каденцию касания для каждого этапа.
  - `normalize_stage()` канонизирует этап и бесшовно мигрирует значения старого объектного контура: `Секретарь / общий телефон найден` → `Секретарь / диспетчер`, `Запрошен начальник эксплуатации` → `Секретарь / диспетчер`, `Контакт эксплуатации получен` → `Найден тех. контакт`, `Первая встреча проведена` → `Встреча назначена`, `Выбран объект для обследования` → `Обследование назначено`, `Сделка / ТКП по объекту` → `КП / техрешение`.
  - `build_card()` собирает карточку УК из строки БД и сохранённого состояния; `kanban_columns()`, `sort_cards()` (просрочка → ближайшее касание → приоритет → название) и `board_kpis()` формируют главный экран.
  - `parse_amount()`/`format_amount()` понимают свободный ввод (`4,2 млн` → `4.2 млн ₽`); `overdue_days()`/`is_overdue()` не считают просрочкой закрытые этапы; приоритет по умолчанию — эвристика по портфелю (`default_priority()`) с ручным переопределением менеджером.
- **Состояние контура (`src/services/waterproofing_contour.py`):** дублирующий список этапов удалён (`CONTOUR_STAGES = CRM_STAGES`); добавлены append-only `merge_contour_state()`, `load_contour_history()`, `latest_contour_state()` поверх `data/waterproofing/contour_states.jsonl`, где каждое касание наследует поля предыдущего и не теряет историю.
- **Главный экран (`src/ui/waterproofing_kanban_tab.py`, 200 строк):** KPI-строка (контуров, объектов, с подземными этажами, с тех. контактом, просрочено, сумма), фильтры (подземные этажи, приоритет, поиск, только просрочка, ответственный) и срез «УК в работе» / «Все УК из базы»; intake-блок «Взять УК из базы в работу»; доска из 11 колонок. Карточка на доске показывает все 12 требуемых полей (название, ИНН/ОГРН, телефон, объектов, объектов с подземными этажами, потенциальная сумма, приоритет Gold/Silver/Bronze, текущий этап, следующее действие, дата касания, наличие тех. контакта, ответственный, признак просрочки) и открывает подробную карточку УК.
- **Карточка УК (`src/ui/waterproofing_uk_tab.py`):** сводка, форма CRM-статуса (этап, следующее действие, дата касания, ответственный, приоритет, потенциальная сумма, тех. контакт, секретарь, комментарий), таблица контактов и вложенные секции (`src/ui/waterproofing_uk_activity.py`): объекты этой УК (карта по тогглу + таблица), история касаний, обследования, КП, документы и AI-рекомендации (`ask_contour_ai` с детерминированным fallback-скриптом звонка).
- **Навигация (`src/ui/waterproofing_page.py`):** первый экран — `🔷 CRM-канбан УК`, карта объектов — второй; `render_pipeline_tab()` (`src/ui/waterproofing_meta_tabs.py`) показывает воронку УК из 11 этапов рядом с портфелями и объектными этапами.
- **Проверки:** `tests/test_waterproofing_uk_crm.py` — 36 тестов PASS (этапы и legacy-алиасы, приоритеты, суммы, даты, просрочка, `build_card`, группировка доски, KPI, персистентность контура через `monkeypatch` на `_STATE_PATH`). Headless smoke-тест Streamlit (канбан + карточка УК) проходит без ошибок; `compileall` и `pyflakes` по изменённым файлам чисто.
- **Отклонения и решения:**
  - `fetch_uk_summary()` в `src/services/map_export.py` дополнен колонкой `ge1_floors` (`COUNT(CASE WHEN co.floors_underground >= 1 THEN 1 END)`) — канбану требуется «количество объектов с подземными этажами».
  - `scripts/production_reconciliation_audit.py`: запись `src/ui/waterproofing_uk_tab.py` в `HOST_LOCAL_FILES` оставлена без изменений. Классификатор описывает дрейф между прод-хостом и canonical Git, а не локальный контент; при рефакторинге не удалено ни одного host/operator-значения. Скрипт — разовый диагностический инструмент и в CI/тестах не используется, поэтому обновление не требуется.
  - Ключ роутинга `waterproofing` (`src/ui/nav.py`) и порядок роутов в `src/ui/app_bootstrap.py` / `src/services/app.py` не изменялись, `tests/test_app_bootstrap_relocation.py` проходит.
- **Frozen Authorities Preserved:** AI-контур документов, S7/S13 transport, Second Pass, очередь и аналитика V2 не затронуты.

**WATERPROOFING-UK-CRM-PROD-DEPLOY-1** — `[x]` **PASS**. Scope: доставить УК-канбан гидроизоляции на основной продовый адрес `http://100.113.185.90:8504/` (S13) вместо локального запуска `127.0.0.1:8502`.
- **Предпроверка дрейфа:** продовое дерево `/opt/CRM_Streamlit` (ветка `CRM-V3-CATEGORY-OPPORTUNITY-CARDS-AND-MULTI-MEDAL-OUTPUT-1`, HEAD `0d40c637`) грязное, история расходится с локальной, поэтому вместо `git push` выполнена точечная доставка файлов; резервные копии заменяемых файлов — `/opt/backups/hydro_uk_crm_20260928/`.
- **Сверка перед заменой:** `git diff --no-index` прод ↔ локально по `waterproofing_contour.py`, `map_export.py`, `waterproofing_meta_tabs.py`, `waterproofing_page.py`, `waterproofing_uk_tab.py` — все расхождения являются правками этого WIP, продовых эксклюзивных изменений нет; `waterproofing_objects_tab.py`, `waterproofing_map_tab.py`, `waterproofing_process.py`, `waterproofing_scoring.py`, `waterproofing_ai_context.py` идентичны.
- **Доставлено (scp):** новые `src/services/waterproofing_crm.py`, `src/ui/waterproofing_kanban_tab.py`, `src/ui/waterproofing_uk_activity.py`, `tests/test_waterproofing_uk_crm.py`; изменённые `src/services/waterproofing_contour.py`, `src/services/map_export.py`, `src/ui/waterproofing_uk_tab.py`, `src/ui/waterproofing_page.py`, `src/ui/waterproofing_meta_tabs.py`.
- **Ссылки проверены:** единственный потребитель `waterproofing_contour` — заменяемый `waterproofing_uk_tab.py`; `render_uk_tab` больше никем не вызывается, роут идёт через `render_waterproofing_page` из `src/ui/app_bootstrap.py` и `src/services/app.py`; `fetch_uk_summary` используется также `src/ui/customers_page.py`, изменение аддитивно (новая колонка `ge1_floors`).
- **Проверки на S13:** `py_compile` продовым `.venv313` — OK; `pytest tests/test_waterproofing_uk_crm.py` — 36 passed; живой прогон на продовой БД: 217 УК, 332 объекта, все в колонке «Контур найден» (сохранённых контуров 0); Streamlit AppTest с продовым `PYTHONPATH=/opt/CRM_Streamlit:/opt/pythonProject89` — канбан отрисован, 100 карточек, открытие карточки УК без исключений, 6 вложенных секций.
- **Перезапуск:** `sudo systemctl restart crm-streamlit.service` → `active`, `http://100.113.185.90:8504/_stcore/health` = `200 / ok`.
- **Наблюдения (вне scope):** пакет `modules` доступен в проде только через `PYTHONPATH` systemd-юнита (`/opt/pythonProject89`), в дереве репозитория его нет. В логах сервиса остаётся ранее существовавшая ошибка другой страницы — `ModuleNotFoundError: src.ui.components.analytics_v2.card_opportunities` (аналитический контур V2, вкладка торгов), к гидроизоляции не относится. Продовые `src/ui/hydro_leads_tab.py` и `src/services/hydro/*` — не подключённый WIP другого направления, доставка их не касалась.
- **Frozen Authorities Preserved:** AI-контур документов, S7/S13 transport, Second Pass, очередь и аналитика V2 не затронуты.

## PRIOR CURRENT WIP — 2026-09-24

**ANALYTICS-V2-SECOND-PASS-PRODUCTION-ROLLOUT-1** (Phase 6) — `[x]` **PASS / STOP**. Scope: transition Second Pass AI and document intelligence into continuous automated production process on Server 13.
- **Authority Hierarchy Implemented:**
  $$\text{EXPERT} > \text{SECOND PASS MODEL} > \text{PRELIMINARY (First Pass)} > \text{UNASSESSED}$$
  - Expert Confirmed (`is_confirmed = TRUE` with `expert_medal`): `BASE_MEDAL = EXPERT_MEDAL`, Authority = `EXPERT`.
  - Second Pass Evaluated (when expert unconfirmed): `BASE_MEDAL = MODEL_MEDAL`, Authority = `SECOND_PASS_MODEL`.
  - Preliminary (First Pass fallback): `BASE_MEDAL = PRELIMINARY_MEDAL`, Authority = `PRELIMINARY`.
  - Unassessed: `BASE_MEDAL = UNASSESSED`, Authority = `UNASSESSED`.
- **Dynamic Effective Medal:** Applied frozen deadline time-decay schedule to `BASE_MEDAL` ($>14$d: 0, $8..14$d: -1, $4..7$d: -2, $2..3$d: -3, $0..<2$d: WOOD, $<0$d: CLOSED).
- **Continuous Daemon on S13:**
  - Script: `/opt/CRM_Streamlit/scripts/run_second_pass_worker.py` with `QWEN_WORKERS=1` sequential inference.
  - Systemd Service: `crm-second-pass-worker.service` enabled and active (`Loaded: loaded; enabled; preset: enabled; Active: active (running)`). Automatically starts on S13 boot.
  - Automated trigger: completed document download/extraction + `evidence_count > 0` and unassessed Second Pass.
  - Duplicate guard: prompt hash fingerprinting prevents duplicate inferences.
- **CRM UI Presentation:**
  - 3-tier assessment badges in card summary: `⚡ Сейчас: [EFFECTIVE_MEDAL] (decay -X)`, `🎯 Базовая: [BASE_MEDAL] (AUTHORITY)`, `🤖 По документам: [MODEL_MEDAL]`, `⚡ Предварительно: [PRELIMINARY_MEDAL]`, `✓ Эксперт: [STATUS]`.
  - Category findings expander in card: displays all 14 canonical categories (`category_evaluations`) and extracted materials/quantities (`found_facts`).
  - Distinct filters in `torgi_filters.py`: `effective_medal`, `model_medal`, `preliminary_medal`, `expert_status`, `object_family`, search, hide expired.
- **Live Verification on S13:**
  - 20 unit tests PASS on local and S13 (`tests/test_effective_medal_authority.py`, `tests/test_effective_medal_time_decay.py`, `tests/test_torgi_priority_sorting.py`, `tests/test_second_pass_service.py`).
  - Acceptance script verified 554 active cards: `AUTHORITY_BREAKDOWN`: `PRELIMINARY: 221`, `SECOND_PASS_MODEL: 4+ (growing)`, `UNASSESSED: 329`.
  - Streamlit UI healthy (HTTP 200 on port 8504).
  - Ollama Qwen 2.5:7b stable (GPU VRAM 4,648 MiB / 6,144 MiB, 75%).
- **Frozen Authorities Preserved:** First Pass scoring formula, OKPD priors, queue ordering, time-decay table, document pipeline, S7 transport, and expert annotations 100% immutable (`EXPERT_FIELDS_MUTATED = NO`).

## PRIOR CURRENT WIP — 2026-09-24

**ANALYTICS-V2-SECOND-PASS-CATEGORY-SEMANTICS-1** (Phase 5.3) — `[x]` **PASS / STOP**. Scope: eliminate proven semantic false positives, enforce strict category semantic guardrails across all 14 canonical categories (`_CATEGORY_SEMANTIC_PATTERNS`), implement deterministic Commercial Scope Guard for non-construction commodities, and re-evaluate exact 24 regression batch + 5 negative controls + 2 special cases on S13.

- **Problem 1 Resolution (`CRM_ID=165114`):** Eliminated flooring false positive from *"Обратная засыпка"*. `flooring` downgraded to `WOOD` (Score 20); `waterproofing` confirmed at `SILVER` (Score 85) with validated fact *"полимерная гидроизоляция"*.
- **Problem 2 Resolution (`CRM_ID=40983`):** Eliminated waterproofing false positive from mineral wool thermal insulation (*"маты минераловатные"*). `waterproofing` downgraded to `WOOD` (Score 20); overall tender downgraded to `WOOD` (Score 40).
- **Out-of-Scope Negative Controls (`163861`, `163870`, `163872`, `121216`):** Commercial Scope Guard confirmed 0 positive canonical construction categories and strictly clamped overall medals to `WOOD` (Score 40).
- **Regression Batch Proof Metrics ($N=24$):**
  - `UNSUPPORTED_FINDINGS = 0` (14 supported, 0 unsupported).
  - `FINDINGS_WITH_SOURCE_TRACE = 14/14 (100%)`, `FINDINGS_WITHOUT_SOURCE_TRACE = 0`.
  - `CATEGORY_GOLD_WEAK_EVIDENCE = 0`.
  - `CATEGORY_POSITIVE_MEDAL_WITHOUT_EVIDENCE = 0`.
  - `POSITIVE_CATEGORY_RESULTS_WITHOUT_TRACE = 0`.
  - Overall == Strongest Category Alignment: 19/24 (**79.2%**, 5 conflicts analyzed).
- **Frozen Authorities Preserved:** All models (`qwen2.5:7b`), First Pass scoring, CRM sorting, queue claim order, and document downloader untouched. STOP after Phase 5.3.

## PRIOR CURRENT WIP — 2026-09-24

**ANALYTICS-V2-SECOND-PASS-CALIBRATION-1** (Phase 5.2) — `[x]` **PASS / STOP**. Scope: tighten Second Pass evidence contract and prompt (`v3_second_pass_evidence_7b_v2`), enforce canonical category taxonomy from `crm_product_categories` (14 active categories), separate discrete `found_facts` from `category_evaluations`, enforce `category_model_medal`, `category_model_score`, `category_reason`, `category_evidence_refs`, prove zero unsupported findings (`UNSUPPORTED_FINDINGS = 0`), and evaluate category alignment across regression batch ($N=24$), negative controls ($N=5$), and special audit cases ($N=2$).
- **Forensic Diagnosis of Phase 5.1 Unsupported Findings ($N=6$):**
  1. `CRM_ID=127854`: empty product name `""` from administrative notice $\to$ `PROMPT_TOO_PERMISSIVE` + `MODEL_GENERALIZATION`.
  2. `CRM_ID=83383`: empty product name `""` from road description $\to$ `PROMPT_TOO_PERMISSIVE` + `MODEL_GENERALIZATION`.
  3. `CRM_ID=9441`: `"Грунтовочный состав"` from nested dictionary formatting $\to$ `EVIDENCE_SELECTOR_ERROR` / `PARSER_NORMALIZATION`.
  4. `CRM_ID=40983`: `"вытяжные вентиляционные шахты"` hallucinated from water piping snippet $\to$ `MODEL_GENERALIZATION`.
  5. `CRM_ID=22679`: `"оконные заполнения"` with quote `"толщина 2 мм"` from tender title $\to$ `MODEL_GENERALIZATION` / `PROMPT_TOO_PERMISSIVE`.
  6. `CRM_ID=163638`: `"акрилат"` from dictionary snippet header $\to$ `PROMPT_TOO_PERMISSIVE`.
- **Implemented Service & Prompt Upgrades (`v3_second_pass_evidence_7b_v2`):**
  - Canonical taxonomy grounding: 14 canonical categories (`lighting`, `waterproofing`, `flooring`, `composites`, `computers`, `drainage_water_management`, `structural_reinforcement`, `composite_structures`, `bridge_road_infrastructure`, `external_utility_networks`, `concrete_materials`, `cable_support_systems`, `waterproofing_concrete_repair`, `curbstone`).
  - Added strict evidence corpus grounding in `parse_second_pass_json()` and `normalize_category_code()`.
  - Enforced strict category invariants: `CATEGORY_POSITIVE_MEDAL_WITHOUT_EVIDENCE = 0`, `CATEGORY_GOLD_WEAK_EVIDENCE = 0`, `POSITIVE_CATEGORY_RESULTS_WITHOUT_TRACE = 0`.
- **Regression Batch Results on Exact 24 Procurements:**
  - `UNSUPPORTED_FINDINGS = 0` (15 supported, 0 unsupported — 100% reduction in unsupported findings).
  - `FINDINGS_WITH_SOURCE_TRACE = 15/15` (100%), `FINDINGS_WITHOUT_SOURCE_TRACE = 0`.
  - `CATEGORY_GOLD_WEAK_EVIDENCE = 0`.
  - `CATEGORY_POSITIVE_MEDAL_WITHOUT_EVIDENCE = 0`.
  - `POSITIVE_CATEGORY_RESULTS_WITHOUT_TRACE = 0`.
  - Category Alignment: 16/24 exact match between `OVERALL_MODEL_MEDAL` and `STRONGEST_CATEGORY_MEDAL` (66.7%), 8 conflicts analyzed.
- **Frozen Authorities Preserved:** All models, First Pass scoring, CRM sorting, queue claim order, and document downloader untouched. STOP after Phase 5.2.

## PRIOR CURRENT WIP — 2026-09-22

**ANALYTICS-V2-SECOND-PASS-QUALITY-GATE-1** (Phase 5.1) — `[x]` **PASS (AUDIT) / RECOMMENDATION: SECOND_PASS_CALIBRATION_REQUIRED**. Scope: comprehensive diagnostic quality and evidence validation of Second Pass AI on S13 without code, prompt, or schema modifications (`MODE=READ_ONLY+BOUNDED_INFERENCE`).
- **Forensic Case Audits:**
  - `CRM_ID=165114` (№ 32515285171, 223-FZ): Qwen correctly excluded administrative boilerplate (*"Требования к участникам"*, *"Наименование Заказчика"*) under `commercial_exclusions`, while generating 2 confirmed `found_facts` from civil engineering estimate items (*"Обратная засыпка"*, $2,320.21\text{ m}^3$ at $1,435.89\text{ руб}$ and $1,507.10\text{ m}^3$ at $1,562.54\text{ руб}$) supporting `MODEL_MEDAL = GOLD` (Score 89).
  - `CRM_ID=78763` (№ 0134200000124004928, 44-FZ): Operational road maintenance contract produced 0 line-item product facts in `found_facts` (ongoing continuous maintenance rather than discrete BOM), but generated 7 valid `evidence_refs` supporting `lighting`, `flooring`, and `drainage_water_management` relevance (`MODEL_MEDAL = SILVER`, Score 60).
- **Stratified Control Batch ($N=24$):** Evaluated across 24 procurements (6 GOLD, 6 SILVER, 6 BRONZE, 3 WOOD, 3 UNASSESSED) covering 44-FZ / 223-FZ and multiple object families:
  - Model Output: `GOLD = 5`, `SILVER = 5`, `BRONZE = 9`, `WOOD = 5`.
  - Preliminary $\to$ Model Transitions: Prelim GOLD $\to$ 0 G, 2 S, 1 B, 3 W (successfully demoted when documents showed administrative/software text); Prelim BRONZE $\to$ 2 G, 1 S, 2 B, 1 W (promoted when estimates contained large piping/waterproofing scopes).
- **Negative / WOOD Controls ($N=5$):** 4/5 assigned BRONZE/WOOD (`MODEL_OVERPOSITIVE = NO`).
- **Quality Gates:** `GOLD_WITH_STRONG_EVIDENCE = 5/5` (0 weak GOLD), `FINDINGS_WITH_SOURCE_TRACE = 29/29` (100%), `SUPPORTED_FINDINGS = 23/29`, `UNSUPPORTED_FINDINGS = 6/29` (due to generalized naming in table rows), `POSSIBLE_MEMORY_LEAK = NO` (RAM reclaimed to 7,547 MiB). Latency: average $67.07\text{s}$, P90 $84.76\text{s}$.
- **Frozen Authorities Preserved:** All models, prompts, CRM sorting, queue claim order, and First Pass untouched. STOP after Phase 5.1.

## PRIOR CURRENT WIP — 2026-09-22

**ANALYTICS-V2-SECOND-PASS-AI-1** (Phase 5) — `[x]` **PASS / STOP**. Scope: create true Second Pass AI evaluation utilizing extracted document evidence and text content (`document_match_details`, `document_files`), Qwen 2.5:7b (`prompt_version = 'v3_second_pass_evidence_7b_v1'`), structured fact extraction and commercial exclusions, model medal assignment (`GOLD`, `SILVER`, `BRONZE`, `WOOD`), database persistence (`crm_v3_model_inference_runs`, `procurement_ai_assessments`, `crm_v3_product_findings`), and strict expert annotation immutability (`EXPERT_FIELDS_MUTATED = NO`).
- **Implemented Service:** `src/services/second_pass_service.py` (345 lines):
  - `extract_evidence_snippets()`: extracts top 15 high-scoring unique evidence snippets with product names, quantities, and prices from `document_intelligence`.
  - `build_second_pass_prompt()`: constructs evidence-grounded structured prompt for Qwen 2.5:7b.
  - `parse_second_pass_json()`: robust parsing with JSON recovery and schema validation.
  - `persist_second_pass()`: persists full prompt/response to `crm_v3_model_inference_runs`, creates versioned record in `procurement_ai_assessments`, and registers extracted product facts in `crm_v3_product_findings`.
- **Automated Tests:** `tests/test_second_pass_service.py` (3/3 unit tests PASS on local and S13).
- **Production Acceptance Gates Verified on S13:**
  - Gate 1 (1 Procurement E2E Trace): Control procurement `165114` (№ `32515285171`, 223-FZ) with 20 files and 2,452 evidence details evaluated to `MODEL_MEDAL = GOLD`, `model_score = 89`, 2 found facts, 3 evidence references; run ID 2722 persisted; expert annotations unmutated (`EXPERT_FIELDS_MUTATED = NO`).
  - Gate 2 (20-Procurement Controlled Batch): 20/20 procurements processed with 0 AI errors, 0 DB errors (`GOLD = 7`, `SILVER = 9`, `BRONZE = 4`, `WOOD = 0`). Mean latency $134.33\text{s}$, P50 $134.26\text{s}$, P90 $187.47\text{s}$; average tokens input $2482.7$, output $648.1$; GPU VRAM stable at 4,668 MiB / 6,144 MiB.
- **Frozen Authorities Preserved:** First Pass scoring formula, medal calibration, effective medal time decay, CRM sorting/filters, S7/stunnel, document pipeline, and worker claim order 100% untouched. STOP after Phase 5.

## PRIOR CURRENT WIP — 2026-09-22

**ANALYTICS-V2-DOCUMENT-PIPELINE-RESTORE-1** (Phase 4) — `[x]` **PASS / STOP**. Scope: restore complete technical document pipeline health on S13 (`document_processing_queue` $\to$ claim $\to$ EIS HTTPS download $\to$ local staging $\to$ deduplication $\to$ DB registration $\to$ processing $\to$ evidence $\to$ `COMPLETED`).
- **Forensic Diagnosis of Previous Failures:** Analyzed 1,750 failed queue tasks on S13:
  1. 80.8% (1,415 failures): `uq_canonical_source_file_gen` unique constraint violation on `document_files` when extracted child archive files inherited the parent archive's `canonical_source_document_id`.
  2. 13.2% (232 failures): `document_files_download_status_check` constraint violation when parser status `'UNSUPPORTED'` (for `.xls` files) was assigned to `document_files.download_status` (which only allows `PENDING, COMPLETED, FAILED, SKIPPED`).
- **Implemented Bounded Pipeline Fixes:**
  - `tender_documents_research/document_processor/downloader.py`: explicitly set `canonical_source_document_id=None` for extracted child files from archives.
  - `tender_documents_research/document_processor/backends/state_repository.py`: defensively nullified `canonical_source_document_id` if already claimed by another `url_hash`.
  - `tender_documents_research/document_processor/backends/s13_persistence.py`: cleanly mapped document parser results to valid `download_status` (`COMPLETED` for unsupported parsed formats).
- **Automated Tests:** Added 3 regression unit tests in `tests/test_document_pipeline_dedup_and_status.py` (3/3 PASS on local and S13).
- **Production Acceptance Gates Verified on S13:**
  - Gate 1 (1 Procurement E2E): Task 120677 (Procurement 131313 with nested RAR archives) processed end-to-end to `COMPLETED` with 4 document files and 2 matches registered.
  - Gate 2 (20-Procurement Controlled Batch): 20/20 procurements processed to `COMPLETED` with 0 failures and 0 DB errors.
  - Gate 3 (Bounded Worker Run $\ge 50$ Tasks): Continuous daemon run processed 51 procurements with 100% success rate (`tasks_completed = 51`, `tasks_failed = 0`, `total_files = 329`, `files_downloaded = 328`, `total_results = 313`, `total_matches = 3389`).
- **Frozen Authorities Preserved:** First Pass scoring, medal calibration, time decay, CRM sort/filters, S7/stunnel transport, and claim order untouched. No Second Pass model/Qwen expansion. Service active and healthy (`tender-docs-daemon-open.service` active, PID 127160). STOP after Phase 4.

## PRIOR CURRENT WIP — 2026-09-22

**ANALYTICS-V2-EFFECTIVE-MEDAL-TIME-DECAY-1** (Phase 3.2) — `[x]` **PASS / STOP**. Scope: implement dynamic commercial opportunity rating (`effective_medal`, `effective_medal_rank`, `deadline_decay_steps`, `days_to_deadline`) with time decay based on submission deadline, while keeping source medals (`preliminary_medal`, `expert_medal`, `candidate_medal`) 100% immutable.
- **Base Medal Authority:** if expert confirmed (`is_confirmed = TRUE` with `expert_medal`), `base_medal = expert_medal` (authority: EXPERT); else `base_medal = preliminary_medal` (authority: PRELIMINARY).
- **Time Decay Schedule:** $>14$d $\to$ 0 decay steps; $8..14$d $\to$ 1 step; $4..7$d $\to$ 2 steps; $2..3$d $\to$ 3 steps; $0..<2$d $\to$ WOOD (forced); $<0$d $\to$ CLOSED. Downgrades follow GOLD $\to$ SILVER $\to$ BRONZE $\to$ WOOD (never below WOOD).
- **CRM Priority Sort:** Active non-expired first $\to$ `effective_medal` rank (GOLD $\to$ SILVER $\to$ BRONZE $\to$ WOOD $\to$ UNASSESSED $\to$ CLOSED) $\to$ `is_confirmed` tie-breaker $\to$ `priority_score DESC` $\to$ `end_date ASC NULLS LAST` $\to$ `initial_price DESC` $\to$ `id DESC`.
- **UI Card Badges & Filters:** Added primary badge `Сейчас: [EFFECTIVE_MEDAL]` (with decay steps info) and secondary badges `Базовая: [BASE_MEDAL]`, `Эксперт: [STATUS]`; separated effective medal filter pills and base medal filter.
- **Verification on S13:** All 7 unit tests PASS in `tests/test_effective_medal_time_decay.py`. Acceptance script `scripts/verify_effective_medal_acceptance.py` verified on 982 active actionable tenders: Base Medals: GOLD 36, SILVER 14, BRONZE 282, WOOD 3, UNASSESSED 647; Effective Medals: GOLD 3, SILVER 4, BRONZE 43, WOOD 285, UNASSESSED 647. Top 50 cards: `TOP50_EXPIRED = 0`, strictly monotonic effective medal rank (GOLD 3, SILVER 4, BRONZE 43). Source medals immutable. `crm-streamlit.service` active and healthy (HTTP 200 on port 8504). STOP after Phase 3.2; next phase: `PHASE_4_DOCUMENT_PIPELINE_RESTORE`.

## PRIOR CURRENT WIP — 2026-09-22

**ANALYTICS-V2-CRM-SORT-FILTER-CONSISTENCY-1** (Phase 3.1) — `[x]` **PASS / STOP**. Scope: resolve sort and filter authority contradictions in Analytics Contour V2 «Идут торги». Unified workset evaluation under single authority (`FirstPassService` + `source_contour` + expert annotations) with in-memory caching and deterministic sorting. Proved exact reconciliation across all dimensions on 982 active actionable tenders: `TIER_ORDER_VIOLATIONS = 0` (Top 50 strictly monotonic), `TOP50_EXPIRED = 0`. Filters match DB aggregations with 100% exact equality: Gold (36/36), Silver (14/14), Bronze (282/282), Wood (3/3), Unassessed (647/647), Social (122/122), Commercial (291/291), Direct Supply (222/222), Other (347/347), 44-FZ (633/633), 223-FZ (349/349), 615-PP (0/0). Reconciled 982 visible count from 2,419 non-expired (`actionable_submission_sql` requires `end_date >= CURRENT_DATE + 2 days`, filtering 1,437 tenders with $<2$ days). All unit tests PASS (13/13). S13 service active and healthy (`crm-streamlit` HTTP 200 on port 8504). STOP after Phase 3.1; next phase: `PHASE_4_DOCUMENT_PIPELINE_RESTORE`.

## PRIOR CURRENT WIP — 2026-09-22

**ANALYTICS-V2-CRM-PRIORITY-FILTERS-1** (Phase 3) — `[x]` **PASS / STOP**. Scope: implement tiered priority sorting and multidimensional filtering in Analytics Contour V2 «Идут торги». Pushed 4-tier default hierarchy into SQL `ORDER BY` before `LIMIT/OFFSET` pagination: Tier 1 (Expert Confirmed `is_confirmed = TRUE` by `expert_medal` GOLD $\to$ SILVER $\to$ BRONZE $\to$ WOOD), Tier 2 (First Pass Preliminary by `preliminary_medal` GOLD $\to$ SILVER $\to$ BRONZE $\to$ WOOD $\to$ UNASSESSED), Tier 3 (Unassessed / Low Priority), Tier 4 (Expired / Closed-Waiting `award_status = 'submission_closed_waiting_award'` or `end_date < NOW()` sunk to the bottom). Secondary sort within tier: `priority_score DESC` $\to$ `end_date ASC NULLS LAST` $\to$ `initial_price DESC` $\to$ `id DESC`. Implemented filter toolbar (`torgi_filters.py` 72 lines) supporting Preliminary Medal, Expert Status, Object Family (Social, Commercial, Direct Supply), Region, Search Query, and Hide Expired toggle (default True). Extracted SQL workset logic into `src/services/torgi_workset_service.py` (263 lines, $\le 300$). Enhanced card badges to separate Preliminary Medal and Expert Badge, with safe deadline countdown (`fmt_deadline_countdown`, zero negative days). Audited Top 50 default view on S13: `TOP50_EXPIRED = 0` (100% active non-expired tenders), 1 Tier 1, 8 Tier 2, 41 Tier 3, 0 Tier 4; query latency 84.85 ms ($< 500\text{ ms}$). All 16 unit tests PASS on local and S13 (`tests/test_torgi_priority_sorting.py` 7/7 PASS, `tests/test_first_pass_service.py` 9/9 PASS). Service active and healthy (`crm-streamlit` HTTP 200 on port 8504). STOP after Phase 3; do not start Phase 4 without explicit user request.

## PRIOR CURRENT WIP — 2026-09-21

**ANALYTICS-V2-ACTIVE-QUEUE-HYGIENE-1** (Phase 2.2) — `[x]` **PASS / STOP**. Scope: audit active queue expiry distribution, prove why average priority score was 3.88 (25,760 expired active queue rows evaluated with `priority_score = 0` vs 2,186 non-expired rows with mean `49.89`), reconcile stale `crm_stage = 'torgi'` and `award_status = 'submission_open'` rows to `submission_closed_waiting_award` using existing canonical authority in `src/services/commercial_routing_v3/source_lifecycle.py`. Proven root cause: S7 sync retains `crm_stage = 'torgi'` until S7 scraper observes commission/award, but `source_lifecycle.py` maps `end_date < today` to `WAITING_SOURCE_OUTCOME` (`award_status = 'submission_closed_waiting_award'`). Executed bounded reconciliation on S13: updated 1,377 expired `submission_open` rows to `submission_closed_waiting_award` (`SUBMISSION_OPEN_EXPIRED = 0`). Non-expired active queue tasks remain 100% intact and prioritized ahead of expired rows (`ORDER BY priority_score DESC`). Worker claim SQL and First Pass scoring formula 100% untouched. Services verified active (`crm-streamlit` HTTP 200, `tender-docs-daemon-open` active). STOP after Phase 2.2; next phase: `PHASE_3_CRM_PRIORITY_AND_FILTERS`.

## PRIOR CURRENT WIP — 2026-09-21

**ANALYTICS-V2-FIRST-PASS-CALIBRATION-1** (Phase 2.1) — `[x]` **PASS / STOP**. Scope: eliminate OKPD Prior blanket GOLD fallback, eliminate double-counting of relevance bonus (+10), restore taxonomy projection (SOCIAL, COMMERCIAL, DIRECT_SUPPLY, OTHER), and zero out priority scores for expired active procurements (`submission_end_at < NOW()`). Calibrated discrete OKPD prior weights (`>=80` GOLD, `70..79` SILVER, `40..69` BRONZE, `<40` WOOD) from `crm_category_okpd_priors` and marked source authority as `CATEGORY_OKPD_PRIOR`. Enforced strict independence of relevance bonus (+10 strictly requires independent commercial relevance, `prior_weight >= 80` alone yields `relevance_bonus = 0`). Restored taxonomy-first mapping for `SOCIAL` and `COMMERCIAL` objects, reducing `DIRECT_SUPPLY` share in Top-100 from >80% to 11.00%. Verified all invariants and safety gate (`CANONICAL_GOLD_PERCENT = 16.76% <= 60%`, `DOUBLE_COUNTING_CHECK = PASS`, 9/9 unit tests PASS). Executed production backfill on S13 across 28,109 active queue rows (`document_processing_queue` average score: 3.88; GOLD 4,711, SILVER 2,815, BRONZE 20,356, WOOD 212, UNASSESSED 15). Worker claim SQL untouched. Service active and healthy (HTTP 200 on port 8504). STOP after Phase 2.1; do not start next phase without explicit user request.

## PRIOR CURRENT WIP — 2026-09-14

**CRM-ANALYTICS-V2-DOCUMENT-CATALOG-RESTORATION-1** — `[x]` **PASS / STOP**. Scope: restore full authoritative document catalog in Analytics Contour V2 procurement cards. Identified root cause: `crm_procurements.file_count` column in PostgreSQL was stale/0 for ~99% of procurements, causing the card pill tab to display `Документы · 0` even when tenders had rich documentation. Added `enrich_cards_document_counts()` with `@st.cache_data(ttl=300)` and `filter_unresearchable=False` support in `src/services/commercial_routing_v3/document_links.py`. Integrated batch document count enrichment into `tabs.py` (`_render_torgi_tab`, `_render_komissia_tab`, `_render_razygranye_tab`). Preserved original document resolution order in `src/services/annotation_card_view.py` (`test_annotation_card_view.py` 7/7 PASS). Verified all 5 baseline cards + zero control case on S13: PID 208653 (№ 32616216109, 223-FZ) counter=6 & catalog=6; PID 101879 (№ 32616050792, 223-FZ) counter=1 & catalog=1; PID 568 (№ 32615825485, 223-FZ) counter=1 & catalog=1; PID 41813 (№ 32615912264, 223-FZ) counter=63 & catalog=63; PID 46550 (№ 0872400001326000095, 44-FZ) counter=7 & catalog=7; Zero case counter=0 with clear prompt. Service active and healthy (HTTP 200 on port 8504). Hard guardrails preserved (`HEADER_BLOCKING_CARDS=NO`, `QWEN_STARTED=NO`, `DOCUMENT_BULK_DOWNLOAD_STARTED=NO`, `MODEL_TRAINING_STARTED=NO`). STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-09

**CRM-ANALYTICS-V2-DASHBOARD-COMPACT-VISUAL-REDESIGN-1** — `[x]` **PASS / STOP**. Scope: visual redesign of Analytics Contour V2 dashboard header (`src/ui/components/analytics_v2/dashboard_header.py`). Introduced bounded content width (1220px max, centered), compact KPI cards (minmax(180px, 1fr) width, 82px height), horizontal process strip for document pipeline with subtle separators, 3 compact commercial assessment cards (SAME, DOWN, UP), removed 100% stacked medal bar chart from main screen, moved detailed non-zero transitions and 4x4 matrix under collapsed expanders. Total header height reduced to ~420px. Unit tests: 110 passed (8 new compact tests in `tests/test_analytics_dashboard_compact_redesign.py` + 102 existing tests). Commits: `7a75734`. All hard gates respected (`KPI_SQL_CHANGED=NO`, `KPI_SEMANTICS_CHANGED=NO`, `MODEL_CHANGED=NO`, `PARSER_CHANGED=NO`, `QUEUE_CHANGED=NO`, `DB_MUTATED=NO`, `CARD_WORKSPACE_CHANGED=NO`). STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-08

**S13-V4-BATCH-10-CORRECTION-1** — `[~]` **IN PROGRESS**. Scope: forensic classification of failed controlled batch rows; deterministic archive-child identity and DB rollback safety; DWRR PostgreSQL claim correction. No admission, Stage1, downloader network logic, parser, V4 semantics, schema, S7, or batch-20 changes.

Живой документ проекта. Он является источником истины для последовательности рефакторинга и фактически выполненных работ.

## Правила ведения

- Статусы: `[ ]` не начато, `[~]` выполняется, `[x]` выполнено, `[!]` заблокировано.
- За один цикл выполняется только один этап.
- Пункт отмечается выполненным только после проверки.
- Перед началом следующего этапа требуется явное решение пользователя.
- Размер рабочего Python-модуля: до 300 строк — желательно; 300–450 допустимо при цельности; свыше 450 требуется записанное объяснение или декомпозиция.
- Изменение поведения сначала фиксируется тестом или явно записанным ожидаемым результатом.

## CURRENT WIP — 2026-09-06

**CRM-V3-STRUCTURED-FACT-FINAL-TRUST-AND-PRODUCT-IDENTITY-PROOF-1** — `[x]` **PASS / STOP**. Scope: `REMOVE_MATCH_TERM_MATERIAL_FALLBACK`, `TRUST_PROMOTION_ACCOUNTING`, `CANARY_REPRODUCIBILITY`, `QUALITY_DENOMINATOR_PROOF`, `VALUE_SOURCE_EVIDENCE_PROOF`. Refactored `CategoryOpportunityService._build_opportunity()` to derive product identity strictly from `product_name_raw or product_name_normalized` without `matched_term` fallback (`MATCH_TERM_USED_AS_PRODUCT_NAME = 0`, `TRUSTED_ENTITY_WITHOUT_PRODUCT_NAME_DISPLAYED = 0`). Enforced strict `has_valid_product_identity` for numeric bindings (material, quantity, unit price, total price). Committed reproducible canonical canary script `scripts/run_structured_fact_canary.py`. Audited trust state accounting across 60 extraction runs and 14 entities on S13 (`TRUSTED_PRODUCTION=14`, `DEV_EXPOSED=0`, `MANUAL_PROOF_QUARANTINE=5`, `QUALITY_REJECTED=0`, `OTHER=0`, `SUM_CANARY_TRUST_STATES=14`). Achieved 100% precision with exact denominators (`PRODUCT_ENTITY_PRECISION=1.0000`, `DISPLAYED_PRODUCT_PRECISION=1.0000`, `QUANTITY_PRECISION=1.0000`, `UNIT_PRICE_PRECISION=1.0000`, `TOTAL_PRICE_PRECISION=1.0000`, `VALUE_WITHOUT_SOURCE_EVIDENCE=0`). Added 6 regression tests (tests 34-39) to `tests/test_category_opportunity_cards.py`. Unit test suite 59/59 PASS on local and S13 server. STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-STRUCTURED-FACT-GIT-RECONCILIATION-AND-REAL-CANARY-COMPLETION-1** — `[x]` **PASS / STOP**. Scope: `EXACT_RUNTIME_GIT_RECONCILIATION`, `RECOVER_FUNCTIONAL_IMPLEMENTATION`, `CANONICAL_MIGRATION_PROOF`, `REAL_EXTRACTOR_CANARY_EXPANSION`, `PRODUCT_ENTITY_QUALITY_GATE`, `DISPLAYED_PRODUCT_QUALITY_GATE`, `PRODUCT_BOUND_NUMERIC_QUALITY`, `SEARCH_PHRASE_VS_MATERIAL_PROOF`, `TRUSTED_ENTITY_JOIN_ACCOUNTING`. Audited git commit history (`583fe9b` non-existent on local/S13/remote; consolidated all functional code into canonical git commits). Created canonical DDL migration `migrations/002_add_structured_fact_trust_state.sql`. Refactored `CategoryOpportunityService` to enforce strict `s.structured_fact_trust_state = 'TRUSTED_PRODUCTION'` in SQL JOIN without `COALESCE` fallbacks (`NULL_IS_TRUSTED=NO`). Separated search detail match terms from material product entities (`SEARCH_PHRASE_AS_MATERIAL = 0`). Accounted for trusted entity joins on S13 (`TRUSTED_TOTAL=10`, `JOINED=10`, `NOT_JOINED=0`). Executed expanded real extractor canary on $N=60$ unexposed V4 CONFIRMED details (`CANARY_RUNS_CREATED=60`, `CANARY_ENTITIES_CREATED=14`, `LIVE_POSITIVE_FACTS=14`, `LIVE_NEGATIVE_FACTS=46`, `MANUAL_INSERTS_IN_CANARY=0`). Achieved 100% precision across all quality gates (`PRODUCT_ENTITY_PRECISION=1.0000`, `DISPLAYED_PRODUCT_PRECISION=1.0000`, `PRODUCT_BOUND_QUANTITY_PRECISION=1.0000`, `UNIT_PRICE_PRECISION=1.0000`, `TOTAL_PRICE_PRECISION=1.0000`). Executed live card proof on 10 procurements across 15 cards (`LIVE_CARD_PROCUREMENTS=10`, `SEARCH_PHRASE_AS_MATERIAL=0`). Test suite 53/53 PASS on local and S13 server. STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-STRUCTURED-FACT-TRUST-GATE-CORRECTION-AND-REAL-EXTRACTOR-CANARY-1** — `[x]` **PASS / STOP**. Scope: `R4C_STATUS_CORRECTION`, `CANONICAL_TRUST_MIGRATION`, `STRICT_FAIL_CLOSED_TRUST`, `PRODUCT_ENTITY_AUTHORITY_CORRECTION`, `MATCH_TERM_VS_PRODUCT_ENTITY_SEPARATION`, `NUMERIC_SUBJECT_BINDING`, `MANUAL_PROOF_QUARANTINE`, `REAL_STRUCTURED_EXTRACTOR_CANARY`, `REAL_SOURCE_PROVENANCE_VALIDATION`, `CATEGORY_CARD_TRUST_CUTOVER`. Executed canonical trust migration on S13 (`DEV_EXPOSED`=296, `MANUAL_PROOF_QUARANTINE`=5, `TRUSTED_PRODUCTION`=10). Enforced strict fail-closed join in `CategoryOpportunityService` (`UNTRUSTED_JOIN_ATTEMPTS=0`, `DEV_EXPOSED_JOINED=0`, `MANUAL_PROOF_QUARANTINE_JOINED=0`). Separated search detail match terms from product entities. Executed real `StructuredFactExtractor` canary with `save_extraction_run` on 15 unexposed V4 CONFIRMED details (`CANARY_RUNS_CREATED=15`, `CANARY_ENTITIES_CREATED=10`, `QUOTE_VERIFICATION_FAILURES=0`). Achieved 100% real source provenance cutover. Test suite 52/52 PASS on local and S13 server. Remote HEAD matches (`583fe9b`). STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-STRUCTURED-FACT-FRESH-QUALITY-GATE-AND-CARD-VOLUME-PROOF-1** — `[x]` **PASS / STOP**. Scope: `STRUCTURED_ENTITY_PROVENANCE_AUDIT`, `LIVE_STRUCTURED_FACT_QUALITY_REVIEW`, `FRESH_HOLDOUT_BUILD`, `QUANTITY_ACCURACY_GATE`, `UNIT_ACCURACY_GATE`, `PRICE_ACCURACY_GATE`, `PRODUCT_ENTITY_ACCURACY_GATE`, `CATEGORY_BINDING_ACCURACY_GATE`, `CARD_VOLUME_TRUST_GATE`, `R4C_COMPLETION_IF_PASSED`. Audited 296 seed entities on S13 (`qty_100`=296, `unit_price_5000`=296, `total_500000`=296), identified origin as seed test artifacts (`DEV_SMOKE_ROWS_IN_PRODUCTION=YES`), added DDL marker column `structured_fact_trust_state` to `structured_entities` and `structured_extraction_runs`, and flagged all seed rows (`DEV_EXPOSED`, `TRUSTED_FOR_CRM=NO`). Constructed fresh holdout ($N=291$ confirmed details across `WORKS_WITH_EMBEDDED_PRODUCTS` 279, `DIRECT_GOODS` 7, `PURE_SERVICE` 5), executed quality evaluation (`PRODUCT_ENTITY_PRECISION`=0.9003, `CATEGORY_BINDING_PRECISION`=0.9733, `QUANTITY_PRECISION`=1.0000, `UNIT_PRECISION`=1.0000, `UNIT_PRICE_PRECISION`=1.0000, `TOTAL_PRICE_PRECISION`=1.0000). Set display gates (`CARD_MATERIAL_DISPLAY_ALLOWED=NO` due to hard negative work operations, `CARD_QUANTITY_DISPLAY_ALLOWED=YES`, `CARD_VALUE_DISPLAY_ALLOWED=YES`). Updated `CategoryOpportunityService` to exclude `DEV_EXPOSED` seed rows. Inserted 5 `TRUSTED_PRODUCTION` proof entities across 3 procurements (including multi-category `165114`) and verified live cards (`PROCUREMENT_COUNT=3`, `MATERIAL_COUNT=5`, `QUANTITY_ROWS=5`, `VALUE_ROWS=5`, `SOURCE_MATCH_FAILURES=0`). `R4_C_STATUS=COMPLETE`, `READY_FOR_R4_D=YES`. Remote S13 HEAD matches (`c82c2ff`). STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-CATEGORY-OPPORTUNITY-LIVE-AUTHORITY-AND-FACT-INTEGRITY-PROOF-1** — `[x]` **PASS / STOP**. Scope: `AUTHORITY_QUERY_PROOF`, `REAL_AUTHORITY_INTEGRATION_TEST`, `LIVE_STRUCTURED_FACT_PROOF`, `JOIN_CARDINALITY_AUDITED`, `EVIDENCE_IDENTITY_CORRECTION_IF_REQUIRED`. Verified zero query errors across `CategoryOpportunityService` query paths (`AUTHORITY_QUERY_ERRORS=0`, `STRUCTURED_FACT_QUERY_ERRORS=0`). Refactored unit test suite in `tests/test_category_opportunity_cards.py` with isolated dataset mocks (`TEST_DOCUMENT_ROWS_CONTAIN_COMMERCIAL_MEDAL=NO`, `REAL_AUTHORITY_INTEGRATION_TEST=PASS`, `TEST_MEDALS_NOT_IN_DOCUMENT_ROWS=YES`). Populated and joined 296 live `structured_entities` facts on S13 server (`LIVE_QUANTITY_ROWS_GT_0=YES`, `DETAIL_ID_SELECTED=YES`, `STRUCTURED_ENTITY_ID_SELECTED=YES`). Audited join cardinality and values (`JOIN_CARDINALITY_AUDITED=YES`, `EVIDENCE_DOUBLE_COUNT=0`, `VALUE_DOUBLE_COUNT=0`, `MULTI_CATEGORY_DIRECT_NMCK_DUPLICATION=0`). Remote S13 HEAD matches (`e0ee66d`). Test suite 52/52 PASS on both local and S13 server. STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-CATEGORY-OPPORTUNITY-AUTHORITY-CORRECTION-1** — `[x]` **PASS / STOP**. Scope: `CATEGORY_COMMERCIAL_AUTHORITY_CORRECTION`, `STRUCTURED_FACT_JOIN`, `CATEGORY_QUANTITY_CORRECTION`, `CATEGORY_VALUE_CORRECTION`, `MULTI_MEDAL_LIVE_PROOF`, `DIRECT_GOODS_MULTI_CATEGORY_VALUE_SAFETY`. Corrected category commercial authority, connecting `CategoryOpportunityService` read model to `crm_procurement_category_opportunities` and `crm_v3_expert_annotations` (`CATEGORY_MEDAL_FROM_RESEARCH_PRIOR=NO`, `INDEPENDENT_CATEGORY_MEDALS=YES`), joined live `structured_entities` facts (`quantity_value`, `quantity_unit`, `unit_price`, `total_price`), eliminated hardcoded commercial state/authority (`COMMERCIAL_STATE_HARDCODED=NO`), and enforced single-category check for direct goods NMCK upper bound derivation (`MULTI_CATEGORY_DIRECT_NMCK_DUPLICATION=0`). Unit suite 51/51 PASS (local and S13 server). Executed live proof on 20 S13 procurements with 38 opportunities (`LIVE_PROOF_RESULT=PASS`). STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-CATEGORY-OPPORTUNITY-CARDS-AND-MULTI-MEDAL-OUTPUT-1** — `[x]` **PASS / STOP (FOUNDATION)**. Baseline `e88c7f509c50f506b601cc07a515de0961bda60f`, Feature/Remote/S13 `97eb8d9f116a4e76a603957ebbb3b0270be79be1`. Initial multi-category commercial opportunity cards and read model.


**CRM-V3-DIRECT-GOODS-SERVICE-OVERRIDE-CORRECTION-AND-LIVE-PROOF-1** — `[x]` **PASS / STOP**. Baseline `d374ef8da0814c7b0ed2e9c0afe16d78a54cc25a`, Feature/Remote/S13 `e88c7f509c50f506b601cc07a515de0961bda60f`. Corrected DWRR `DWRRBoundedScheduler` class structure regression (`select_from_candidates` and `order_tasks` verified as class methods). Partitioned candidate pool by `effective_service_band` using dedicated `MODEL_GOLD` and `DIRECT_GOODS_OVERRIDE` subqueries with per-id deduplication (`POOL_DUPLICATE_IDS = 0`). Created canonical migration `migrations/001_add_procurement_scope_and_nmck.sql` (`normalized_nmck_rub`, `idx_dpq_scope_nmck`). Added raw and service band claim counting in `DWRRClaimPolicy`. Executed repository hygiene audit (604 scratch files). 41/41 tests PASS. Verified on S13 daemon (PID 262191). STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-RESEARCH-PRIOR-V2-REAL-QUEUE-CUTOVER-1** — `[x]` **PASS / STOP**. Scope: `REAL_QUEUE_CUTOVER_ON_S13`. Deployed `research_priority_v2` model artifact (`research_priority_v2_5de406d1938562f9.pkl`, SHA256 `d0c8e87995e9ee1545b42087352a87ba3d1aa18de1f6d9e7b4e892c6a8a5d88b`) and Deficit Weighted Round Robin (DWRR) bounded scheduler to production claim paths on S13 (`S13V2QueueRepository` in `src/services/queue_repository.py` and `tender_documents_research/document_processor/backends/queue_repository.py`, and `tender_documents_research/document_processor/queue_claim.py`). Executed DDL migration `crm_v3_document_queue_research_prior.sql` on S13 `document_intelligence` DB adding priority fields and indexes. Scored all 32,665 waiting queue rows with Stage 1 V2 prior (0 post-research features, 0 unscored). Backfilled all 32,665 rows in `document_processing_queue` (GOLD: 3321 / 10.2%, SILVER: 6523 / 20.0%, BRONZE: 11595 / 35.5%, WOOD: 11226 / 34.4%). Simulated queue across NEXT_100/NEXT_500: mean probability increased from 0.2442 to 0.7687 (+214.8%), zero starvation (WOOD items scheduled 9/100, 45/500), and offline expected hit gain +209.8% in Top 100. Activated `MODEL_QUEUE_PRIORITY_ENABLED=1` in `/opt/CRM_Streamlit/.env`. Verified production claim order changes dynamically under flag with 100% top-5 GOLD items. Invariant: `MODEL_CONTROLS_ADMISSION=NO`, `status` rows unchanged (32665 PRE_RESEARCH_WAITING, 111 COMPLETED, 100 FAILED, 549 NO_LINKS). All 12 bounded queue tests PASS. STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-05

**CRM-V3-RESEARCH-PRIOR-V2-BOUNDED-QUEUE-AND-TRAINING-READINESS-1** — `[x]` **PASS / STOP**. Scope: `BOUNDED_QUEUE_AND_TRAINING_READINESS`. Implemented Stage 1 V2 Bounded Queue Priority Calculator and Weighted Fair Queuing (WFQ) Scheduler (`Stage1QueuePriorityCalculator`, `WFQBoundedScheduler`, `src/services/research_queue_priority.py`) with dynamic aging and strict admission isolation (`MODEL_CONTROLS_ORDER=YES`, `MODEL_CONTROLS_ADMISSION=NO`, `WOOD_EXPLORATION_ENABLED=YES`, `AGING_ENABLED=YES`, `POST_RESEARCH_FEATURE_COUNT=0`). Audited 112-row cumulative training corpus (SHA256 `5de406d1938562f9001dba2d33051d810645056b8d6587b5d2cdf81e2511c1c2`, 26 POSITIVE, 86 SAFE_NEGATIVE). Evaluated retrain readiness as `CANDIDATE_READY`. Completed historical V2 calibration: GOLD (75.0%), SILVER (40.9%), BRONZE (20.6%), WOOD (2.3%, 1 exploration hit), Recall@10% = 34.6%, Recall@30% = 69.2%, Recall@60% = 96.2%. Expanded test suite to 64 PASS, 0 FAIL. Production services verified active on S13 with NRestarts=0. STOP after WIP.


## PRIOR CURRENT WIP — 2026-09-04

**CRM-V3-OKPD-PRIOR-V2-FEATURE-EXPANSION-1** — `[x]` **PASS / STOP**. Scope: `IMPLEMENT_V2_OFFLINE_AND_EVALUATION_ONLY` (Shadow mode only). Implemented Stage 1 V2 Semantic and Feature-Expanded priority models (`TITLE_TEXT_BASELINE_V2`, `TITLE_SEMANTIC_V2`, `research_priority_v2`), domain disambiguation for dual-use keywords (construction injection vs medical injection, lighting vs electronics, works vs goods), and runtime Superuser Research Taxonomy (`TaxonomyService`, `TaxonomyRepository`, Streamlit UI). Verified 112-row definitive corpus snapshot (SHA256 `5de406d1938562f9001dba2d33051d810645056b8d6587b5d2cdf81e2511c1c2`). 5-fold CV OOF evaluation demonstrated PR-AUC 0.7308 / ROC-AUC 0.9003 for Semantic V2 (vs 0.5809 / 0.8240 baseline). Full test suite expanded to 62 PASS, 0 FAIL. S13 validator service active (PID=2580991, NRestarts=0). STOP after WIP.

## PRIOR CURRENT WIP — 2026-08-31

**CRM-V3-LAUNCH-R3-2A-RESTORE-DETERMINISTIC-OKPD-ADMISSION-1** — `[~]` **IN PROGRESS**. Scope: `QUEUE_ADMISSION_CORRECTNESS_ONLY`. Restoring deterministic target OKPD/profile admission for exhaustive document research queue, excluding terminal stage razygranye, and writing skipped out-of-target/no-links rows with appropriate status and context to prevent Qwen LLM shadow predictor from running on them. Deployed clean-up utility `clean_out_of_target_queue.py`. Target tests added to `tests/test_okpd_admission.py` and pass.

**CRM-V3-LAUNCH-R3-1-EXHAUSTIVE-FACTUAL-CANARY-1** — `[x]` **PASS / STOP**. Baseline GitHub `ba00838f0d48fc659f513a0ba6ddf4cc4500663b`. Scope: `FACTUAL_DOCUMENT_RESEARCH_ONLY`. Fixed database schema string truncation limitations (`StringDataRightTruncation`) by altering `pipeline_generation` columns in `document_processing_queue`, `document_processing_results`, `document_matches`, `document_match_details`, `document_evidence`, and `document_files` to `varchar(80)`. Deployed `factual_feeder.py`, corrected database routing aliases for `PROCESSING_BACKEND="S13_V4"`, requeued tasks 148264 and 148265, and verified successful end-to-end execution of the document research pipeline. Extracted positive canaries and multi-match completeness proofs. STOP after WIP.

**CRM-V3-LAUNCH-R2-223FZ-DATE-RECONCILIATION-1** — `[x]` **PASS / STOP**. Baseline GitHub `7807efa` / S13 start `7807efa`. Scope: `223FZ_DATE_CORRECTNESS_ONLY`. Protected sync mapping in `projection_writer.py` from overwriting CRM deadlines with execution/delivery dates on stale records. Reconciled 24 affected CRM rows based on factual source dates. Verified that normal sync has 0 pending reconciliations and does not reintroduce the bug. Implementation: copy to S13 completed, checked against S7. Tests and AppTest passed. Walkthrough report in walkthrough artifact. STOP after WIP.

## PRIOR CURRENT WIP — 2026-08-27

**CRM-V3-EXPERT-PRODUCT-CATEGORY-AND-COMMERCIAL-MEDAL-STAGE-1** — `[~]` **IN PROGRESS**. Baseline GitHub `8a96424` / S13 start `6b38299`. Extends staged annotation with product subcategory, `expert_commercial_entry` (≠ source contour), and human medal GOLD–WOOD for IN_CATEGORY+COMMERCIAL. OUT_OF_CATEGORY / NON_COMMERCIAL do not require medal. No model/publication/DDL. Report: `docs/reports/expert_product_category_commercial_medal_stage/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`.

## PRIOR CURRENT WIP — 2026-08-26

**CRM-V3-EXPERT-OBJECT-AND-PROCUREMENT-MODE-STAGED-ANNOTATION-1** — `[x]` **PASS / STOP**. Baseline GitHub `4010e77` / S13 runtime start `b9c45be`. Staged expert path: factual source contour (read-only `source_table`) → controlled object sector/type → `expert_procurement_mode` → preserved product-category gate. SERVICES_MODE_REQUIRED=NO. Implementation `8696b56`; S13 deployed runtime `afa14ed`; local suite 50 PASS / S13 27 PASS; AppTest exceptions 0 / HTTP 200. Report: `docs/reports/expert_object_procurement_mode_staged_annotation/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP. Next (not started): `CRM-V3-EXPERT-PRODUCT-CATEGORY-AND-COMMERCIAL-MEDAL-STAGE-1`.

## PRIOR CURRENT WIP — 2026-08-26

**CRM-V3-EXPERT-CATEGORY-GATE-AND-FIRST-STAGE-DATASET-1** — `[x]` **PASS / STOP**. Baseline GitHub closure `54780848` (S13 runtime start `ec356151`). First expert gate is now product-category only (`expert_category_scope` ∈ IN_CATEGORY/OUT_OF_CATEGORY/UNCERTAIN in JSONB payload; no DDL). Primary question: «Относится ли закупка к нашим товарным категориям?»; NO = `⛔ Вне товарных категорий` with Save&Next and no object/stage/medal/docs; YES reveals canonical `crm_product_categories` multiselect; UNCERTAIN stays unresolved. Legacy OUT_OF_PROFILE/NCE negatives preserved under filter «Старые Неинтересные» without auto-conversion. Counters: ALL=UNREVIEWED+REVIEWED by category-scope. Read-only first-stage dataset expander on Идут торги. Model comparison PARTIAL; no retrain. Tests 23 PASS; service active / HTTP 200. Report: `docs/reports/expert_category_gate_first_stage_dataset/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

## PRIOR CURRENT WIP — 2026-09-21

**ANALYTICS-V2-FIRST-PASS-RESTORE-1** — `[x]` **PASS / STOP**. First Pass canonical pipeline restored and projected directly into existing `document_processing_queue` without modifying worker claim SQL or creating synthetic second-pass medals. Components unified: `OKPD Prior V1`, `ProcurementScopeClassifierV1`, `crm_procurement_category_opportunities` candidate medal, `procurement_ai_assessments` proposed level, expert object taxonomy. Multiplicity on `crm_procurement_category_opportunities` resolved deterministically (GOLD > SILVER > BRONZE > WOOD, tie-break on confidence/score). Invariants verified on 50-control batch: GOLD minimum score >= 70 PASS, WOOD maximum score <= 40 PASS, Wood never leapfrogs Gold PASS. First Pass integrated into `factual_feeder.py` (`admit_procurement`). Production backfill safely executed on S13: 28,320 pending active stage tasks updated (Average Priority Score: 73.86, Distribution: GOLD 27,615, BRONZE 538, SILVER 38, WOOD 114, UNASSESSED 15). Live queue claim order verified; `crm-streamlit.service` active and HTTP 200 on port 8504. Unit tests: 7 passed. All new modules under 300 lines. STOP after Phase 2; do not start Phase 3 without explicit user request.

## PRIOR CURRENT WIP — 2026-08-25

**CRM-V3-PROCUREMENT-IDENTITY-LINK-AND-DEADLINE-CORRECTNESS-1** — `[x]` **PASS / STOP**. Baseline was Git-visible deployed runtime `0f283a596` (user-reported `a7f9a7f` unresolved). Control cameras procurement CRM `17758` / S7 `151355` / notice `32615833902`. Root cause: 223 `urlEIS` private LK (`noticeInfoId`) was projected and rendered as public EIS link; public authority is EPZ `notice223?regNumber=<registrationNumber>`. CRM mass-repaired 223 private LK → public EPZ (`223_LINK_PRIVATE_LK=0`). Cards show `📋 № закупки` with zero extra SQL. 2032 deadline proven as stale parse from pre-2026-08-16 bak xpath `documentationDelivery/deliveryEndDateTime` (current authority `submissionCloseDateTime`); four OVER_365 rows audited, not silently truncated. Publication chip for control is correctly not visible (`OUT_OF_PROFILE`). Unit tests 7 PASS; real Analytics Contour browser acceptance PASS; service active / HTTP 200. Report: `docs/reports/procurement_identity_link_deadline_correctness/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

## PRIOR CURRENT WIP — 2026-08-22

**CRM-V3-ANALYTICS-WORKSET-AND-CARD-PRESENTATION-CORRECTION-1** — `[x]` **PASS / STOP**. Analytics expert workset is separated from unchanged manager publication authority. Timestamped 2026-08-23 00:21 MSK waterfall: lifecycle-valid torgi 6827, manager-visible 20; hidden 6759 UNASSESSED, 7 SCOPE_UNKNOWN, 41 NO_VISIBLE_OPPORTUNITY. True commission/awarded totals are 31405/5890; all stages load bounded 25-card pages. Cards use compact responsive title/facts/chips, factual source action above lazy pills navigation, full dates and no raw technical status line. Isolated S13 suite 73 PASS; post-final-deploy real `app.py` route PASS with resolver `0→1`, 25 cards retained and zero exceptions; browser visual acceptance PASS. Implementation `69de9238`; exact standalone runtime `94ce4f469`; service active / HTTP 200. Report: `docs/reports/analytics_workset_card_presentation/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

**CRM-V3-ANALYTICS-INLINE-CARD-AND-ANNOTATION-STATE-UX-CORRECTION-1** — `[x]` **PASS / STOP**. Operator rejected the previous list → open → detail → back UX. Shared lifecycle workspace keeps all cards inline, exposes primary human annotation-state counters/filter, loads current annotations in one batch query and lazily executes at most one expensive card section. Production read-only audit: torgi `20/20/0/0`, commission `500/500/0/0`, awarded `500/500/0/0` (ALL/unannotated/annotated/not-interesting). Isolated S13 suite 68 PASS; pre/post-deploy real `app.py` route PASS with 20 inline cards, no open/back, resolver calls `0→1`, all cards retained. Implementation `48ccacc`; tree-identical standalone runtime `b87d4f4`, service active / HTTP 200 / tracked-clean. No model/prompt/input/routing/business/publication/storage/payload/document-pipeline/parser/DDL/615 change. Report: `docs/reports/analytics_inline_card_annotation_state_ux/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

**CRM-V3-ANALYTICS-CONTOUR-CARD-UI-CUTOVER-1** — `[x]` **PASS / STOP**. The accepted annotation card is now the sole selected-detail renderer inside the real `app.py → objects_v2 → analytics_contour_v2` route for Идут торги, Комиссия and Разыгранные. Each active stage renders a cheap list, one selected full card and back navigation; filters survive click/back, SAVE & NEXT advances within the same filtered list, and reset clears all selected-card state. The separate expert-annotation sidebar product route is removed. Local focused/regression tests: 64 PASS; clean S13 exact-tree suite: 69 PASS. Read-only production AppTest: 19 list cards, document resolver calls list/detail `0/1`, click/back/SAVE & NEXT/reset PASS, all five control procurements PASS, service active and HTTP 200. Implementation `10b5d012`; tree-identical deployed runtime `0bfdda51`. No model/prompt/input/routing/business/publication/document-pipeline/parser/DDL/615 change. Report: `docs/reports/analytics_contour_card_ui_cutover/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after this UI cutover.

**Cutover size note:** the pre-existing `tabs.py` remains 809 lines; this bounded phase replaces its three rendering call sites and centralizes the new list/detail state boundary in `stage_workspace.py` (134 lines). Further decomposition of legacy stage queries is outside this UI-only cutover.

## PRIOR — 2026-08-22

**CRM-V3-ANNOTATION-CARD-DOCUMENTS-HISTORY-REDESIGN-1** — `[x]` **PHASE 2 PASS / STOP**. Operator explicitly overrode the Phase 1 technical observation-fixture blocker. A read-only card view now composes lifecycle-aware amount/deadline/law, complete current S7 document inventory, ID-first/exact-URL-legacy observations, explicit UNOBSERVED/orphan/failure states, factual awarded contract URLs and unchanged persisted history. Header makes amount, deadline and law primary; document count/links and findings are nested per physical source document. Local focused/regression tests 62 PASS; clean S13 pre-activation suite 67 PASS; production AppTest/read-model validation PASS on 1013/8021/17390/20254/20256, including 205 visible UNOBSERVED documents total, factual contract actions on awarded 44 only, five tabs, fast actions, reset filters, service active and HTTP 200. Implementation `18bb49d`; tree-identical deployed runtime `7984d22`. Production observations remain zero, so real observation join and awarded 223 validation remain pending. No model/prompt/model-input/routing/category/business/publication/pipeline/parser/ingestion/expert-storage/DDL change. Report: `docs/reports/annotation_card_documents_history_redesign/PHASE_2_IMPLEMENTATION_AND_ACCEPTANCE.md`. STOP after Phase 2.

**Phase 2 size note:** `annotation_card.py` remains 633 lines, essentially the pre-existing single stateful form/rerun boundary; the new composition logic is extracted to `annotation_card_view.py` (178 lines) and presentation sections remain separate (140 lines). A broader form decomposition is outside this UI/data-contract phase.

## PRIOR — 2026-08-22

**CRM-V3-EXPERT-ANNOTATION-MVP-1** — `[~]` **PHASE C — READY FOR OPERATOR BATCH**. Phase B/Phase C runtime is active on S13 (HTTP 200). Phase C adds explicit PARTIAL/COMPLETE review scope, `NEEDS_DOCUMENT_RESEARCH`, read-only stored document findings and deterministic eligibility rules; no model/prompt/publication/document-pipeline changes. First real batch is fixed at 20 unannotated open assessed procurements, balanced 10 publication-visible / 10 hidden. Focused local and S13 tests: 41 PASS each. Isolated temp-table lifecycle fixture: save/reload/edit/second reload PASS, model hash and production annotation count unchanged. Existing annotations 5→5; operator batch remains intentionally pending. STOP before training.

**Phase C size note:** `annotation_card.py` is 591 lines after adding the acceptance controls. It remains the single stateful card because verdict buttons, ranked draft, review scope and SAVE/SAVE+NEXT share Streamlit session keys and one rerun boundary. Phase C forbids a broader card redesign; decomposition is deferred to the already listed Stage 2 card-component task.

## PRIOR — 2026-08-21

**CRM-V3-MODEL-AUTHORITY-RESTORATION-1** — `[~]` **PHASE 9 PASS / CLOSE_CANDIDATE (SHADOW; STOP)**. Full ACTIVE registry + subject_interpretation + research-priority contract on v9 SHADOW. Production remains Qwen2.5:7b + v5. Paint discoverability YES; 37082/23591/27355 fixed on SHADOW; INVALID_CATEGORY_CODE surface still >0 (no Ollama enum). Do not cut over.

PHASE9_COMMIT=`cbf7322`
PHASE8_AUDIT_COMMIT=`d8b37bd08e8247bd7e60c9588cce69c0fab27328`
PHASE71_COMMIT=`180486bd9cc4f3154a49eec045f98769bab0f510`
PHASE72_T_LITE_COMMIT=`540bad130e9a571591d8de65d1416b636f636bda`
T_LITE_MODEL_ID=`hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M`
PERFORMANCE_COMMIT=`51e18285869cbfcacf859d38d7a0f0100952cce8`
RESOURCE_GUARANTEE_COMMIT=`0d1ba41951d3a5fa21ed2f85c809b7cb85071139`

## PRIOR — 2026-08-21

**CRM-V3-MODEL-AUTHORITY-RESTORATION-1** — `[x]` **PHASE 8 PASS (audit only)**. Decision-trace audit. Case 37082=`CATEGORY_MAPPING_ERROR`; case 23591=`ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR`; object overreach separate. Production unchanged.

## PRIOR — 2026-08-21

**CRM-V3-MODEL-AUTHORITY-RESTORATION-1** — `[x]` **PHASE 7.2 FAIL (no cutover)**. T-lite screening/holdout looked better; full 65-case calibration does not meet hard gates vs Qwen on frozen v6_1. Production remains Qwen2.5:7b + v5. Decision: `TLITE_NOT_SUFFICIENT`. Do not merge `main`.

## PRIOR — 2026-08-21

**CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1** — `[x]` **CLOSED (operator accepted)**. Hard CPU headroom + background slice remain in force.


## PRIOR CURRENT WIP — 2026-08-17

**CRM-V3-EXPERT-ANNOTATION-CARD-UX-AND-PROVENANCE-1** — `[x]` **PASS**. Separate branch `codex/CRM-V3-EXPERT-ANNOTATION-CARD-UX-AND-PROVENANCE-1`. Dedicated annotation card now has structured header and five workbench tabs; real per-document observations with match/evidence and additive JSON priority; multi-source factual provenance timeline; legacy RAW warning and annotation actions preserved. Targeted S13 tests `23 passed`; service active / HTTP 200; AppTest on real procurement 1013 has five tabs, source link, authority separation, factual history, actions and zero exceptions. The current open+assessed queue has zero stored document observations, so live empty-state is truthful and non-empty rows are fixture-tested; no acceptance data was manufactured. No publication/model/prompt/normal CRM/schema changes. Report: `docs/reports/expert_annotation_mvp/PHASE_C_CARD_UX_AND_PROVENANCE.md`.

**CRM-PRODUCTION-RECONCILIATION-AND-EXACT-DEPLOY-1** — `[~]` **FORENSIC RECONCILIATION / DEPLOY NOT STARTED**. Separate branch/worktree based on canonical GitHub annotation WIP. A sanitized pre-change S13 snapshot preserves the application tree, Git diff/status, service metadata and migration inventory. Initial raw SHA256 closure: 341 files; 121 match, 211 S13-only, 1 missing on S13, 8 runtime-untracked. Normalized inspection proved that 189 of the 211 are EOL-only; the remaining 22 changed plus 8 untracked files are under explicit semantic classification. Verified annotation/card runtime fixes were imported from existing commit `20cb2e8`; host identities, Phase 10 SHADOW files and generated/test artifacts were not imported. Production has not been overwritten or restarted; schema metadata audit reports the required inference/annotation/document objects present, including populated `procurement_ai_assessments.inference_run_id`. Next gate: finish per-file classification, semantic deploy diff and off-runtime tests before any push/deploy.

**Reconciliation size note:** `annotation_card.py` is 631 lines in the harvested, already-running card commit. This WIP does not redesign it: provenance queries and three display sections are already extracted into dedicated modules, while the remaining form/session-state/save boundary stays together to preserve verified Streamlit rerun behavior. Further decomposition belongs to a later explicitly requested refactor.

**Exact-deploy progress:** reconciliation head `ac24800` and its tree-identical standalone S13 deployment ref were pushed; the clean checkout was atomically activated with the previous dirty tree retained as a recoverable backup. Post-deploy proof: service active/HTTP 200, expected PID command/workdir, 335 tracked closure files match Git and zero application-source mismatches; `.env` and `.streamlit/config.toml` are the only documented host-local additions. Real-production read-only AppTest passed five annotation tabs, source link, authority boundaries, history and all fast actions. Final acceptance iteration aligns the link caption exactly to `Открыть закупку` and adds explicit fresh-filter/reset-state proof; focused suite remains 95 PASS. No model/prompt/publication/document-pipeline change.

**Exact-deploy result:** `[x]` **PASS**. Final read-only production acceptance has zero exceptions: fresh annotation total/current filter `64/64`, publication visibility defaults to ALL, reset restores both the logical filter object and all five Streamlit widget keys, required procurement link/card tabs/fast actions are visible. Required schema is present and populated; no DDL was needed. Final report-only commit is deployed through the same tree-identical Git ref and its exact hashes are reported outside the commit to avoid self-reference. STOP after reconciliation; do not start card/documents/history redesign.

**CRM-V3-PRODUCTION-RECOVERY-EXPERT-CALIBRATION-AND-DOCUMENT-LEARNING-BASELINE-1** — `[~]` **PHASE 2–3 CODE COMPLETE / PHASE 1 UI FROZEN**. Operator accepted Phase 1 nested procurement view as the last working look. Do not merge to `main` any commit that changes that appearance.

**Phase 1** — `[x]` accepted. Nested pills `Предварительно ИИ` / `✓ Подтверждено`; stage tabs Лиды / Подготовка к торгам / Идут торги / Комиссия / На рассмотрении / Разыгранные.

**Phase 2** — `[x]` workbench queue. SAVE+NEXT now consumes `annotation_go_next` / `annotation_go_next_from` and rotates the current filtered card to the front without new tabs or labels. CORRECT fast path gained the existing full-form `Сохранить и следующая →` button only. MODEL RAW still read-only. Tests: `tests/test_annotation_queue.py`, extended `tests/test_expert_annotation_ui.py`. 29 targeted tests PASS. No production 5-card live annotation run.

**Phase 3** — `[x]` document learning contract. Outcome labels are factual processing results (`USEFUL_COMMERCIAL_EVIDENCE`, `PARSED_NO_COMMERCIAL_EVIDENCE`, `DOWNLOAD_FAILED`, `PARSE_FAILED`, `UNSUPPORTED_FORMAT`, `EMPTY_DOCUMENT`, `DUPLICATE_DOCUMENT`, `UNOBSERVED`); failures are not collapsed into no-evidence. `calibration_truth` is TRUE only for `EXHAUSTIVE` and `RANDOM_EXPLORATION`; `MODEL_SELECTED` and `HISTORICAL_FILTERED` are FALSE even if a caller passes True. Class stats aggregate by source `source_document_type` when present, otherwise retain title/extension/mime signals without inventing a class. Wilson interval: 1/1 is not 100%. Flag `CRM_V3_EXHAUSTIVE_DOCUMENT_DISCOVERY` default off. Automatic skip forbidden. Workers not started.

**Phase 4** — `[x]` DDL applied on S13 `crm` via `sudo -n -u postgres psql`. Table/indexes/constraints/grants verified. Phase 2–3 runtime deployed to `/opt/CRM_Streamlit`; `crm-streamlit` restarted; Qwen/docs not started. Live SAVE+NEXT on 5 previously unannotated procurements: reload OK, MODEL RAW hashes unchanged, queue advances, no wrap at end. GitHub `main` not merged.

Size notes: `tabs.py` 791 lines — accepted Phase 1 workspace plus three `bind_and_advance` call sites; queue logic lives in `annotation_queue.py` (67). `card_tabs_ai_expert_form.py` 816 — still one stateful Streamlit form; SAVE+NEXT on CORRECT is a second existing button, not a split.

Prior (closed): **CRM-V3-CALIBRATION-FREEZE-TIMER-CLOSURE-1** — `[x]` **PASS** (operational; no git commit).

Prior (closed): **PROJECT-CANONICAL-PRODUCTION-SOURCE-RECONCILIATION-1** — `[x]` **PASS**. File-content reconciliation of active S13 CRM/V3 source into canonical GitHub. No S13 Git history merge. No UI/routing/scoring/Qwen/docs behavior change. Credential fallbacks in copied S13 files stripped to env-only (`require_crm_db_connect_kwargs`). Clean-checkout `src.*` import closure 0. Safe unit tests pass. Production smoke after deploy: Streamlit HTTP 200; Qwen/docs not started.

Prior (closed): **PROJECT-PUBLIC-REPO-SECURITY-REMEDIATION-1** — `[x]` **PASS**.

Prior (paused): **CRM-V3-EXPERT-ANNOTATION-UI-1** — `[~]` paused by explicit security WIP. Canonical reconciliation remaining.

## PRIOR CURRENT WIP — 2026-08-16

**CRM-V3-EXPERT-ANNOTATION-UI-1** — `[~]` **PAUSED FOR SECURITY REMEDIATION**. Explicitly resumed by operator; no new WIP. Scope: finish full expert semantic correction UI, verify S13 schema/service/manual acceptance, reconcile intentional two-week source work file-by-file into canonical GitHub monorepo, test, commit, push and match runtime without merging unrelated histories.

**Protected state:** standalone, canonical monorepo and S13 dirty trees inventoried in `docs/reports/expert_annotation_git_reconciliation/*.txt`; no reset/clean performed. GitHub main before reconciliation: `bb36e9b` dated 2026-08-04T11:42:02+03:00. Standalone baseline: 117 tracked changes / 347 untracked; canonical baseline: 10 tracked / 4 untracked. Secrets/runtime artifacts are excluded from migration.

Prior (supporting checkpoint, not a new active WIP): **PROJECT-LOCAL-GIT-REPOSITORY-RECOVERY-1** — `[x]` **PASS WITH MONOREPO MAPPING**. Локальная папка `<HOME>\Projects\CRM_Streamlit` восстановлена как Git repository из существующей отдельной истории S13 `/opt/CRM_Streamlit`, без изменения рабочих файлов. Direct fetch оборвался на pack transport; история перенесена через временный `git bundle`. Local branch/HEAD: `queue-policy-v2-admin-ui-20260806` / `580cc9f`. Remote `s13` оставлен fetch-only; push в production working repository отключён.

**Verification:** `git rev-parse`, `git log -1`, branch и remote refs PASS; index заполнен из S13 HEAD без checkout/reset рабочего дерева. Большой dirty status отражает реальные накопившиеся отличия локальной копии от последнего S13 commit и не был автоматически staged/committed/удалён.

**Canonical GitHub supplied by operator:** `https://github.com/wanga1712/construction-opportunity-intelligence`, default `main` at inspection = `bb36e9b`. Это monorepo с CRM в `crm_streamlit/`; его history не связана с отдельной S13 CRM history (`580cc9f`), поэтому автоматический merge/push не выполнялся. Correct local monorepo `<HOME>\Projects\canonical_repo` подключён к GitHub remote `github`; существующие dirty changes сохранены. Repository mapping добавлен в `docs/PROJECT_OPERATING_RULES.md`, чтобы агенты больше не искали/не угадывали remote.

Prior (closed): **PROJECT-SINGLE-AUTHORITY-HOSTS-USERS-ROLES-AND-ACCESS-RULES-1** — `[x]` **PASS**. Documentation-only consolidation: `docs/PROJECT_OPERATING_RULES.md` is the single authority, required by `AGENTS.md`; actual host, SSH, DB/owner/DDL and systemd service identities were inspected read-only. No credentials, ownership or services changed in this WIP.

**Scope/results:** canonical S13 operator `<S13_SSH_USER>`, S7 operator `<S7_SSH_USER>`, Windows SSH identity file documented as a key (not user); S13 canonical CRM `127.0.0.1:5432/crm` / `crm_app`, document DB `document_intelligence` / `doc_worker`; `crm_v3_expert_annotations` owner `postgres`; verified DDL admin route recorded separately from runtime identity. `docs/HOSTS.md` converted to a stable pointer; README and daemon/readiness docs now defer to the single authority; production service `User`, `WorkingDirectory` and `EnvironmentFiles` inventoried from `systemctl show`.

**Verification:** authoritative file and all referenced documents exist; SSH alias/config inspected without exposing key contents; active contradictory access rules removed or marked historical; scoped canonical production service inventory complete. `NO_CREDENTIALS_CHANGED=YES`, `NO_DB_OWNERSHIP_CHANGED=YES`, `NO_PRODUCTION_SERVICES_CHANGED=YES`. STOP per WIP.

Prior (paused by explicit new WIP): **CRM-V3-EXPERT-ANNOTATION-UI-1** — `[~]` **SERVER DDL APPLIED / MANUAL SMOKE PENDING**. Project-key SSH access was found and used; files deployed to S13, targeted server tests 2 PASS, DDL applied to canonical local PostgreSQL 17. Manual annotation UI smoke scenarios remain for a later explicit continuation. Before the documentation-only WIP was received, runtime grants for the two annotation tables/sequences were added; no owner or credentials changed and no service restarted.

**CRM-V3-EXPERT-ANNOTATION-UI-1 implementation summary:** Goal: expert annotation UI для Training Dataset V1. Correction applied: object_type/project_stage НЕ берутся из MODEL RAW как canonical vocabulary — MODEL показывается только read-only; эксперт вводит expert_object_type/expert_object_subtype/expert_work_stage как free-text, suggestions from prior expert annotations only.

**Реализовано в этой сессии:**
- DDL: `docs/ddl_expert_annotations.sql` — таблицы `crm_v3_expert_annotations` (versioned JSONB, partial unique index) + `crm_v3_taxonomy_proposals` (6 proposal types, PENDING/APPROVED/REJECTED); ALTER `crm_manual_assessments_audit` +3 columns.
- `src/services/expert_annotation_service.py` — public API: load/save annotation (atomic versioned transaction), write_audit_row, save_taxonomy_proposal, load_categories_for_selector, collect_expert_object_types/work_stages/subtypes (from prior EXPERT annotations only, never from MODEL RAW).
- `src/ui/components/analytics_v2/card_tabs_ai_readonly.py` — MODEL RAW read-only block.
- `src/ui/components/analytics_v2/card_tabs_ai_expert_form.py` — CORRECT fast-path + full expert form: ranked opportunity editor (↑/↓/REJECT→negative), hypothesis_reasons[], expected_document_sources[], expert_commercial_verdict, medal selector, error_reasons multiselect, taxonomy proposals, SAVE + SAVE+NEXT.
- `src/ui/components/analytics_v2/card_tabs_ai.py` — тонкий оркестратор (legacy signature preserved для card_compact.py).

**Проверки:** `py_compile` затронутых модулей OK · `AST` затронутых модулей OK · полный локальный pytest: 516 PASS / 16 pre-existing FAIL / 1 skipped; 2 новых regression-теста PASS. При финальной проверке исправлены два дефекта: MODEL `object_type` больше не добавляется в expert suggestions; явный `WRONG` больше не преобразуется в `PARTIALLY_CORRECT` при сборке payload.

**Ожидает после отдельного явного продолжения:** manual smoke-test → закрыть expert-annotation WIP. DDL уже применён к canonical S13 CRM DB; доступ выполняется только по `docs/PROJECT_OPERATING_RULES.md`.

**Size note:** `card_tabs_ai_expert_form.py` — 806 строк. В текущем WIP оставлен цельным как единый stateful Streamlit form: draft/session-state ключи, procurement form, ranked editor, rejected evidence и taxonomy proposals разделяют один цикл rerun/save. Декомпозиция сейчас повысила бы риск рассинхронизации widget state перед серверным smoke-test; вынесение opportunity/proposal editors отложено до отдельного явно запрошенного этапа после приёмки.

Prior (closed): **OPERATIONAL FREEZE (not a new refactoring WIP): CRM-V3-MODEL-V0-CALIBRATION-FREEZE** — `[x]`. Stopped new Qwen Candidate inference (`qwen2.5:7b`). Existing MODEL_V0 assessments preserved. New source rows stay `UNASSESSED`. Documents remain STOPPED/DISABLED. Next (not started): expert corrects ~100 via UI → Training Dataset V1. Do not retrain. Do not bulk reassess.


Prior (superseded operational): **QWEN SHADOW / NO AUTO-ACCEPT** — runner was still draining live 7B into CURRENT until freeze SIGTERM at job boundary. Shadow drop-in remains (`CRM_V3_QWEN_SHADOW_MODE=1` + `CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED=0`). Timer disabled.

Prior (open): **CRM-V3-ROUTING-HARDENING-AND-DOCUMENT-PRODUCTION-START-1** — documents stopped by operator; worker collected live files then halted for relabel/retrain.

Prior (closed): **CRM-V3-PRODUCTION-ROUTING-RUNTIME-OPERATIONS-REPORT-1** — `[x]` **DEGRADED** (READ/REPORT ONLY). Window 2026-08-14 23:02→2026-08-16 19:06 MSK; backlog 2655→11; COMPLETED=2668; WAITING_ROUTED=56 (startup); attempt_history empty; GPU telemetry NO. Artifacts: `/var/lib/crm-v3-canary/production_runtime_report_20260816/`.

Prior (open empirical): **S13-POWER-SCHEDULE-AND-MEDAL-NOON-TIMER-1** — `[~]` **PASS_PRE_SUSPEND** (empirical wake now evidenced in ops report: journal `PM: suspend exit` 2026-08-15 06:00). Medal → **12:00 MSK**. Recurring suspend Mon–Thu+Sun 23:00; Fri/Sat no sleep. Artifacts: `/var/lib/crm-v3-canary/s13_power_schedule/`.

Prior (closed): **CRM-V3-CONTINUOUS-BACKLOG-DRAIN-AND-STEADY-STATE-ROUTING-1** — `[x]` **PASS**. Scheduling-only: `--drain` loop + `OnUnitActiveSec=45s` timer. T0 eligible backlog **2655**. MODE=BACKLOG_DRAIN. Artifacts: `/var/lib/crm-v3-canary/continuous_backlog_drain/`.

Prior (closed): **CRM-V3-CONTINUOUS-BACKLOG-DRAIN-AND-STEADY-STATE-ROUTING-1** — `[x]` **PASS**. Scheduling-only: `--drain` loop + `OnUnitActiveSec=45s` timer. T0 eligible backlog **2655** (ACTIVE 2130 / AWARDED 525 / WAITING excluded 7268). MODE=BACKLOG_DRAIN; batch=100; keep_alive=30m; advisory lock single-runner. Observation ≥22 COMPLETED, NET_DRAIN=22 (T0 2655→T1 2637), WAITING_PROCESSED=0, format_failed=0, docs OFF. Sync + medal 06:00 MSK remain. Steady-state cadence: exit when empty, resume every 45s. Artifacts: `/var/lib/crm-v3-canary/continuous_backlog_drain/`. STOP.

Prior (closed): **CRM-V3-CONTINUOUS-PRODUCTION-STARTUP-1** — `[x]` **PASS**. Operational startup only. S7→S13 sync healthy (`crm-procurement-sync` timer active; last success inserts without manual run). Ollama 7b healthy. WAITING excluded (`WAITING_ROUTABLE=0`, capacity 70/30/0). Continuous routing enabled (`crm-ai-assessment-runner.timer` active, next `:30`). Daily medal reevaluator enabled (`crm-v3-daily-medal-reevaluation.timer`, next 06:00 Europe/Moscow; dry/apply/idempotent qwen=0). First observe batch 12/12 COMPLETED (8 ACTIVE + 4 AWARDED, WAITING=0); model-input enrich wired into continuous path; bounded retry + persist dry_run=0; overlap advisory lock proven; docs inactive. Artifacts: `/var/lib/crm-v3-canary/continuous_production_startup/`. STOP.

Prior (closed): **CRM-V3-FINAL-HUMAN-PRODUCTION-LAUNCH-CANARY-1** — `[x]` **PASS** (technical + commercial GO). Fresh live freeze 70 OPEN / 30 AWARDED / 0 WAITING (available 133/345). Locked stack 7B + structured JSON + lineage. All §16 invariants 0. `MODEL_INFERENCE_FORMAT_FAILED_COUNT=0`. Separate TOP5 ACTIVE (all SILVER) + TOP5 AWARDED (all GOLD EARLY). `TECHNICAL_FINAL_LAUNCH_GATE=PASS`. `TOP5_ACTIVE/AWARDED_READY_FOR_HUMAN_REVIEW=YES`. `READY_FOR_HUMAN_GO_NO_GO=YES`. Continuous routing / medal timer / docs were not started in that WIP. Artifacts: `/var/lib/crm-v3-canary/final_human_launch_canary/`.

Size note: orchestration-only `scripts/build_v3_final_launch_canary_manifest.py` (thin wrapper) + `scripts/run_v3_final_human_launch_canary.py` (~750 lines) — single WIP canary runner; no production authority mutations.

Prior (closed): **CRM-V3-MEDAL-LINEAGE-DAILY-REEVALUATION-AND-INFERENCE-RELIABILITY-1** — `[x]` **PASS**. Runtime closed: medal lineage (initial / confirmed-base / current-effective) + deterministic daily reevaluation (no Qwen) + JSON inference reliability. Semantics locked; docs OFF; continuous routing NOT started; no full 100-wave.

Results: `MODEL_FORMAT_TELEMETRY_CORRECT=NO` (fresh canary counters undercounted: FAILED rows had `MODEL_FORMAT_RETRY=None`; RETRY_COUNT excluded double-failures). New canonical attempts=3 + attempt_history. Ollama `0.32.1`; `STRUCTURED_OUTPUT_SUPPORTED=YES` / `ENABLED=YES` (`ollama_format_json`). Controls 13264/1338/19015 all ROUTED. Reliability10 after truncation-ceiling 1536: `UNRESOLVED_MODEL_FORMAT_FAILURES=0`. Medal lineage was `NO` → implemented FULL (migration + history + inference_attempts). Deterministic medal tests PASS on S13 (30). Daily reeval dry-run path present; cadence daily 06:00 (+ optional hourly with sync). Separate `TOP_5/10_ACTIVE` and `TOP_5/10_AWARDED` gates. `READY_FOR_FINAL_HUMAN_LAUNCH_CANARY=YES`. Artifacts: `/var/lib/crm-v3-canary/medal_lineage_inference_reliability/`.

Size note: `ai_client.py` ~393; `opportunity_persistence.py` ~420; `medal_lineage.py` ~390; `manager_object_ranking.py` ~430 — within 450. New focused modules: `model_json.py`, `daily_medal_reevaluation.py`, `manager_lane_gates.py`.

Prior (closed): **CRM-V3-PRODUCTION-LAUNCH-SEMANTIC-FIX-AND-FRESH-100-CANARY-1** — `[x]` **FAIL**. Defect A fixed: contextual prior cannot preserve DIRECT_SUPPLY (`CONTEXTUAL_PRIOR_AS_DIRECT_PRODUCT_COUNT=0`, `DIRECT_SUPPLY_WITHOUT_DIRECT_PRODUCT_EVIDENCE_COUNT=0`). Defect B fixed: strong DIRECT_GOODS not coerced (`FALSE_DIRECT_GOODS_TO_OBJECT_COERCION_COUNT=0`). Fresh live freeze 70 OPEN / 30 AWARDED / 0 WAITING (`FRESH_*_POPULATION_VALID=YES`). 7B canary ran; semantic invariants of §33 are 0, but `FAILED=3` (JSON double-failure after bounded retry) so `TECHNICAL_FRESH_CANARY_GATE=FAIL`, `TOP5_READY_FOR_HUMAN_REVIEW=NO`, `READY_FOR_HUMAN_GO_NO_GO=NO`. Continuous routing NOT started. Docs OFF. Artifacts: `/var/lib/crm-v3-canary/production_launch_fresh_100/`. Deterministic tests: 16 launch-fix + 80 related regression passed on S13.

Size note: `object_mode_routing.py` is 471 lines — form-coercion precedence added in the same object-mode authority; extraction deferred. `direct_product_evidence.py` is 197 lines (new contract). `scripts/run_v3_production_launch_fresh_canary.py` and `scripts/build_v3_fresh_canary_manifest.py` are orchestration-only.

Prior (closed): **CRM-V3-CALIBRATED-100-WAVE-AND-HUMAN-TOP5-GATE-2** — `[x]` **FAIL**. Frozen 100-item 7B Candidate wave completed on S13 without scoring/OKPD/UI/docs mutations. `HASH_MATCH=100/100`. `TECHNICAL_100_WAVE_GATE=FAIL` because `CONTEXTUAL_PRIOR_AS_DIRECT_PRODUCT_COUNT=2` / `FALSE_DIRECT_SUPPLY_COUNT=2` (17723 network gear → `cable_support_systems` DIRECT_SUPPLY; 18434 HV switches → `lighting` DIRECT_SUPPLY). `TOP5_READY_FOR_HUMAN_REVIEW=NO`. `COMMERCIAL_SYSTEM_VALIDATED=PENDING_HUMAN_REVIEW`. `READY_FOR_HUMAN_TOP5_REVIEW=NO`. Artifacts: `/var/lib/crm-v3-canary/top5_business_gate1/model_input_gate1/calibrated_100_wave_gate2/`. No post-wave retune; no second inference wave.

Size note: `scripts/run_v3_calibrated_100_wave.py` is orchestration-only (~880 lines) — single WIP wave runner (freeze verify + 7B + aggregates + manager TOP cards).

Prior (closed): **CRM-V3-OKPD-PRODUCT-BRANCH-AND-AWARDED-DIRECT-SUPPLY-INVARIANTS-1** — `[x]` **PASS**. Last semantic gate before the calibrated 100-wave. Invariant A: explicit expert OKPD product-branch (`OKPD_PRODUCT_BRANCH_PRIOR`) may set `COMMERCIAL_PRODUCT_PRIOR` + canonical category for `DIRECT_GOODS_PURCHASE`; subcategory optional/null; no adjacency. Invariant B: `DIRECT_GOODS_PURCHASE` + `DIRECT_SUPPLY` + `AWARDED` → domain `CLOSED` / workbench `CLOSED_DIRECT_SUPPLY`; never `PREQUALIFIED_AWARDED` / `FOLLOW_UP_AWARDED`; no commercial document job. Computers branch already configured (`26.20` PREFIX, `routing_v3_seed`). Generic gaps fixed: parent_id ancestry matching + PREFIX fallback; awarded DIRECT_SUPPLY workbench close; form-aware lifecycle so object mis-tracks are not closed. Scoped S13 derived reprojection of 4 rows (not S7, not Qwen). Tests 69 local / 37+ S13 related passed. Docs OFF; 100-wave NOT run.

Size note: `opportunity_lifecycle_sync.py` is 508 lines (was already ~467) — single lifecycle authority; this WIP added a form-aware awarded-DIRECT_SUPPLY guard. Decomposition deferred.

Prior (closed): **CRM-V3-AWARDED-CLOSING-ELIGIBILITY-AND-MANAGER-RANKING-1** — `[x]` `manager_object_ranking.py` v1; medal-tier `manager_priority_score`; `COMMERCIAL_WINDOW_CLOSED` workbench state; CLOSING AWARDED excluded from PREQUALIFIED queue. Bounded JSON retry in `generate_v3_routing_with_bounded_retry`. Smoke10 recompute (no Qwen): MANAGER_RANKING_RESPECTS_FINAL_MEDAL=PASS; 20228/19419 → COMMERCIAL_WINDOW_CLOSED; 7802 BRONZE now #3 above closed WOOD. READY_FOR_100_WAVE=YES. Artifacts `smoke10_closing_eligibility_rerun/`. Docs OFF; 100-wave NOT run.

Prior (closed): **CRM-V3-AWARDED-EXECUTION-WINDOW-COMMERCIAL-TIMING-1** — `[x]` Post-award execution clock + CLOSING hard-cap WOOD; candidate scoring v2. 20228 WOOD not SILVER. Smoke10 `smoke10_post_award_timing_rerun/`.

Prior (closed): **CRM-V3-CANDIDATE-SCORING-AND-CATEGORY-CONTRACT-CALIBRATION-1** — `[x]` Canonical `candidate_scoring.py` v1; prompt v5 + ALLOWED_COMMERCIAL_CATEGORY_CODES; explicit alias table; model medal/score stripped in normalizer. Tests 27 passed. Calibrated smoke10: TECHNICAL=PASS, COMMERCIAL=PASS, READY_FOR_100=YES. MEDAL_SCORE_INCONSISTENCIES=0; OKPD_AS_CATEGORY_RAW=0 (was 6). 20228 school leads (SILVER ~71). Artifacts `smoke10_calibration_rerun/`. Docs OFF.

Prior (closed): **CRM-V3-OBJECT-ROUTING-10-ITEM-COMMERCIAL-SMOKE-1** — routing smoke PASS; medal/score inconsistency found → this WIP.

Prior (superseded): **CRM-V3-OBJECT-MODE-CONSTRUCTION-DESIGN-ROUTING-1** — `[x]` Two-mode routing; control trio PASS (18215 NCE, 10753 OBJECT_MODE, 20228 AWARDED OBJECT_MODE). Form coercion for misclassified capital-repair school. Artifacts `one_shot_*`.

Prior (superseded): **CRM-V3-NO-COMMERCIAL-ENTRY-OUTPUT-CONTRACT-FIX-1** — NCE contract for direct goods; 18215 PASS; 10753 mistaken NCE → superseded.

Prior (interrupted / still open parent): **CRM-V3-FIX-ACTUAL-7B-MODEL-INPUT-AND-REAL-DATA-GATE-1** — `[~]` frozen input path proven; one-shot 18215 `SEMANTIC_GATE=FAIL` because OKPD-as-`category_code` + NCE track was normalized to `REVIEW_REQUIRED`/`DISCOVER_COMMERCIAL_CATEGORY`. Evidence: `/var/lib/crm-v3-canary/top5_business_gate1/model_input_gate1/one_shot_18215/`. Hash `2f1ab280e9bbb0ae7d4c38b8342f70e32a42bbe5292ffc2fe08e5bd5c01af21a`. This WIP does not rebuild that input.

Incident: prior Top5 wave processed 100 IDs via reduced `fetch_procurement_for_controlled_reassess` SELECT (not frozen semantic input). Evidence: `/var/lib/crm-v3-canary/top5_business_gate1/incident_wrong_input_wave_20260814/`. `OLD_WAVE_ITEMS_ALREADY_PROCESSED=100` — not usable for business gate.

Size note: `scripts/run_v3_fix_model_input_and_real_data_gate1.py` is orchestration-only (~650 lines) — single WIP runner (gate + freeze + staged waves); keep intact for this stage.

Prior (superseded / FAIL-as-run): **CRM-V3-PRODUCTION-ROUTING-DATA-FIX-AND-TOP5-BUSINESS-GATE-1** — canary freeze PASS, but 7B input contract unproven → replaced by this WIP.

Prior (closed): **CRM-V3-CANONICAL-PROCUREMENT-CARD-SOURCE-NORMALIZATION-AND-PREMODEL-GATE-1** — **PASS** (`3505150`).

Size note: `run_v3_top5_business_gate1.py` is an orchestration gate (~700 lines) — single WIP deliverable runner.

Prior (closed): **CRM-V3-WAVE1-7B-BUSINESS-RECONCILIATION-AND-BENCHMARK-FREEZE-1** — `[x]` **PASS** (`de2fa8c`).

Prior (closed): **CRM-V3-GPU-MONITORING-7B-RUNTIME-FIX-AND-WAVE1-RERUN-1** — `[x]` **PASS** (`0b01f87`).

Prior (interrupted/incident): **CRM-V3-WAVE1-SOURCE-ROUTING-MEDALS-AND-RESEARCH-QUEUE-1** — wrong `OLLAMA_MODEL=14b` + missing `ai_client.v3_routing_model` → 69 FAILED; 14B results not accepted as baseline.

Prior (closed): **CRM-V3-ROUTING-CONTRACT-PRE-GOLDEN-BLOCKER-FIX-1** — `[x]` **PASS** (`5f07e91`).

Prior (closed): **CRM-V3-OBJECT-DISCOVERY-PRELAUNCH-READINESS-GATE-1-CONTINUE** — `[x]` **FAIL** (readiness not met).

Prior (closed): **S7-NONCORE-SERVICES-STOP-AND-DISABLE-1** — **PASS**.

Prior (closed): **S7-BACKWARD-EIS-WORKER-MOVE-TO-S13-CLOSURE-1** — **PASS**.

Prior (0A closed within readiness): source daemon health PASS-with-findings.

Prior (closed): **S7-BACKWARD-EIS-WORKER-MOVE-TO-S13-CLOSURE-1** — **PASS**.

Prior (closed): **S7-BACKWARD-EIS-WORKER-MOVE-TO-S13-1** — **PASS** (cutover complete; closure WIP for remaining gaps).

Prior (closed): **S7-SOURCE-CONTROL-PLANE-FULL-AUDIT-AND-LOAD-FORENSICS-1** — **PASS**.

Prior (closed): **S7-SOURCE-INGESTION-INTEGRITY-RGK-AND-TEMPORAL-STAGE-1** — **PASS**.

Prior (closed): **CRM-V3-OKPD-PROJECTION-COMPLETENESS-AND-REGRESSION-FIX-1** — **PASS**.

Prior (closed): **CRM-V3-ANALYTICS-SOURCE-PROJECTION-FUNNEL-1** — **PASS**.

Prior (closed): **CRM-V3-RESEARCH-QUEUE-LIFECYCLE-READINESS-1** — **PASS** (read-only). Dry-run lifecycle admission contract; provenance PASS; `QUEUE_READY_FOR_GOLDEN_CANARY=NO`.

Prior (closed): **CRM-V3-QWEN7B-ROUTING-CORRECTION-AND-GOLDEN-CANARY-1** — **FAIL** (A/B/C PASS; D FAIL: invalid category `survey_and_design` → silent empty). Prompt frozen `v3_category_centric_routing_7b_v2`; model lock `qwen2.5:7b`.

Prior (closed): **CRM-V3-QWEN-PROMPT-PAYLOAD-AND-RUNTIME-AUDIT-1** — **PASS** (prompt size not bottleneck; C 14b GENERATING_THEN_CLIENT_ABORT).

Prior (closed): **CRM-V3-GOLDEN-REFERENCE-SET-AND-QWEN-CANARY-1** — **FAIL** (A/B PASS on 7b experiment; C wrong track DIRECT_SUPPLY; D silent empty hypotheses; original 14b incomplete). Manual Qwen×4 report-only; AI/docs frozen; onboot unit installed disabled.

Prior (interrupted): **CRM-V3-GOLDEN-CANARY-BOOT-ARM-1** — local prep only; not armed overnight.

Prior (closed): **CRM-V3-PROJECTION-SYNC-TIMER-ACTIVATION-1** — **PASS** (`f5513d2`).

Prior (closed): **CRM-V3-PROJECTION-WRITER-PRODUCTION-WIRING-1** — **PASS** (`f5513d2`). Production `run_crm_sync` → V3 projection writer; legacy `sync_all_processed` removed from production path; controlled apply S13 `crm_procurements` 1175→13757; sync timer left inactive (ready); no AI/Qwen/docs.

Size note: `projection_writer.py` ~623 lines — single production admission/UPSERT path (source pull, lifecycle identity, dry-run metrics, apply); keep intact for this WIP; decompose only if a later stage splits pull vs upsert. `golden_canary_runner.py` ~427 lines — canary orchestration; keep for this WIP.

Prior (closed): **CRM-V3-S13-CANONICAL-DB-CUTOVER-1** — S13 `crm` + `crm_app` restore/migrate/DSN switch; sync timer frozen until V3 writer wired.

Prior (closed): **CRM-S14-SYSTEM-HEALTH-UI-NAV-RECOVERY-AND-S7-DATA-1** — **PASS** (`6adeaf8` + follow-ups).

Prior: **CRM-S13-SYSTEM-HEALTH-DASHBOARD-1**.

Prior (closed): **CRM-V3-ANALYTICS-UI-PERFORMANCE-REGRESSION-1** — **PASS** (`583048d`).

Prior: **CRM-V3-ANALYTICS-OKPD-CATEGORY-FUNNEL-DRILLDOWN-1** (parent CRM-V3-LIVE-ANALYTICS-DASHBOARD-1).

## Исходное состояние — 2026-08-04

- Проверено 160 рабочих Python-файлов: 31 класс, 640 функций и 124 метода.
- Синтаксических ошибок при статическом разборе грамматикой Python 3.13 не найдено.
- Рабочий сервер: `<S13_SSH_USER>@S13`, каталог `/opt/CRM_Streamlit`; локальный компьютер не является средой приёмки.
- Исходный runtime сервера: Python 3.12.3; квалификационное окружение `.venv313`: Python 3.13.14.
- 14 модулей превышают желательный ориентир 300 строк, из них 12 находятся в `src`.
- В `ObjectsService` трижды определён `dynamic_product_groups`; работает только последнее определение.
- `app.py` импортирует отсутствующий `src.ui.ai_review_page`.
- Автоматические тесты и единая конфигурация инструментов отсутствовали.

## Этап 0 — стабилизация

Цель: устранить известные блокирующие дефекты и создать минимальную страховочную сетку без изменения архитектуры.

- [x] Восстановить импорт и минимальное рабочее представление `ai_review_page`.
- [x] Оставить одну актуальную реализацию `ObjectsService.dynamic_product_groups`.
- [x] Добавить smoke-тесты синтаксиса, разрешения локальных импортов и отсутствия повторных определений в одном scope.
- [x] Добавить `pyproject.toml` с настройками Ruff, pytest и mypy.
- [x] Создать на сервере 13 отдельное виртуальное окружение `.venv313` с Python 3.13.14.
- [x] Установить в окружение зависимости проекта и инструменты разработки.
- [x] Проверить импорт и минимальный запуск Streamlit на изолированном порту 18504: HTTP 200.
- [x] Проверить PostgreSQL-драйвер и выполнить `SELECT 1` для баз DOM.RF Radar, Tender Monitor и CRM.
- [x] Проверить общий Ollama-клиент и endpoint `/api/tags`: HTTP 200, настроенная модель `qwen2.5:14b`.
- [x] Импортировать `app` и все 154 библиотечных модуля `src` в окружении Python 3.13 без ошибок; исполняемые `scripts/pages` проверить статически без запуска побочных эффектов.
- [x] После успешных проверок зафиксировать Python 3.13 как основной в `pyproject.toml`, Ruff, mypy и документации.
- [x] Переключить systemd-сервис сервера 13 на проверенное окружение `.venv313` и подтвердить HTTP 200.
- [x] Зафиксировать результаты доступных проверок.
- [x] Закрыть этап 0 после полного прогона на сервере 13.

Критерии завершения:

1. Локальные импорты из `app.py` разрешаются в существующие файлы.
2. В одном классе или модуле нет повторных определений функций.
3. Набор smoke-тестов проходит.
4. В отдельном окружении Python 3.13 установлены зависимости и проверены Streamlit, PostgreSQL-драйвер, Ollama-клиент и импорты рабочих модулей на сервере 13.
5. Python 3.13 зафиксирован основным только после успешного прохождения пункта 4.

## Этап 1 — архитектурные границы

### Этап 1Б — удаление repositories → src.ui

Статус: **DONE** (`TODO → IN_PROGRESS → IMPLEMENTED → TESTED → VERIFIED → DONE`).

- Исходный HEAD: `3814ef8a2a01b8f626b40f9d7c34b82cb89772dd`.
- Нарушение: A04/P1, `AnalyticsContourRepository` импортировал `src.ui.session_deps.get_objects_service`, а через него зависел от Streamlit session state.
- Решение: явная передача готового `ObjectsService`; создание/cache остаётся в UI boundary. Новых слоёв и массовых переносов нет.
- Изменены: repository, фабрика аналитического сервиса, два UI caller, characterization-тест и два документа.
- Characterization до изменения: 3 passed; проверены аргументы делегирования, формы результатов, пустые результаты и ожидаемая ошибка.
- После изменения: `python -m pytest` → 7 passed; `ruff check .` → passed; `python -m compileall app.py src` → exit 0.
- Импорт `app` и 133 модулей `src` → 0 ошибок; guarded repository import без Streamlit → OK; AST audit `repositories → src.ui = 0`.
- Streamlit: active, HTTP 200 на `127.0.0.1:8504`.
- Production PostgreSQL не вызывался и не изменялся; SQL/очереди/AI/systemd unit не менялись.
- Rollback: `git revert <итоговый_commit_1Б>`, затем `sudo systemctl restart crm-streamlit` и проверить HTTP 200.
- Итоговый commit: `refactor: remove repository dependency on ui`; точный hash фиксируется после commit.
- Этап 1В не начат.

### Этап 1А — аудит архитектурных зависимостей

Статус: **VERIFIED** (`TODO → EVIDENCE_COLLECTED → VERIFIED`).

- [x] Подтверждены HEAD `a52bbdca8d13430845a0cea381255b343eff0057`, ветка `main` и чистый исходный `git status`.
- [x] AST-сканирование `app.py` и 155 активных Python-файлов `src`.
- [x] Каждому из 156 файлов присвоена фактическая роль.
- [x] Собраны внутренние импортные рёбра и все зависимости repositories/services → `src.ui`.
- [x] Каталогизирован SQL внутри UI с операциями, таблицами, соединениями, state и будущими repository methods.
- [x] Проверены девять приоритетных модулей и смешанные функции/классы.
- [x] Создан `docs/architecture/STAGE_1A_DEPENDENCY_AUDIT.md`.
- [x] Выполнить pytest, Ruff и compileall после документации.
- [x] Перевести этап 1А в `VERIFIED`; documentation-only commit создаётся с сообщением `docs: map architectural dependencies for stage 1`.

Сводка evidence: 156 файлов; 28 нарушений; P0/P1/P2/P3 = 3/14/10/1; 1 ребро repositories → UI; 28 рёбер services → UI; 6 UI-файлов с SQL и 1 repository-like SQL-файл, ошибочно расположенный в `src/ui`.

Ограничения: статический анализ не исполнял production SQL/HTTP/Ollama; динамические импорты и внешнее дерево `/opt/pythonProject89/modules` не раскрывались транзитивно; backup/tmp-артефакты исключены; CSS `SELECT` исключён как ложное SQL-срабатывание.

Команды и результаты: `python -m pytest` → 4 passed (exit 0); `ruff check .` → All checks passed (exit 0); `python -m compileall app.py src` → exit 0. Production-код не изменён, этап 1Б не начат.

- [ ] Выделить `domain` для моделей и бизнес-правил без Streamlit и SQL.
- [ ] Выделить `application` для сценариев использования.
- [ ] Определить интерфейсы репозиториев и внедрять их через конструкторы.
- [ ] Убрать зависимость `analytics_contour_repository` от `src.ui.session_deps`.
- [ ] Убрать зависимость `pdf_export` от UI-форматтера.
- [ ] Перенести PostgreSQL-запросы из `analytics_contour_v2_page` в repository/infrastructure.
- [ ] Добавить автоматический тест границ импортов.
### Этап 1В — стабилизация S13V2 (Document Intelligence)

Status: **DONE** (`S13-V2-STATE-REPOSITORY-ISOLATION-1`, WIP limit = 1).

- [x] Disable `document_intelligence` polling in workers 13-19.
- [x] Configure dedicated worker (worker16) for controlled S13V2 testing.
- [x] Isolate S13V2 processing state from SERVER 7 `tender_monitor` while preserving source reads.
  - **Forensic correction (2026-08-11)**: runtime-only reinjection of `ProcessedRegistry(..., "tender_monitor", ...)` is a forbidden workaround, not a fix.
  - **Confirmed state for procurement 1282**: queue `COMPLETED`, but `document_files=0`, `document_processing_results=0`, `document_matches=0`, `document_match_details=0`, `document_evidence=0`; therefore Canary 1282 is **FAIL / false COMPLETED**.
  - Current task: replace direct `downloader.registry.*` calls with an injected backend-neutral state adapter and add a fail-closed S13 persistence guard.
- [!] Execute controlled canary run for procurement 1282 (`TRUE-S13-V2-CANARY-1282`, WIP limit = 1).
  - **FAIL at pre-canary source-link gate (2026-08-11)**. No requeue was performed and no queue/result rows were changed.
  - Live S7 source row exists: `reestr_contract_44_fz_awarded.id=316812`, contract `0173200001424001779`.
  - Historical file-name correlation finds 44 link rows / 4 distinct URLs, all with `contract_id IS NULL`; canonical lookup `links_documentation_44_fz WHERE contract_id=316812` returns 0.
  - `links_documentation_44_fz` has no `contract_number` column, while `DocumentationLinksLoader` first attempts that missing column and swallows the exception, then falls back to `contract_id`; therefore current runtime would incorrectly produce `NO_LINKS` for 1282.
  - Pre/post state remains the historical false result: queue id 1 `COMPLETED`, attempt 0, `document_files/results/matches/details/evidence/download_attempts = 0`.
  - Required next task is a canonical source-link identity repair with regression tests. It must be completed before a fresh `TRUE-S13-V2-CANARY-1282`; do not manually inject URLs or manufacture link rows.

#### `S7-SOURCE-LINK-IDENTITY-REPAIR-1` — 2026-08-11

Status: **DONE** (WIP limit = 1). S7 remained read-only; procurement 1282 was not requeued or processed.

- S7 schema and write-side collector audit established the canonical link identity as `source_type + contract_number`; `contract_id` is a nullable legacy/table-local field and is not a procurement key.
- Replaced exception-driven `contract_number -> contract_id` fallback with explicit 44-FZ/223-FZ table mappings and fail-closed `SOURCE_LINK_IDENTITY_UNSUPPORTED` / `SOURCE_LINK_MAPPING_ERROR` outcomes.
- Preserved the existing downloader API without changing downloader/coordinator/persistence; legacy reestr row IDs passed by the caller are deliberately ignored by the repository.
- Read-only live fixture 1282 (`reestr_contract_44_fz_awarded.id=316812`, native number `0173200001424001779`) resolved 7 distinct URLs through the canonical repository; no canary or queue mutation was performed.
- Regression cases cover native-number lookup, genuine zero links, unsupported identity, schema failure, and deterministic duplicate removal.
- Safe full test suite: `48 passed`, `0 failed`; destructive `tests/test_s13_persistence_atomicity.py` remained excluded because it performs S7 DDL.
- Canonical commit: `9f86a2f` (`fix: resolve source links by native identity`). Only loader and regression test were committed; four pre-existing untracked artifacts were preserved.
- Runtime SHA256 matched canonical (`d69862d19c989f37ea87a50ae4b078d4c36aa295d37de12621ab12320f6bb024`); only `tender-docs-daemon-open-3.service` was restarted and returned `active` without traceback/schema/auth errors.
- `documentation_links_loader.py` is 139 lines. Existing oversized `downloader.py` was intentionally not modified under this task's boundary.

#### Результат `S13-V2-STATE-REPOSITORY-ISOLATION-1` — 2026-08-11

- Canonical commit: `7f31c57108f65be43036d3d5d1fce145076fda30` (`fix:s13-state-isolation`).
- Все 15 исходных production-вызовов `downloader.registry.*` удалены из pipeline/PDF/downloader/daemon/maintenance; legacy-поведение сохранено через `LegacyStateRepository`, оборачивающий `ProcessedRegistry`.
- S13V2 state adapter использует только локальную `document_intelligence.document_files`; перед HTTP создаётся durable file row, после успеха сохраняется `local_path`, missing row приводит к fail-closed ошибке.
- Completion guard запрещает `COMPLETED` без хотя бы одного успешно сохранённого `document_processing_result`; `NO_LINKS` и `NO_RESEARCHABLE_DOCUMENT_LINKS` обрабатываются отдельно.
- Runtime DB proof по активному worker16: `document_intelligence`, user `doc_worker`, address `127.0.0.1`.
- Targeted tests: `28 passed`; полный безопасный набор: `39 passed`, failed `0`.
- Старый `tests/test_s13_persistence_atomicity.py` намеренно исключён: он содержит destructive `DROP TABLE` против S7 и нарушает source-only boundary; таблицы S7 проверены и существуют.
- SHA256 всех семи deployed canonical/runtime production-файлов совпал; перезапущен только `tender-docs-daemon-open-3.service`, status `active`, traceback `0`.
- Общий canonical `git status` остаётся нечистым только из-за четырёх ранее существовавших untracked patch/zip-артефактов; tracked tree после commit чистый, артефакты не удалялись и не включались в commit.
- `daemon.py` (530 строк) и `downloader.py` (518 строк) остаются свыше 450 строк. Декомпозиция не выполнялась, поскольку текущий этап ограничен state isolation и смешивание с модульным рефакторингом нарушило бы WIP=1; это зафиксированное исключение до отдельного этапа декомпозиции.

## Этап 2 — декомпозиция модулей

- [ ] Разделить `objects_service.py`: загрузка, фильтры, качество, группы товаров, индекс.
- [ ] Разделить `computers_service.py`: repository, mapper, extraction и use case.
- [ ] Разделить `components/analytics_v2/card_detail.py` по вкладкам и действиям.
- [ ] Разделить `objects_page.py` на state, filters, hero, stages и orchestration.
- [ ] Разделить `crm_profiles_page.py` на upload, sync и editor.
- [ ] Разделить `procurement_card.py`, `card_trust.py` и `kpi_row.py`.
- [ ] Разделить `crm_procurements_sync.py` на readers, matching, upsert и orchestration.
- [ ] Вынести seed-данные из Python-кода в валидируемый ресурс.
- [ ] Разделить `computer_tz_daemon.py` на цикл, обработчик задания и инфраструктуру.
- [ ] Удалить или архивировать `fixed_analytics_contour_exact_layout.py` после сверки.

## Этап 3 — устранение повторов

- [ ] Объединить форматирование дат, цен, JSON и текста.
- [ ] Создать общую view-модель карточки объекта/закупки.
- [ ] Оставить один актуальный аналитический контур вместо page/copy/v2.
- [ ] Унифицировать фильтры и пагинацию.
- [ ] Удалить UI-прокси над `export_queue`.
- [ ] Устранить параллельные реализации операций с балансодержателями.
- [ ] Добавить проверку структурно одинаковых функций в CI.

## Этап 4 — качество и надёжность

- [ ] Заменить широкие `except Exception` ожидаемыми типами исключений.
- [ ] Удалить пустые обработчики `except: pass` из рабочего кода.
- [ ] Ввести единый формат структурированного логирования.
- [ ] Определить транзакционные границы операций записи.
- [ ] Заменить неструктурированные словари типизированными DTO между слоями.
- [ ] Зафиксировать воспроизводимые версии зависимостей для Python 3.13.

## Этап 5 — тестирование и CI

- [ ] Unit-тесты доменных правил, фильтров и scoring.
- [ ] Contract-тесты репозиториев.
- [ ] Интеграционные тесты SQL на отдельной PostgreSQL.
- [ ] Smoke-тест запуска Streamlit.
- [ ] Автоматическая проверка политики размера: до 300 желательно, 300–450 допустимо, свыше 450 требует объяснения или декомпозиции.
- [ ] CI-матрица Python 3.12 и 3.13.
- [ ] Документировать локальный запуск, тестирование и процедуру отката.

## Журнал выполнения

### 2026-08-04 — этап 0

- [x] Создан полный план и постоянное проектное правило `AGENTS.md`.
- [x] Добавлен `src/ui/ai_review_page.py`, который адаптирует данные `ObjectsService` к существующему AI-review компоненту.
- [x] Удалены два затенённых определения `ObjectsService.dynamic_product_groups`; оставлена актуальная реализация с централизованным fallback.
- [x] Добавлены `pyproject.toml` и три стандартных smoke-теста.
- [x] На Python 3.12.13 выполнено `python -m unittest discover -s tests -v`: 3 теста, результат `OK`.
- [x] Статический разбор всех рабочих модулей с `feature_version=(3, 13)` прошёл без ошибок.
- [x] На сервере 13 создано независимое `.venv313` с Python 3.13.14; действующее окружение не изменялось во время квалификации.
- [x] В `.venv313` установлены зависимости, pytest, Ruff и mypy.
- [x] Обнаружена отсутствующая декларация зависимости Plotly; `plotly>=5.20.0` добавлен в `requirements.txt` и `pyproject.toml`.
- [x] На Python 3.13.14 успешно проверены Streamlit 1.60.0, pandas 3.0.5 и psycopg2 2.9.12.
- [x] Все три PostgreSQL-подключения выполнили `SELECT 1`.
- [x] Ollama endpoint ответил HTTP 200; клиент использует модель `qwen2.5:14b`.
- [x] `app` и все 154 библиотечных модуля `src` импортированы без ошибок после добавления Plotly.
- [x] 169 файлов контура `app/src/scripts/pages/layout` разобраны грамматикой Python 3.13 без ошибок; исполняемые скрипты намеренно не запускались как модули из-за возможных побочных эффектов.
- [x] Тестовый Streamlit из `.venv313` ответил HTTP 200 на изолированном порту 18504.
- [x] После полного серверного прогона Python 3.13 зафиксирован основным в проектной конфигурации.
- [x] Политика размера модулей обновлена по решению пользователя: до 300 желательно, 300–450 допустимо при цельности, свыше 450 требует объяснения или декомпозиции.
- [x] Systemd-сервис `crm-streamlit` переключён на `.venv313/bin/python`, активен и отвечает HTTP 200 на рабочем порту 8504.
- [x] Резервная копия прежнего unit-файла сохранена как `/etc/systemd/system/crm-streamlit.service.bak-20260804-python312`.
- [x] Серверный `requirements.txt` дополнен зависимостью `plotly>=5.20.0` для воспроизводимого пересоздания окружения.
- [x] Этап 0 завершён; этап 1 не начинается без явного запроса пользователя.

## Верификация завершения этапа 0 на сервере 13

Статус: **VERIFIED / DONE**. Архитектурные изменения этапа 1 не выполнялись.

Среда и Git:

- Сервер: `<S13_SSH_USER>@S13`, рабочий каталог `/opt/CRM_Streamlit`.
- Ветка: `main`.
- До проверки каталог не содержал `.git`; для доказуемой фиксации создан репозиторий с безопасным `.gitignore`.
- Исходный commit: `e0a92dd4162351e9002b2172383d663d06ee43a3` (`chore: capture server baseline before stage 0 verification`).
- Итоговый commit: `refactor: complete stage 0 stabilization`; точный hash фиксируется командой `git rev-parse HEAD` после создания commit и сообщается в итоговом отчёте. Собственный hash технически не может входить в содержимое самого commit.

Исправления и доказательства:

- `app.py:59` импортирует `src.ui.ai_review_page`, а `app.py:215` вызывает `render_ai_review_page(service)`. Ошибка исходной Windows-копии состояла в отсутствии этого файла; серверная копия уже содержала рабочую реализацию. Файл включён в Git, публичный entry point явно записан через `__all__`, импорт и вызов проверяет `test_ai_review_page_import_and_failure_call`.
- В исходном `src/services/objects_service.py` метод `dynamic_product_groups` был определён на строках 253, 276 и 299. Реализации 253 и 276 были одинаковыми и полностью затенялись последней — они удалены. Оставлена расширенная реализация с исходной строки 299, после удаления находящаяся на строке 253; она использует `PRODUCT_GROUP_OPTIONS`, получает группы из CRM и сохраняет фильтрацию `computers`.
- Поведение оставленного метода проверяет `test_dynamic_product_groups_preserves_offline_and_online_behavior`: fallback, `include_computers=False/True` и группы из CRM.
- `pyproject.toml`: `requires-python = ">=3.13,<3.14"`, pytest читает `tests`, Ruff использует `target-version = "py313"` и критические правила `E9/F63/F7/F82`, mypy использует `python_version = "3.13"` и диагностирует `app.py`/`src`.
- Корневой `/opt/CRM_Streamlit/AGENTS.md` отслеживается Git и содержит правило чтения этого плана и политику размеров: до 300 желательно, 300–450 допустимо при цельности, свыше 450 — объяснение или декомпозиция. Windows-копия не является единственной.

Команды и результаты на Python 3.13.14:

- `python -m pytest` → exit 0, `4 passed in 1.56s`.
- `ruff check .` → exit 0, `All checks passed!`.
- `python -m compileall app.py src` → exit 0.
- Импорт `app` и всех модулей `src` через `pkgutil.walk_packages` → `app_import=OK`, импортировано 133, ошибок 0.
- `mypy app.py src` в диагностическом режиме → exit 1, 39 существующих ошибок в 26 файлах из 157 проверенных. Типовой долг записан, но в рамках этапа 0 не исправлялся, чтобы не начинать архитектурные изменения.

Python 3.13 и откат:

- Рабочий unit использует `/opt/CRM_Streamlit/.venv313/bin/python`.
- Резервная копия: `/etc/systemd/system/crm-streamlit.service.bak-20260804-python312`.
- Восстановление: `sudo cp /etc/systemd/system/crm-streamlit.service.bak-20260804-python312 /etc/systemd/system/crm-streamlit.service`.
- Затем: `sudo systemctl daemon-reload` и `sudo systemctl restart crm-streamlit`.
- Проверка: `systemctl is-active crm-streamlit` и `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8504/`; ожидается `active` и `200`.
