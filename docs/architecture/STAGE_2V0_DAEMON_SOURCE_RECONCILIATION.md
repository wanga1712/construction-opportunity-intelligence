# Этап 2В-0 — reconciliation production daemon source

Дата проверки: 2026-08-05. Статус: **VERIFIED / DONE** после локального commit и внешнего bundle. Этап 2В остаётся **BLOCKED_BY_SOURCE_RECONCILIATION** до завершения этого commit; completion guard в данном изменении отсутствует. Этап 2Г: **NOT STARTED**.

## Границы и источники

- GitHub: `wanga1712/construction-opportunity-intelligence`.
- Канонический clone: `/opt/construction-opportunity-intelligence`.
- Production deployment target: `/opt/tender_documents_research`.
- Baseline `origin/main`: `bb36e9ba582e79b70c48aee5e7d879da472d8e71`.
- Ветка reconciliation: `server13-production-reconcile-20260805`.
- Deploy key: `<HOME>/.ssh/<SSH_IDENTITY>`, read-only; приватный ключ не копировался.
- `/opt/CRM_Streamlit` является отдельным Git-репозиторием и в этапе не изменялся.

`git fetch origin` подтвердил `HEAD == origin/main`, divergence `0/0`, clean tree до создания ветки. Fetch не изменял production. Git внутри production target не создавался; symlink, `pull`, `merge`, `rsync`, systemd и production source не менялись.

## Production units

Все семь units имеют `WorkingDirectory=/opt/tender_documents_research`, interpreter `/opt/tender_documents_research/.venv/bin/python`, entrypoint `-m document_processor.daemon`, unit files в `/etc/systemd/system`, drop-ins отсутствуют.

| Unit | EnvironmentFile профиля | Lane/profile | Worker | Batch | State |
|---|---|---|---:|---:|---|
| `tender-docs-daemon-open` | `/etc/tender-docs-worker-open.env` | `crm_active_hot,open_active` | 13 | 4 | active |
| `tender-docs-daemon-open-2` | `/etc/tender-docs-worker-open-2.env` | `crm_active_hot,open_active` | 15 | 4 | active |
| `tender-docs-daemon-open-3` | `/etc/tender-docs-worker-open-3.env` | `crm_active_hot,open_active` | 16 | 4 | active |
| `tender-docs-daemon-awarded` | `/etc/tender-docs-worker-awarded.env` | `awarded_recent,historical_awarded` | 14 | 4 | active |
| `tender-docs-daemon-awarded-2` | `/etc/tender-docs-worker-awarded-2.env` | awarded profile; lane default из unit environment | 17 | 3 | active |
| `tender-docs-daemon-computers` | `/etc/tender-docs-worker-computers.env` | `open_active`, computers profile | 18 | configured default | active |
| `tender-docs-daemon-computers-2` | `/etc/tender-docs-worker-computers-2.env` | `open_active`, computers profile | 19 | configured default | active |

Общие environment files перечислены без значений: `/opt/tender_documents_research/.env`, `/etc/tender-docs-db.env`, соответствующий worker profile. Другие consumers каталога (CRM computer jobs, monitoring и weekend safety guard) обнаружены, но не импортируют completion modules и не входят в будущий restart scope 2В. Timers и shell launchers не менялись.

## Метод сравнения

Сравнивались `*.py`, `*.md`, `pyproject.toml`, `requirements*.txt`, YAML, JSON без заранее известных secrets, shell scripts и systemd templates. Исключены `.git`, virtualenv, caches, logs, downloads, document storage, temp, backups, sandbox, PID/lock, `.env`, credentials, dumps и model files.

Baseline inventory: 88 Git-файлов, 198 production-файлов, union 198. Общих byte differences — 29: 28 являются только LF/CRLF, одно semantic отличие — `document_processor/queue_manager.py`. Git-only source отсутствует. Production-only — 110; полный per-path inventory приведён ниже.

## Критические файлы и заявленный snapshot

- `document_processor/daemon.py`: semantic-identical, byte difference только line endings.
- `document_processor/queue_manager.py`: один production-newer semantic patch, сохранён.
- `document_processor/queue_claim.py`: byte-identical.
- `crm_queue_bridge.py`, `priority_recalculator.py`, `queue_priority_calculator.py`, `document_processor/README.md`: byte-identical.
- Ранее заявленные CRM-файлы найдены в `crm_streamlit/` и `/opt/CRM_Streamlit`. `src/ui/nav.py` и analytics tabs совпадают; root `app.py` и analytics orchestration закономерно разошлись из-за последующих этапов рефакторинга CRM. Они принадлежат отдельному CRM Git history и не переносились в daemon reconciliation.
- `card_compact.py`, `card_detail.py`, `card_trust.py`, `procurement_card.py`, CRM profile files присутствуют в обоих CRM trees; в этом этапе они только каталогизированы.

## Server-only queue patch

Изменена только `QueueManager.purge_lost_sales_window()`. Для non-awarded source tables SQL теперь добавляет условие, запрещающее purge pending-задачи, пока `q.submission_end_at >= CURRENT_DATE`. Для awarded tables прежняя проверка `delivery_end_date/end_date` сохраняется.

Влияние:

- queue claim: нет;
- expired/purge logic: да, предотвращает преждевременное снятие OPEN-задач;
- completion/retry/worker selection: нет;
- SQL: да, один дополнительный predicate в union query;
- transaction boundary: не меняется;
- связанного unit test в Git/production не найдено;
- patch является действующим production fix, а не временным completion-guard;
- зависимостей от других production-only semantic изменений не найдено.

## Принятые решения

В Git перенесены только подтверждённые deltas:

1. `document_processor/queue_manager.py` — `PRODUCTION_NEWER_FIX`, с нормализацией line endings и без переписывания patch.
2. `requirements.txt` — `PRODUCTION_ONLY_SOURCE`, штатный runtime dependency manifest.
3. `utils/logger_config.py` и `utils/exceptions.py` — `PRODUCTION_ONLY_SOURCE`, обязательный import closure daemon/database manager.
4. `smart_text_extractor.py` — `PRODUCTION_ONLY_SOURCE`, динамически импортируется matcher.

`keyword_thresholds.json` и `user_keywords.json` классифицированы `SECRET_OR_CONFIG`: это deployment-managed production configuration; в Git не копировались. Остальные production-only Python/scripts/tests классифицированы как legacy diagnostic/operations/test source вне active daemon import closure; их массовое включение не требуется для P0 guard и отложено на отдельный аудит. `.vscode`, logs и runtime artifacts не коммитятся.

Размер `document_processor/queue_manager.py` превышает 450 строк. В 2В-0 декомпозиция запрещена: файл переносится byte/semantic-equivalent production patch ради восстановления source provenance. Отдельная декомпозиция допустима только после P0 guard и characterization текущих SQL/transaction boundaries. `smart_text_extractor.py` находится в допустимом диапазоне 300–450 строк и переносится как цельная существующая dynamic dependency.

## Проверки canonical базы

- Production Python: `3.12.3`.
- `python -m compileall .`: passed для всего canonical daemon subtree.
- Critical imports `document_processor.daemon`, `queue_manager`, `queue_claim`: passed после восстановления import closure.
- Import audit: 56 modules; 55 импортируются. `document_processor.patch_classifier` намеренно выполняет patch при import и завершает `SystemExit(1)` (`process_text signature not found`); это существующая import-time side effect и ограничение snapshot, не regression reconciliation.
- Safe matcher characterization: 4/4 passed.
- Штатный daemon venv не содержит pytest и Ruff.
- `pytest` через CRM venv заблокирован отсутствующими daemon dependencies/production-only test layout; production PostgreSQL не вызывалась.
- `ruff check .` через CRM venv: 875 pre-existing findings; reconciliation их не исправляет.
- `git diff --check`: passed.

Ни worker, ни queue claim не запускались. DDL/DML и ручных запросов PostgreSQL не выполнялось.

## Deployment boundary и карта этапа 2В

Source: `/opt/construction-opportunity-intelligence/tender_documents_research`. Target: `/opt/tender_documents_research`. Все перечисленные modules загружают семь daemon units из таблицы выше.

| Relative path | Source SHA-256 до 2В | Target SHA-256 | owner/group/mode target | Backup | Будущая команда/проверка/rollback |
|---|---|---|---|---|---|
| `document_processor/daemon.py` | `afd65ba1379001a35ad5c88f02b521967401823b1cca6884e24d45af283cd4f8` | `bd8d47f7423743fe9e7e8d628406fd799ee7611b48bde0e1448c0eaec0b51d03` (line endings only) | `<S13_SSH_USER>/<S13_SSH_USER>/666` | `/opt/tender_documents_research/backups/stage2v_<ts>/daemon.py` | backup exact file; `install -o <S13_SSH_USER> -g <S13_SSH_USER> -m 666`; `sha256sum`; restore backup |
| `document_processor/queue_manager.py` | `d59b349dc26fdcabcb9a522f643fc88526e03a4abcc45768303255b6010fca39` | same | `<S13_SSH_USER>/<S13_SSH_USER>/666` | `.../queue_manager.py` | same procedure |
| `document_processor/task_completion.py` | `50a8dceda9d29e73c6be685fc1f57a28087201e6954252ae8e3ea8b386d52d17` | same | `<S13_SSH_USER>/<S13_SSH_USER>/666` | `.../task_completion.py` | same procedure |
| `document_processor/task_result.py` | `c1fef3aeccafe1ef8bcfa5a38ac75300ae9a01c68adf83e09aec1d1cab20b12c` | same | `<S13_SSH_USER>/<S13_SSH_USER>/666` | `.../task_result.py` | same procedure |
| `document_processor/resume_constants.py` | `198333d8555333b295e39e70732f9e77044b00c885f0b85647925ac89d394a00` | same | `<S13_SSH_USER>/<S13_SSH_USER>/666` | `.../resume_constants.py` | same procedure |

В 2В: backup только фактически изменяемых файлов, точечное копирование без `--delete`, checksum, restart всех семи daemon units, проверка каждого unit/queue progress. Rollback — восстановить только backup-файлы либо развернуть предыдущий Git commit, затем restart тех же семи units. Этот deployment в 2В-0 не выполнялся.

## Production invariants после reconciliation

- `/opt/tender_documents_research` не изменён.
- Семь daemon units active, restart/reload не выполнялся.
- `crm-streamlit` active; HTTP `127.0.0.1:8504` = 200.
- Production checksums critical files совпадают с baseline, приведённым выше.
- Очереди и PostgreSQL вручную не изменялись.
- Completion guard этапа 2В отсутствует.

## Rollback и внешняя сохранность

До deployment rollback reconciliation commit: удалить только локальную ветку после переключения на `main`; production rollback не требуется, поскольку production не менялся. После commit создаётся bundle `/tmp/server13-production-reconcile-20260805.bundle`; его SHA-256 фиксируется в итоговом отчёте. Deploy key остаётся read-only.

## Полный source inventory

Статус `different/line-endings-only` означает byte difference без semantic difference. `Git last commit` относится к baseline `origin/main`; для production-only указан `-`.
| Path | Git | Production | Git SHA-256 | Production SHA-256 | Comparison | Git last commit | Production mtime | Classification | Action |
|---|---:|---:|---|---|---|---|---|---|---|
| `.vscode/settings.json` | no | yes | `-` | `a510610b7365a16bb21e3a38313c58b392a46a317f3d0c7ad1674c63f594a04a` | production-only | `-` | `2026-03-13T12:16:29` | RUNTIME_ONLY | exclude |
| `README.md` | yes | yes | `e209387e7d0a435feccd18c7eb927824f1776557b2485a4134756863b5a36ee8` | `e209387e7d0a435feccd18c7eb927824f1776557b2485a4134756863b5a36ee8` | identical | `dd27873` | `2026-08-03T09:36:12` | IDENTICAL | none |
| `benchmark_matcher.py` | no | yes | `-` | `3b783ad4044b01c9b9660e28b5ce24a31e89d24222fe88b5796beb2322ac94a3` | production-only | `-` | `2026-03-17T15:36:29` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_contract_location.py` | no | yes | `-` | `f85f328b100f2d61bd6cd064f8aedffd5663d6dc456a3c7d56b0296f4b5cb502` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_contract_status.py` | no | yes | `-` | `f0a4df5a81806ada080e3580bc28b88f54918463fb37315b29835ed6ab9f22ab` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_daemon_status.py` | no | yes | `-` | `e9f560d54a83f2b7df9bc09d633f8ef808c76234463d48af1fa6683fb011796e` | production-only | `-` | `2026-02-26T09:37:58` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_dates_and_search.py` | no | yes | `-` | `23f496a3e26f29c3b9122f5d1b3871e7cc73fe1d826fc691f4aec8311def5988` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_dates_and_search_v2.py` | no | yes | `-` | `a274b84c96a9fba26640ba74ebc18288599f6cbaa41b8193d09818496ed08dbb` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_db_locks.py` | no | yes | `-` | `c4cf883ee25197106410cae5d922df21a0b25bd6c85e34def903d869241bda07` | production-only | `-` | `2026-02-26T16:05:47` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_db_status.py` | no | yes | `-` | `8baad57cd5ac23928d85c441cd86e89eaccab84d9c6d11273e741af84fbf4eb5` | production-only | `-` | `2026-02-26T17:20:29` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_deployment_ready.py` | no | yes | `-` | `e137b9e004a7f8c62e6bca7a13968ac11a371a33a9bd93f84ca6ccf6a121bc7a` | production-only | `-` | `2026-03-13T13:37:39` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_env.py` | no | yes | `-` | `71ca711a6995ff38b08a6f3e5677290066eb642701616fe76168efd3ecb7bb62` | production-only | `-` | `2026-03-13T13:48:32` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_first_processed.py` | no | yes | `-` | `663280fd699a05a7b197782afea678bb1dccc513912c3c353df1c7c3c5cc42f4` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_freshness_and_search.py` | no | yes | `-` | `febb0dcab03429bab9a32710471c06771564a24989ff6e682ea7e7028cd0c349` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_keywords.py` | no | yes | `-` | `6e28eef6d2cd0cd69c6051f49fc7ada7f3e7fb61fb5cb6b695881dd693a8cc53` | production-only | `-` | `2026-02-26T15:25:44` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_matches.py` | no | yes | `-` | `18ffffbfe19af170cd8d9596556e25392d0f406bdb33e7756578085431823eaf` | production-only | `-` | `2026-02-26T15:50:02` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_processes.py` | no | yes | `-` | `a3232643a101cf37bcfc1669adb8e9d2236e6551e8363afbcb0a10967440d6d7` | production-only | `-` | `2026-03-16T11:03:31` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_queue.py` | no | yes | `-` | `66955b1623d92a6a805523a3513eed00b5c1ae76d5b82508a428fd7dda14cfb3` | production-only | `-` | `2026-02-26T11:26:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_queue_status.py` | no | yes | `-` | `f4236b8607c972cbdd979ad75f53e3a6135c89c99f8750e5b6fe621f12b7fdd5` | production-only | `-` | `2026-03-17T15:36:29` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_recent_matches.py` | no | yes | `-` | `40ecb3b4f9d33158dc28c264a457392ed1726108ff4b7f320c84d6d504d0c326` | production-only | `-` | `2026-03-17T15:36:29` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_recent_matches_fixed.py` | no | yes | `-` | `ed8c2393312c16db6e9b6c3ba09cc069ce2926a9ad89d216b839058834c82fbb` | production-only | `-` | `2026-03-17T15:36:29` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_system_status.py` | no | yes | `-` | `c167ec42f36eda96eac3b4a18b55553f01e8dd1ca2e0af9ab6bad03203407e71` | production-only | `-` | `2026-03-16T11:03:12` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `check_table_structure.py` | no | yes | `-` | `8d5476d7ed641251dd9aeccbc2cd2102ef4f4a2ca8066b1dd8d6ef1e287dd320` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `clean_test_phrases.py` | no | yes | `-` | `833697421751caa4079a548ef447b4462ad197450234c5fe0504e909c5fdcd79` | production-only | `-` | `2026-02-26T15:12:21` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `cleanup_garbage_matches.py` | no | yes | `-` | `fc25de396961a37d5f5fa3f5c66d6e1c5168e8ee9fe85c3d51493f179088645f` | production-only | `-` | `2026-02-26T15:51:41` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `complete_system_status.py` | no | yes | `-` | `ab42f959dbe1f1ae40c158b81954fe4d705b45ab25934714733128165bcbb578` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `correct_filter_stats.py` | no | yes | `-` | `d5a4e78706862ff9c1c69168ac0a494b498a4ca4b5f4a5401bf992acb8fca17d` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `correct_patch.py` | no | yes | `-` | `0c1bb1ad21997e3fa160e1ecb9a0377137f0bc5217658ae24bd28e222ccaf9b0` | production-only | `-` | `2026-03-13T13:50:18` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `correct_system_analysis.py` | no | yes | `-` | `2d04a272376d536a2a98f0b384ab1937bacfced5f91a4c2fc626369d70406b60` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `create_local_tests.py` | no | yes | `-` | `961dbf6a41660bf30b3c86a1c3ef827d35717ad7f155493684b17b9a17eb8ea4` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `create_test_files.py` | no | yes | `-` | `c2b724067df3138c3d2704afd8be120701f9d8fb6cbc79a2e633189f96b95a02` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `daemon_analytics.py` | no | yes | `-` | `cdf4bcd7d6cdb12d8a345fb7cf9e94b3efd1c6ec88010c24caa4606449673a45` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `daemon_analytics_fixed.py` | no | yes | `-` | `5c37371356915e915e6463863e93a35ed59ce3efef044be87ec21ee704ffb94f` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `database_work/__init__.py` | yes | yes | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | identical | `dd27873` | `2026-02-24T11:21:39` | IDENTICAL | none |
| `database_work/database_connection.py` | yes | yes | `36e4bfdfb7b127cad7083b807d54193a21761f74b858fc95cb914282e0ca085c` | `36e4bfdfb7b127cad7083b807d54193a21761f74b858fc95cb914282e0ca085c` | identical | `dd27873` | `2026-03-17T15:36:30` | IDENTICAL | none |
| `debug_matcher.py` | no | yes | `-` | `fc0f5f55ac8f3bb149317baf5fcc13db7882166c61b5c76186f2d15fbf2a5fc7` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `debug_scores.py` | no | yes | `-` | `a68311f9317bcee315d893da388e6c266066423b6ee8ac595825831513dc3b15` | production-only | `-` | `2026-03-02T09:58:07` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `debug_search.py` | no | yes | `-` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | production-only | `-` | `2026-03-16T12:41:17` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `deploy_improved_client.sh` | no | yes | `-` | `9878df239b22efdb5f109324d2b53125282e0b7385301dc6a68b5bdb1c5c26ca` | production-only | `-` | `2026-03-16T11:08:59` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `deploy_stunnel_bypass.sh` | no | yes | `-` | `377014323a8e4edc278314819ade7d44ffb5156688c2ac3701f0b5820593e53e` | production-only | `-` | `2026-03-16T11:10:19` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `diagnose_server.py` | no | yes | `-` | `321c7b1b1718264541f0ef352a6d7aee540b1ac13db48129582318c016110d79` | production-only | `-` | `2026-03-16T11:04:02` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `docs/MULTI_PROFILE_DOCUMENT_DAEMON.md` | yes | yes | `5e47d6d7268a8964dbfcf27a911060b399b555fce923a4f22f0b829476575d99` | `5e47d6d7268a8964dbfcf27a911060b399b555fce923a4f22f0b829476575d99` | identical | `dd27873` | `2026-07-23T22:16:46` | IDENTICAL | none |
| `docs/archive/AUDIT_STEP_1_ARCHITECTURE.md` | yes | yes | `788415bc78c227d6db6bf2d827da1d229769b8aeca7844bb0fff160545293447` | `788415bc78c227d6db6bf2d827da1d229769b8aeca7844bb0fff160545293447` | identical | `dd27873` | `2026-07-20T15:54:17` | IDENTICAL | none |
| `docs/archive/AUDIT_STEP_2_PROCESSING_FUNNEL.md` | yes | yes | `59e1fa9f7b75ac6d6ebd8b1658726480ff6db3f36a12e7f9097c0e2decb9610a` | `59e1fa9f7b75ac6d6ebd8b1658726480ff6db3f36a12e7f9097c0e2decb9610a` | identical | `dd27873` | `2026-07-20T12:22:44` | IDENTICAL | none |
| `docs/archive/CRM_CARD_SCHEMA.md` | yes | yes | `b8836e6a5d2566c9fb0fd5e089f4bb2ca387d15ee047ac325af145c35f37baf6` | `bf2544c4662617e6c2d3a89e984dce5cda566b367f3a8cc813b9a0edd483d5b6` | different/line-endings-only | `dd27873` | `2026-03-26T15:39:02` | IDENTICAL | keep Git LF |
| `docs/archive/DEPLOYMENT_STEPS.md` | yes | yes | `3d274277c297ba503f96d8eb9e97ca526f76065389fbb36b3812644d4ec4e3fa` | `1fb53260c895dba06e088d26d088ed2e76396b5a0175da88175f751a7848ebb6` | different/line-endings-only | `dd27873` | `2026-03-13T13:36:44` | IDENTICAL | keep Git LF |
| `docs/archive/DEPLOYMENT_SUCCESS.md` | yes | yes | `c8589e8788f2da883bdc6e61380de6bf260c918af14d0052eca27533c9ceb0ee` | `43c7e73c856d7f526f7e429c7bf6d98b8701f77774741e73f3c6e2824d83e1b0` | different/line-endings-only | `dd27873` | `2026-03-13T13:52:23` | IDENTICAL | keep Git LF |
| `docs/archive/FULL_PRODUCT_FUNNEL.md` | yes | yes | `19dd8ecf0c7af8b3ef69a2ede651ea138e006092110b1af4af167d4799712595` | `19dd8ecf0c7af8b3ef69a2ede651ea138e006092110b1af4af167d4799712595` | identical | `dd27873` | `2026-07-21T16:46:43` | IDENTICAL | none |
| `docs/archive/IMPROVEMENTS_GUIDE.md` | yes | yes | `53b70628bdcf7335e3230410cc45ae1868ce6198c3fc057f61c7cb9f1546ebbc` | `b32f8aee4fcbec42c9fd7d390da33b7338f912c39e4707da9bfe70aae52f4d2f` | different/line-endings-only | `dd27873` | `2026-03-13T13:24:25` | IDENTICAL | keep Git LF |
| `docs/archive/MODULE2_AUDIT.md` | yes | yes | `006aafaff8de7f5936dccd34d67cb5e5ec7433b43075d275aaacf4301b01bd3a` | `6434cd7d058f25fc2c2a43b39a25e03c7f51dc5f594cb9b420194a61ce3fee19` | different/line-endings-only | `dd27873` | `2026-04-13T16:51:36` | IDENTICAL | keep Git LF |
| `docs/archive/PARTIAL_PDF_FIX_REPORT.md` | yes | yes | `7adce82948c4e9bae7ed95c6b57d8b80295757153fbaa681ebf75784431c69fe` | `7adce82948c4e9bae7ed95c6b57d8b80295757153fbaa681ebf75784431c69fe` | identical | `dd27873` | `2026-07-20T13:46:27` | IDENTICAL | none |
| `docs/archive/README_analytical_daemons.md` | yes | yes | `e0185a1f22df0f7782d66855cbf9d7b3d134dd209d144eeadf2f999f6a9b22cd` | `e0185a1f22df0f7782d66855cbf9d7b3d134dd209d144eeadf2f999f6a9b22cd` | identical | `dd27873` | `2026-07-31T12:58:03` | IDENTICAL | none |
| `docs/archive/READY_FOR_DEPLOYMENT.md` | yes | yes | `275e9604f72a38fb41de5559f83f383c34b0686b778ac631f6e13bddc88a937e` | `c25a5b8b1d0c37ae6799e89131ed365a0c977d9125cd45d45161e56c39df1677` | different/line-endings-only | `dd27873` | `2026-03-13T13:38:28` | IDENTICAL | keep Git LF |
| `docs/archive/STATUS_REPORT_20260731.md` | yes | yes | `bf26763b3acfe1032732003e265a134424c2685e4e84f0bf5e81b9f8b260ce5c` | `bf26763b3acfe1032732003e265a134424c2685e4e84f0bf5e81b9f8b260ce5c` | identical | `dd27873` | `2026-07-31T13:19:09` | IDENTICAL | none |
| `docs/archive/STUNNEL_BYPASS_PLAN.md` | yes | yes | `d4caad747507314caa67e621c06389c4760b0d62fe9e02f3b3daf3aa971a7bc6` | `ad02566fa0693321a37b9bec65236f52f576b9e1ce685e7220c91ade4f409770` | different/line-endings-only | `dd27873` | `2026-03-16T11:10:51` | IDENTICAL | keep Git LF |
| `docs/archive/SUMMARY.md` | yes | yes | `9eaca26bddb2659ac5f3e3030184e78e7f5d137ef216989615e5d68cb0ab8cc9` | `e87986649da908948989f594b0ba6000e4715269515253374ecea39c6078b2ac` | different/line-endings-only | `dd27873` | `2026-03-13T13:38:47` | IDENTICAL | keep Git LF |
| `docs/archive/TEXT_EXTRACTION_GUIDE.md` | yes | yes | `e7be4cadb8f49ea2323f781764b58b13143fb83aee78a509f04e3c801fd9e654` | `5fd2b149f8bb253f9c596e92b8b2bd7e1087fd7eba8a31404ff68b9233dfbb76` | different/line-endings-only | `dd27873` | `2026-03-13T13:31:30` | IDENTICAL | keep Git LF |
| `docs/modules/contract_classifier/README.md` | yes | yes | `affbb588a25619f239cd8a5ab1c4618bfed46eced54f3ad7b53cae13165dc5b0` | `affbb588a25619f239cd8a5ab1c4618bfed46eced54f3ad7b53cae13165dc5b0` | identical | `dd27873` | `2026-08-03T09:36:46` | IDENTICAL | none |
| `docs/modules/daemon/README.md` | yes | yes | `a81cc1cd0cdb570fe12dde2d20641a4ae68d74c7e9b63444079500ae693022fb` | `a81cc1cd0cdb570fe12dde2d20641a4ae68d74c7e9b63444079500ae693022fb` | identical | `dd27873` | `2026-07-31T13:24:31` | IDENTICAL | none |
| `docs/modules/matcher/README.md` | yes | yes | `f929505d8f3fc2b5848237c055cf3ba22f37f07e20acf250bec83251d64a31fb` | `f929505d8f3fc2b5848237c055cf3ba22f37f07e20acf250bec83251d64a31fb` | identical | `dd27873` | `2026-07-31T13:24:31` | IDENTICAL | none |
| `docs/modules/queue_manager/README.md` | yes | yes | `fe8788bf205a1f0711dd731e7cb4328862436668c7b7350d0246a82006bf708e` | `fe8788bf205a1f0711dd731e7cb4328862436668c7b7350d0246a82006bf708e` | identical | `dd27873` | `2026-07-31T13:24:31` | IDENTICAL | none |
| `docs/modules/task_pipeline/README.md` | yes | yes | `cbe696292e67387bd4ea598d560d8eef4112dec0fb83b19ca130186c6503b6d3` | `cbe696292e67387bd4ea598d560d8eef4112dec0fb83b19ca130186c6503b6d3` | identical | `dd27873` | `2026-07-31T13:24:31` | IDENTICAL | none |
| `document_processor/README.md` | yes | yes | `dde0b073b6bb61e58509c3ffaee53c0e6f89bbf52a9ee9e35a269058a17967ca` | `dde0b073b6bb61e58509c3ffaee53c0e6f89bbf52a9ee9e35a269058a17967ca` | identical | `bb36e9b` | `2026-08-04T09:34:19` | IDENTICAL | none |
| `document_processor/__init__.py` | yes | yes | `82efe056a04f25d7df88e80cae18d8f0b6eabd31b9a4afb3877d0a1822ea874d` | `24c19147db9cdfcf7d07a941021401115cde6f053d20d3ef76007778dac3ee91` | different/line-endings-only | `dd27873` | `2026-02-17T13:21:49` | IDENTICAL | keep Git LF |
| `document_processor/archive_extractor.py` | yes | yes | `bcf4556e753672baf146c50351ab0328bc8b3d24b0c323bd3aacc8d7adf78191` | `a5d42e5692496c2b2bc096f135101fe3fc42f8964f2cdeff38b1d0f66171a60f` | different/line-endings-only | `dd27873` | `2026-07-27T21:55:53` | IDENTICAL | keep Git LF |
| `document_processor/contract_classifier.py` | yes | yes | `c2e36ffe152e1862f847a8a03dbd62f9ffc9c28a4cba7a7ba35f7004d2bddd71` | `c2e36ffe152e1862f847a8a03dbd62f9ffc9c28a4cba7a7ba35f7004d2bddd71` | identical | `dd27873` | `2026-07-31T00:15:43` | IDENTICAL | none |
| `document_processor/crm_observation_store.py` | yes | yes | `d6950ad49a01d21ad316157762c353e4da8cb4ae2fb55d2e3162bf4fd3d2a283` | `8691bb85e6d45e4076c67066b0b352479b3592ef24578028e0951f3888742ec8` | different/line-endings-only | `dd27873` | `2026-07-29T22:18:14` | IDENTICAL | keep Git LF |
| `document_processor/crm_queue_bridge.py` | yes | yes | `b9e9a72efdd39ff393ccc436afbb7da269a078b2b895840ab9e1b1afd0943f10` | `b9e9a72efdd39ff393ccc436afbb7da269a078b2b895840ab9e1b1afd0943f10` | identical | `bb36e9b` | `2026-08-03T18:57:53` | IDENTICAL | none |
| `document_processor/crm_taxonomy_loader.py` | yes | yes | `b7a1252547801474a6e416d175db08b003016b7cfa5ead005c031c148b8f7c81` | `2eacbc073e8f981faafb6583ef11a7e6fa7363eec1b61fc971b797ea5d8325cb` | different/line-endings-only | `dd27873` | `2026-07-29T22:16:54` | IDENTICAL | keep Git LF |
| `document_processor/daemon.py` | yes | yes | `afd65ba1379001a35ad5c88f02b521967401823b1cca6884e24d45af283cd4f8` | `bd8d47f7423743fe9e7e8d628406fd799ee7611b48bde0e1448c0eaec0b51d03` | different/line-endings-only | `bb36e9b` | `2026-08-03T17:51:43` | IDENTICAL | keep Git LF |
| `document_processor/daemon_maintenance.py` | yes | yes | `4cb090f8ffa97dae337bc1186d19262f7622294a5244467205ac5f1402fd2911` | `4cb090f8ffa97dae337bc1186d19262f7622294a5244467205ac5f1402fd2911` | identical | `dd27873` | `2026-07-30T23:42:05` | IDENTICAL | none |
| `document_processor/document_routing.py` | yes | yes | `8efe17cf0375a1c4de2cdb9474c24c9d497bf5971a50f5b027b833ef7a23ab2a` | `b3bcf218b8cdd5deaff3ccf801178b053e733b8c69194cedb1b00926cb0ba35e` | different/line-endings-only | `dd27873` | `2026-07-29T22:27:32` | IDENTICAL | keep Git LF |
| `document_processor/documentation_links_loader.py` | yes | yes | `18ffe2b064d1333678fe18efcd44a36efddc323a0b5a4071ea266dd130adbd3c` | `18ffe2b064d1333678fe18efcd44a36efddc323a0b5a4071ea266dd130adbd3c` | identical | `dd27873` | `2026-07-30T00:08:12` | IDENTICAL | none |
| `document_processor/downloader.py` | yes | yes | `5e3f2b330477d879b780da1c005e1d94246c6282faebdd40f1bb015196f53f2d` | `5e3f2b330477d879b780da1c005e1d94246c6282faebdd40f1bb015196f53f2d` | identical | `dd27873` | `2026-07-30T00:08:12` | IDENTICAL | none |
| `document_processor/file_enhancer.py` | yes | yes | `56cb7228a3e6c2d909b27c366455f80c45048b3b1956efcb8f32d540fdb38bd5` | `56cb7228a3e6c2d909b27c366455f80c45048b3b1956efcb8f32d540fdb38bd5` | identical | `dd27873` | `2026-02-26T09:35:46` | IDENTICAL | none |
| `document_processor/file_skip_list.py` | yes | yes | `0f645d8dfb2763060d636290d309cb486c66c217ac8e6a9a7ac435d68648fd3e` | `dc2921bf323d83f33a459ee6928042ddec76f9528a70598b5aad6de1a8a9b488` | different/line-endings-only | `dd27873` | `2026-02-27T10:22:12` | IDENTICAL | keep Git LF |
| `document_processor/file_validator.py` | yes | yes | `1a4f0522ab02e02bfd9852a15d4105befec70aeed154d37b3ef88850ba476888` | `804f82614cd56e11d4853eb77b74b19312e2969aec4c226e83e41f6072b463a0` | different/line-endings-only | `dd27873` | `2026-02-25T12:35:20` | IDENTICAL | keep Git LF |
| `document_processor/http_client.py` | yes | yes | `479cad9dac018ee413e5782a2889290dcf39a93930cee3cc49da7b3c747a2a22` | `479cad9dac018ee413e5782a2889290dcf39a93930cee3cc49da7b3c747a2a22` | identical | `dd27873` | `2026-07-30T00:20:58` | IDENTICAL | none |
| `document_processor/match_repository.py` | yes | yes | `a91233e17a47857918e730fb1b7cb10eef2ae4d1b53980c98024bc416d21b2bb` | `a91233e17a47857918e730fb1b7cb10eef2ae4d1b53980c98024bc416d21b2bb` | identical | `dd27873` | `2026-07-29T22:23:20` | IDENTICAL | none |
| `document_processor/matcher.py` | yes | yes | `f8b29388243ab9193c4245a7c7e791fba75fc8f30d4259d86856846943512e22` | `f8b29388243ab9193c4245a7c7e791fba75fc8f30d4259d86856846943512e22` | identical | `dd27873` | `2026-07-31T13:01:53` | IDENTICAL | none |
| `document_processor/matching/__init__.py` | yes | yes | `9d8b793f0a344f65038a3759cb812d2db65165b7ed67feb2ed14bd9df50bd03a` | `9d8b793f0a344f65038a3759cb812d2db65165b7ed67feb2ed14bd9df50bd03a` | identical | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | none |
| `document_processor/matching/composite_drainage_rule.py` | yes | yes | `6f84417a3fba299728c377c1cfb2fcffb02eed27211b17cf47a4a86ec5010e73` | `6f84417a3fba299728c377c1cfb2fcffb02eed27211b17cf47a4a86ec5010e73` | identical | `dd27873` | `2026-07-23T22:16:43` | IDENTICAL | none |
| `document_processor/matching/line_score.py` | yes | yes | `38539cca413496e75804e34db1e316375cc8eefc8e521d99a8cba91c0ba17aae` | `38539cca413496e75804e34db1e316375cc8eefc8e521d99a8cba91c0ba17aae` | identical | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | none |
| `document_processor/matching/match_display_formatter.py` | yes | yes | `29f9da51f8919d6f22e6a6b05bd0edfd5edf1547b98d48aa9686569464ba751b` | `29f9da51f8919d6f22e6a6b05bd0edfd5edf1547b98d48aa9686569464ba751b` | identical | `dd27873` | `2026-07-20T17:01:21` | IDENTICAL | none |
| `document_processor/matching/table_cell_score.py` | yes | yes | `eeaced455fa797edd5e9ca5ed5fae758ab2f7eb4d874ca8ed95dfe919eefa3f0` | `eeaced455fa797edd5e9ca5ed5fae758ab2f7eb4d874ca8ed95dfe919eefa3f0` | identical | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | none |
| `document_processor/matching/table_header_detector.py` | yes | yes | `163b00f724f6f98e013605a5b26e94a20978a18b8d809389a7de4177dfbf5e12` | `163b00f724f6f98e013605a5b26e94a20978a18b8d809389a7de4177dfbf5e12` | identical | `dd27873` | `2026-07-20T17:01:20` | IDENTICAL | none |
| `document_processor/matching/table_row_enricher.py` | yes | yes | `6694e11e2eca13e4e59ef539784dd454287c005634460429d862ba2a4a279027` | `6694e11e2eca13e4e59ef539784dd454287c005634460429d862ba2a4a279027` | identical | `dd27873` | `2026-07-20T17:01:31` | IDENTICAL | none |
| `document_processor/matching/table_row_matcher.py` | yes | yes | `eb63ec04c522ad3d560977210a64638fc7b15e51cd258abe8af260fbc4c0964c` | `eb63ec04c522ad3d560977210a64638fc7b15e51cd258abe8af260fbc4c0964c` | identical | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | none |
| `document_processor/morning_priority_boost.py` | yes | yes | `3d191bc49c7d988086102b9761f6c6d8a34a50b124bdfd7d568bb38445df01cd` | `3d191bc49c7d988086102b9761f6c6d8a34a50b124bdfd7d568bb38445df01cd` | identical | `dd27873` | `2026-07-22T13:01:31` | IDENTICAL | none |
| `document_processor/parse_utils.py` | yes | yes | `81475e3a140cee7f85ce7e1645c40e4f30fc01c6b53f7d7a5b7ee42be5c79857` | `f486f3fdccf73f34449730541958036020d1da7cbfd79330c824a1a7fe0d10cc` | different/line-endings-only | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | keep Git LF |
| `document_processor/parser_factory.py` | yes | yes | `01ecb2eb21a5651ea9f528393ae3320c424989916638b7e0273be6d241334b6d` | `01ecb2eb21a5651ea9f528393ae3320c424989916638b7e0273be6d241334b6d` | identical | `dd27873` | `2026-03-02T09:58:08` | IDENTICAL | none |
| `document_processor/parsers/__init__.py` | yes | yes | `bec88b9ca37507ae806e6903e323b7ba596ce91be9fc4a73a0dae15df1dc0b7a` | `bec88b9ca37507ae806e6903e323b7ba596ce91be9fc4a73a0dae15df1dc0b7a` | identical | `dd27873` | `2026-02-26T18:15:15` | IDENTICAL | none |
| `document_processor/parsers/doc_parser.py` | yes | yes | `7e016f1d5dd9dcbce7e3bbdc43fde55f82b23f1853462b3644bc57a5145f3c14` | `27042ea575d4e35c5929964ba17693032c4e829d69bfd9f8c46de165dc8bd763` | different/line-endings-only | `dd27873` | `2026-02-26T18:14:59` | IDENTICAL | keep Git LF |
| `document_processor/parsers/excel_parser.py` | yes | yes | `1793765788a94ee41ef21a0e45889a157518d7bbc6de3c70e89fdadd4c7c416a` | `1793765788a94ee41ef21a0e45889a157518d7bbc6de3c70e89fdadd4c7c416a` | identical | `dd27873` | `2026-07-27T21:45:16` | IDENTICAL | none |
| `document_processor/parsers/gsfx_parser.py` | yes | yes | `43ba64266f7955fe05d7fc9fda0f97573a404c997710476688a3298343213ad2` | `bb109266cdc136e473dc1f2879b490ef146dc1889c03cb56f2b1dd0151de3cd3` | different/line-endings-only | `dd27873` | `2026-02-26T18:15:01` | IDENTICAL | keep Git LF |
| `document_processor/parsers/odt_parser.py` | yes | yes | `f7cf96566ce41c128a2b9d981adfbf4f85e722fa54f57e7fe483655b3b5459dc` | `f7cf96566ce41c128a2b9d981adfbf4f85e722fa54f57e7fe483655b3b5459dc` | identical | `dd27873` | `2026-02-26T17:46:48` | IDENTICAL | none |
| `document_processor/parsers/pdf_parser.py` | yes | yes | `15ae5ba4106742bfef51164d020926b4a4d3fa0fccdda664d68ae8e4ccfd9566` | `15ae5ba4106742bfef51164d020926b4a4d3fa0fccdda664d68ae8e4ccfd9566` | identical | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | none |
| `document_processor/parsers/pdf_table_extractor.py` | yes | yes | `846641f75be49b823cf36aa1f33d9efafc417b7c5eec979555ca6d208a96cd04` | `5beee56aada478d090d989c6d40005acb44a8caf85d300cc4dc0d4a0a915daf2` | different/line-endings-only | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | keep Git LF |
| `document_processor/parsers/table_row_builder.py` | yes | yes | `547b70d3a6a30d9159d1377c231e0618d5657b2ab62600706993e6f0d10c51d3` | `721697d018db7ce0f870f5ec450bdc3e26844da17f5bad2872d14bb6c63446c8` | different/line-endings-only | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | keep Git LF |
| `document_processor/parsers/text_parser.py` | yes | yes | `56c9480cdbb4ec89818c6f4bf9eec95fd65453d558a7676b7dee1fb3821152e6` | `56c9480cdbb4ec89818c6f4bf9eec95fd65453d558a7676b7dee1fb3821152e6` | identical | `dd27873` | `2026-02-17T13:21:50` | IDENTICAL | none |
| `document_processor/parsers/word_parser.py` | yes | yes | `9f2c2c038b66764bc18c7c29402e55d88e03f6ac8ff956f75ec28ac577a8014e` | `77bed57fe854a7b75d216ece0be29dbfd6d29605ddcbeb45b3f44c2b61141143` | different/line-endings-only | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | keep Git LF |
| `document_processor/patch_classifier.py` | yes | yes | `a5725db3b9f4fdb3617a5a06f699712e44cd67f2dfdbf62436a88099e19622cc` | `a5725db3b9f4fdb3617a5a06f699712e44cd67f2dfdbf62436a88099e19622cc` | identical | `dd27873` | `2026-07-31T00:15:44` | IDENTICAL | none |
| `document_processor/pdf_processor.py` | yes | yes | `c14577a3e7ba14912db3ce8db6d862f6a629b6b05ece033bbc5a4a940f2b36c4` | `ec87d14dd4a9cef031a403cc8866b156bf6a11b1a954d813eb6a80fe17165d42` | different/line-endings-only | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | keep Git LF |
| `document_processor/priority_recalculator.py` | yes | yes | `10500ad5a10cb7fcdc2e40dbb9a2eb6003a59cf767f5759b83d9e1698bebcdeb` | `10500ad5a10cb7fcdc2e40dbb9a2eb6003a59cf767f5759b83d9e1698bebcdeb` | identical | `bb36e9b` | `2026-08-04T09:49:22` | IDENTICAL | none |
| `document_processor/processed_registry.py` | yes | yes | `d0fcf472f46699cf13bd17f94fd6ab61f088e0f90755bcc38df9b42bd2940497` | `d0fcf472f46699cf13bd17f94fd6ab61f088e0f90755bcc38df9b42bd2940497` | identical | `dd27873` | `2026-07-29T23:27:11` | IDENTICAL | none |
| `document_processor/queue_claim.py` | yes | yes | `0c6b46689dabeda231e8875830fe81ef7d4c27a7cf02d345345f95513828e927` | `0c6b46689dabeda231e8875830fe81ef7d4c27a7cf02d345345f95513828e927` | identical | `bb36e9b` | `2026-08-03T17:51:41` | IDENTICAL | none |
| `document_processor/queue_manager.py` | yes | yes | `a91873fe7440184db7e0988da8cbcf17df6ca3b206b84e903d1c6516e49daaaa` | `d59b349dc26fdcabcb9a522f643fc88526e03a4abcc45768303255b6010fca39` | different/semantic | `bb36e9b` | `2026-08-04T11:48:00` | PRODUCTION_NEWER_FIX | transfer production fix |
| `document_processor/queue_populate_coordinator.py` | yes | yes | `cf59466dca0c8c1780bfdc26f723a8dde0d3abb981d96eac6352a0db731b8903` | `cf59466dca0c8c1780bfdc26f723a8dde0d3abb981d96eac6352a0db731b8903` | identical | `dd27873` | `2026-07-30T12:12:11` | IDENTICAL | none |
| `document_processor/queue_priority.py` | yes | yes | `0474a7370aa30825c9268cab37409f3ca6edfbb34eca478092ac1ba12277bf4e` | `0474a7370aa30825c9268cab37409f3ca6edfbb34eca478092ac1ba12277bf4e` | identical | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | none |
| `document_processor/queue_priority_calculator.py` | yes | yes | `bf1851dd7ce300fb0928cb8aa557fad209bcecf9709062327812ec32b32308ff` | `bf1851dd7ce300fb0928cb8aa557fad209bcecf9709062327812ec32b32308ff` | identical | `bb36e9b` | `2026-08-03T17:37:46` | IDENTICAL | none |
| `document_processor/registry_contract_locator.py` | yes | yes | `bba5348f16a1f6ade32ac35167dffd1708d1dae832bcb7eb01fe2494e5a3deaf` | `bba5348f16a1f6ade32ac35167dffd1708d1dae832bcb7eb01fe2494e5a3deaf` | identical | `dd27873` | `2026-07-22T12:50:21` | IDENTICAL | none |
| `document_processor/registry_tables.py` | yes | yes | `e73aad65114c16019ea3843dee017b19b77b32bc3dd6e45c0b6cb673b64164f4` | `e73aad65114c16019ea3843dee017b19b77b32bc3dd6e45c0b6cb673b64164f4` | identical | `dd27873` | `2026-07-22T12:50:20` | IDENTICAL | none |
| `document_processor/reparse_queue.py` | yes | yes | `92f10fc1f52d899a7bdf2d99265640dbbd45e57c945ddb1a537e9d01f13f7b18` | `8f4fbb8e7714b8cf7b01121f29acc6dc48d34cdfa8974aa90b4b4a37caf3e9a4` | different/line-endings-only | `dd27873` | `2026-07-20T11:32:34` | IDENTICAL | keep Git LF |
| `document_processor/reprocess_constants.py` | yes | yes | `a163be294eda945abb0bd5cb1fc61872a8a738608aa0a0a970f0a43a1010f19a` | `a163be294eda945abb0bd5cb1fc61872a8a738608aa0a0a970f0a43a1010f19a` | identical | `dd27873` | `2026-07-20T18:14:20` | IDENTICAL | none |
| `document_processor/resume_constants.py` | yes | yes | `198333d8555333b295e39e70732f9e77044b00c885f0b85647925ac89d394a00` | `198333d8555333b295e39e70732f9e77044b00c885f0b85647925ac89d394a00` | identical | `dd27873` | `2026-07-29T23:27:11` | IDENTICAL | none |
| `document_processor/search_profile_config.py` | yes | yes | `debca3ea580440005af1a4f535455c902a4d80434bea20b8cf598cacc3eeb1a2` | `08fdb3d6de19c274dbe31d846aef37e2b86f9d9205858b00477dbd7b18f520b4` | different/line-endings-only | `dd27873` | `2026-07-29T22:18:57` | IDENTICAL | keep Git LF |
| `document_processor/search_profiles.json` | yes | yes | `30ee72b986c08ecfaefdc6c98fe74f63cff4ab04b1157211316a223d395b2cc0` | `30ee72b986c08ecfaefdc6c98fe74f63cff4ab04b1157211316a223d395b2cc0` | identical | `dd27873` | `2026-07-23T22:51:32` | IDENTICAL | none |
| `document_processor/task_completion.py` | yes | yes | `50a8dceda9d29e73c6be685fc1f57a28087201e6954252ae8e3ea8b386d52d17` | `50a8dceda9d29e73c6be685fc1f57a28087201e6954252ae8e3ea8b386d52d17` | identical | `dd27873` | `2026-07-20T13:07:22` | IDENTICAL | none |
| `document_processor/task_pipeline.py` | yes | yes | `c52d0e6eb6deac38b82121130ebfa13bc743e36cb472a037fa68c3d4b8b67058` | `c52d0e6eb6deac38b82121130ebfa13bc743e36cb472a037fa68c3d4b8b67058` | identical | `dd27873` | `2026-07-31T00:15:56` | IDENTICAL | none |
| `document_processor/task_result.py` | yes | yes | `c1fef3aeccafe1ef8bcfa5a38ac75300ae9a01c68adf83e09aec1d1cab20b12c` | `c1fef3aeccafe1ef8bcfa5a38ac75300ae9a01c68adf83e09aec1d1cab20b12c` | identical | `dd27873` | `2026-07-20T13:07:22` | IDENTICAL | none |
| `document_processor/yandex_client.py` | yes | yes | `69c7e528d170f845319cf3cdf0d81be0ab8ee24a1d9aac2d359b478932672ca7` | `a145711b741496c59d8e62b376e7d2cde317ded3c23a24029cc295b7017ca729` | different/line-endings-only | `dd27873` | `2026-07-20T15:53:57` | IDENTICAL | keep Git LF |
| `enhanced_matcher.py` | no | yes | `-` | `b3102e45e2a7b3a4674ca70e2915e23d914a61091d5e022d84cda5b64dfd7e07` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `filter_analysis.py` | no | yes | `-` | `9aa2ae156783f60c7646cc2baf7742936af1e593c7450042182a2cbc52cec28b` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `final_filter_stats.py` | no | yes | `-` | `9aa2ae156783f60c7646cc2baf7742936af1e593c7450042182a2cbc52cec28b` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `final_system_test.py` | no | yes | `-` | `6138be101d84bee3132c76c1573f03e6fe283f1cefe7650e4dfef90424c9afb3` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_contract_script.py` | no | yes | `-` | `8562f8cda91b3756e7725bc35b93d7ed9361d35fa84dde2631a451f6f2804371` | production-only | `-` | `2026-02-27T19:33:18` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_recent_bridges.py` | no | yes | `-` | `44a561f482bcde4a4a52d56b09e7dccdef12e1749d29776760615b272b0144ac` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender.py` | no | yes | `-` | `fe1c39aa2d87e25f96227819c149e8e9b7e39a6164c190f1e75a05efe0f4d4c1` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender_all_fz.py` | no | yes | `-` | `bca1961ae2100dde6e8ce7129898ca46bef141934a919c16beacaa024d7859cf` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender_comprehensive.py` | no | yes | `-` | `faf21bb885579a0ae94c1c63f3d1f1d92b8224137ae9be60a1f386342375bdb3` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender_extended.py` | no | yes | `-` | `be355063d84193b8e77a66c7f6a8289b3b2ada48becb869a765d90e18105a420` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender_extended_v2.py` | no | yes | `-` | `355c709d83c1a41c93d584139cace6e6381e31afd9ac2d13500f527d2708f4c5` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender_extended_v3.py` | no | yes | `-` | `15ed29ad94c8b74f1a98ff4492798806399dea1a819c0628d47eb46289b84c69` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `find_tender_kitaevskoe.py` | no | yes | `-` | `841564dfd48784938cf849af17cb894a877c7af9bd999eca8ff45aa5e2d36af8` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `full_reset.py` | no | yes | `-` | `3fc302426838b440fb5c70cb7f6470ea56c9e8be6d3ad8803eb47ba853416592` | production-only | `-` | `2026-02-26T11:06:58` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `generate_pdf.py` | no | yes | `-` | `9812c7cac725fb288d16b2ed39c70392c9b6ca52ca33ef7abd244f435447adac` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `improved_http_client.py` | no | yes | `-` | `e09ebef4383ff6b6e815f2da96b602551bea35600e76e8ffb8f3c6bd0c7410bc` | production-only | `-` | `2026-03-16T11:08:17` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `inspect_matches.py` | no | yes | `-` | `1f17f5b66dd9efcfc9670d53f1e3305d86934888cf4ed6077da9356576d1a05f` | production-only | `-` | `2026-02-26T12:01:35` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `inspect_table.py` | no | yes | `-` | `4f62fe933d29e59790c42d2d676b0c4a8e10a6d038547ec7f6703b13cd0cf8ca` | production-only | `-` | `2026-02-27T19:33:19` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `integration_code.txt` | no | yes | `-` | `b2af6a28d14a1e272e75328da96a97487399200fa77b4e7edc4982d04a987ef8` | production-only | `-` | `2026-03-13T13:43:14` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `keyword_thresholds.json` | no | yes | `-` | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` | production-only | `-` | `2026-02-26T15:08:24` | SECRET_OR_CONFIG | keep deployment-managed; do not commit |
| `keywords_debug.txt` | no | yes | `-` | `7e097f97a55553ad4655c9a7d2fb9d2ee61b5bc7201de239e0403d5e746131cf` | production-only | `-` | `2026-08-05T08:48:17` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `kill_pid.py` | no | yes | `-` | `18cd9203c16a019f41eb0e7cb040bec1738c26267c9bdb50c290f59a5c0b6570` | production-only | `-` | `2026-02-26T16:06:31` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `list_tables_and_search.py` | no | yes | `-` | `db3d1e41dc7177dba57c5f893572a6e1060792b46ae9a4f104fbe145dd7328c9` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `local_matcher.py` | no | yes | `-` | `25400ab7f888115b46d44134884148e9668f571cbb86d5ca3bb7cc1c1de92a49` | production-only | `-` | `2026-03-12T14:48:27` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `matcher_config_recommendations.json` | no | yes | `-` | `e2130c7981f0bae1a946f11ab3f7986e1464fcbe9d04bfb1afb4c27f56c3fe30` | production-only | `-` | `2026-03-13T13:15:21` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `matcher_improvements.py` | no | yes | `-` | `d85402d619799fb171f788c82c7e4701edbf32b31d88206c73f01319062dfd49` | production-only | `-` | `2026-03-13T13:18:50` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `matcher_patch.py` | no | yes | `-` | `fc04b896a8b14138d764d31cf69095338319b3eb6d79ee55ea15324e76801594` | production-only | `-` | `2026-03-13T13:42:27` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `monitor_recovery.py` | no | yes | `-` | `91cb7a06e0c5497d315066e74fc8cd8d839c7a8f6eb1349e0f5283d55b671b3f` | production-only | `-` | `2026-03-16T11:04:27` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `monitor_status.py` | no | yes | `-` | `85e80ff6f3cd6a52298e0c658eaff7067bc4c4ddf4509b45c551f4aad9c9f187` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `patch_downloader.py` | no | yes | `-` | `f2ad60b860d3e7aeedfb55338bccc1f7caa4798c5ab933880a6c7967ce35f1ac` | production-only | `-` | `2026-03-16T11:09:34` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `patch_http_client.py` | no | yes | `-` | `18c4571fcaea3549d98cca2b23aeff12453b9dab287754f679fc54469bf63824` | production-only | `-` | `2026-03-16T11:08:50` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `quick_test_integration.py` | no | yes | `-` | `b953d3ee1f126818f7ff932a789f7808bcc1c75293ba24259ed67eb39103fec1` | production-only | `-` | `2026-03-13T13:36:14` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `real_filter_analysis.py` | no | yes | `-` | `9aa2ae156783f60c7646cc2baf7742936af1e593c7450042182a2cbc52cec28b` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `real_user_filter_analysis.py` | no | yes | `-` | `aa8f30dee1900af5f9e144e30078e91f9d84f4b21869dfa7da2d1f42b9d8ac28` | production-only | `-` | `2026-03-17T13:22:31` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `real_user_filter_stats.py` | no | yes | `-` | `9aa2ae156783f60c7646cc2baf7742936af1e593c7450042182a2cbc52cec28b` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `requeue_for_reparse.py` | no | yes | `-` | `745061cd78b39d696a7d8362c4a953dff5114b8e7cbb4347d2afa9e60b978e52` | production-only | `-` | `2026-07-20T11:32:34` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `requirements.txt` | no | yes | `-` | `ebd7175a9e31c0eeb69e2d2c808d5e948ef9246332da4cd2eb3be939f78204f6` | production-only | `-` | `2026-07-20T11:32:34` | PRODUCTION_ONLY_SOURCE | transfer to Git |
| `reset_db.py` | no | yes | `-` | `dd895ba5ebf6027da7f3c9229d59639cbcc558644fa3e08201dee472e7675415` | production-only | `-` | `2026-02-26T09:35:47` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `reset_queue.py` | no | yes | `-` | `4e6516ef38803ac663358544dff805f44298ee730ca276fe51795a28f32aff9c` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `reset_state.py` | no | yes | `-` | `c78c8b1bb4ce04cdf54c6b9195bdaff825f7d23dd1782586b376cf9c758ff2ab` | production-only | `-` | `2026-02-26T09:35:48` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `run_manual_test.py` | no | yes | `-` | `b2fa7b83cc88e95066494edcb2655ff3d614cf015b5a3e88421aa6a88d025271` | production-only | `-` | `2026-03-02T09:58:08` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `run_on_server.sh` | no | yes | `-` | `8c9a4776a50e7a4f3068502ebb68088997c2a5057a38a49e7472b958743e92be` | production-only | `-` | `2026-02-25T10:27:15` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `scripts/inspect_search_settings.py` | yes | yes | `64901d647a17cff102e3748991c59bed8610b5ea08478ffd4c448297c9a87a83` | `64901d647a17cff102e3748991c59bed8610b5ea08478ffd4c448297c9a87a83` | identical | `dd27873` | `2026-07-23T22:06:19` | IDENTICAL | none |
| `scripts/merge_lighting_keywords.py` | yes | yes | `a5852e391ad483a448eafac7bfbf5252986c3ce27b2483d0517636e93e169afd` | `d7b86e39232263e0412ea3101a85b5a4da5fa3b7c27fb8395a35e43c02fd380a` | different/line-endings-only | `dd27873` | `2026-07-23T23:56:34` | IDENTICAL | keep Git LF |
| `scripts/merge_user_keywords_20260723.py` | yes | yes | `e55185190880a85014d3fa5f70655de3d50134f43874600a6e4628eea6ec656b` | `e55185190880a85014d3fa5f70655de3d50134f43874600a6e4628eea6ec656b` | identical | `dd27873` | `2026-07-23T22:16:47` | IDENTICAL | none |
| `scripts/test_profile_routing_tmp.py` | yes | yes | `7c92498e16406bb3c254fa8bd64ae90f39d4cbfbbe9c5b492f79bf38a17cdc4b` | `7c92498e16406bb3c254fa8bd64ae90f39d4cbfbbe9c5b492f79bf38a17cdc4b` | identical | `dd27873` | `2026-07-23T22:51:02` | IDENTICAL | none |
| `scripts/weekend_safety_guard.sh` | yes | yes | `ff330ae0712a960caf3df37f72f452004b723d44930a06bc083f5f950443df0a` | `ff330ae0712a960caf3df37f72f452004b723d44930a06bc083f5f950443df0a` | identical | `dd27873` | `2026-07-28T09:43:33` | IDENTICAL | none |
| `setup_monitoring.sh` | no | yes | `-` | `bb48956f6bf82f97c133bbb6b8b7727602f5a8635af0fe97a07ee9815de01c3c` | production-only | `-` | `2026-03-13T12:58:31` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `setup_smart_extraction.py` | no | yes | `-` | `3cbf9709328df6dd0d9a9c3ccb81f5279b2231f9d440858f47913e461ed2ab06` | production-only | `-` | `2026-03-13T13:35:31` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `simple_filter_check.py` | no | yes | `-` | `9aa2ae156783f60c7646cc2baf7742936af1e593c7450042182a2cbc52cec28b` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `smart_text_extractor.py` | no | yes | `-` | `a588833c3e7a1d038a8e4e2086edb694b7b87863bda522e1be3db1b7e4a30a5e` | production-only | `-` | `2026-03-16T22:43:19` | PRODUCTION_ONLY_SOURCE | transfer to Git |
| `tender_db_smoke.py` | no | yes | `-` | `32a7b6f6027a17f9b12e9ce6afe5d867549a34683dd36e5f77069337f62d2bfa` | production-only | `-` | `2026-07-21T19:55:02` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `tendermonitor-monitoring.service` | no | yes | `-` | `404a2dc1f98691aeb944220fb2260ac80e84217376c9265c548310d4ab62a154` | production-only | `-` | `2026-03-13T12:59:49` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `tendermonitor-monitoring.timer` | no | yes | `-` | `dfb7fd42049c669cad7c4d92cc08d0ef0e914b079fe70a762db352fd4192ccdd` | production-only | `-` | `2026-03-13T12:59:53` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_display.py` | no | yes | `-` | `99423dd641e07aa27bfd90a81ef609f7a00f3cc5810fbdc62a521023b22d7aee` | production-only | `-` | `2026-02-26T12:05:42` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_imports.py` | no | yes | `-` | `095298d944a4ea8093a2691e8a381c838a988499d1ae5edf194059cc818c3153` | production-only | `-` | `2026-02-26T14:06:59` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_on_server.py` | no | yes | `-` | `0648bf94cae9a80aa8e9844b52c7b4adcc13f5f6b81e447e928432e81e590e99` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_real_matching.py` | no | yes | `-` | `124eb4d01076b03b97eddd64cae14afafeec7ede76e312a60f12239951975879` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_smart_extraction_force.py` | no | yes | `-` | `5cd0167aa0513428735f079b0827ce6a5ba2ef328c6341bc4f2d02e5e9e90694` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_smart_extraction_real.py` | no | yes | `-` | `b405246de1f9a7cff03b239fbedad23430db2a83b269cd88ec8296c306a19fd1` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `test_text_extraction.py` | no | yes | `-` | `4c0dd0dce7d3a92d3cbd8fea20b31dd94780dc6e090d2bc59495b926cfe2c882` | production-only | `-` | `2026-03-13T13:29:54` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `tests/test_archive_extractor.py` | no | yes | `-` | `379ad09504e17b5fd9e93e723b7bba66a3d19d141b2ed64551edb6113ccfb374` | production-only | `-` | `2026-07-27T21:50:39` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_excel_parser.py` | no | yes | `-` | `44b6d0fc576c97b7c368ef23d7ef3a9fa7f10fe4e3d3ebee97ffb5d7f920f7f5` | production-only | `-` | `2026-07-27T21:50:39` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_match_display_formatter.py` | no | yes | `-` | `fb8bcc623a9af01de321e67277cdb84d5e2e5854ac7a9984dc7cd5e2c3fee52d` | production-only | `-` | `2026-07-20T17:01:34` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_matcher_basic.py` | no | yes | `-` | `66174425e0c091aaaf5753f9548433491703315a4686afbb29f2b113abd01094` | production-only | `-` | `2026-02-28T11:00:56` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_matcher_complex.py` | no | yes | `-` | `5c913fc0eac1748d1be4d9b9d822e0f6e519741991fc8505aac824e614d7ce3a` | production-only | `-` | `2026-03-02T09:58:09` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_matcher_extended.py` | no | yes | `-` | `2f4bca3812c13c72e6968f2d1b18f00475334b0ebf3dca7c90f90f834990c343` | production-only | `-` | `2026-02-28T11:45:23` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_partial_pdf_resume.py` | no | yes | `-` | `9018dbc59d6e1c4813bd61aac7689c831c652f47cec6158ea52e91cfb65d4873` | production-only | `-` | `2026-07-20T13:19:19` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_table_header_detector.py` | no | yes | `-` | `739cbb94f54bb9a9588164c80033703d37626893e136f8ea88ad5d02474306c4` | production-only | `-` | `2026-07-20T16:50:03` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_table_row_matcher.py` | no | yes | `-` | `bb74893e734584d14b3252432e2ecf94ccc5a1a93b552597109671f58359457b` | production-only | `-` | `2026-07-20T11:32:34` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_word_parser_tables.py` | no | yes | `-` | `77306db4c19bed2afbeced1e405c9153703dc3c71da9a2ad4113a6a0f43eb284` | production-only | `-` | `2026-07-20T11:32:34` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `tests/test_yandex_upload.py` | no | yes | `-` | `10ff970bd3da9ed6f558e600c61cdddca71e7b8208e5e45b975745759fe72d6a` | production-only | `-` | `2026-02-25T16:12:43` | PRODUCTION_ONLY_SOURCE | defer test-source audit |
| `user_filter_stats.py` | no | yes | `-` | `9aa2ae156783f60c7646cc2baf7742936af1e593c7450042182a2cbc52cec28b` | production-only | `-` | `2026-03-17T15:36:30` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
| `user_keywords.json` | no | yes | `-` | `1a8686b55d3b3d1d5124fb8d831bcd32d8820b648df568ef1d16e1ae181d3b91` | production-only | `-` | `2026-07-23T23:57:13` | SECRET_OR_CONFIG | keep deployment-managed; do not commit |
| `utils/exceptions.py` | no | yes | `-` | `0f84fc42a284b623396f725e32d64d7b52eecb9a451a596b6fd8eb0a4f21d871` | production-only | `-` | `2025-11-11T15:50:06` | PRODUCTION_ONLY_SOURCE | transfer to Git |
| `utils/logger_config.py` | no | yes | `-` | `060d318a410ac177f3629db59650dd0d7a5e6c3562f9f591bf23b69cc93f4cba` | production-only | `-` | `2026-02-20T14:16:18` | PRODUCTION_ONLY_SOURCE | transfer to Git |
| `verify_clean.py` | no | yes | `-` | `3c24e6459a27bb651d9e33184bd76bebc3aaede1630f83c3d8c523267b391b95` | production-only | `-` | `2026-02-26T15:32:38` | PRODUCTION_ONLY_SOURCE | leave legacy diagnostics/operations in production |
