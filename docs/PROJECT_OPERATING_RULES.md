# Project operating rules: identities and access

Статус: **единственный authoritative source** для project hosts, human
operators, SSH identities, DB roles, service identities и deployment access.
`AGENTS.md` требует прочитать этот файл до инфраструктурных операций. Другие
документы могут описывать сервисы, но не переопределяют эти правила.

## Термины и запрет смешения identities

- **HUMAN OPERATOR** — человек, управляющий инфраструктурой.
- **OS USER** — Linux account для SSH или процесса.
- **DB ROLE** — PostgreSQL authentication/permission role.
- **SERVICE USER** — OS identity процесса systemd.
- **CRM BUSINESS USER** — отдельная будущая application-level identity; она
  не выводится из OS/DB names. В текущем проекте product end-users нельзя
  определять по Linux или PostgreSQL usernames.
- SSH private key — identity file, а не пользователь или роль.

Никогда не изобретать SSH username, DB username/owner, sudo account, service
account, host, credential или key path. Запрещено пробовать произвольные
`admin`, `root`, `xander`, `ubuntu`, `postgres` и другие identities, если они
не разрешены ниже или существующей approved configuration. Если identity не
удалось подтвердить в этом файле и referenced configuration, остановиться:
`IDENTITY_AUTHORITY_MISSING`.

## Canonical hosts and SSH

| Host | Authority and purpose | Approved human/SSH access |
|---|---|---|
| S13 | Logical name `S13`; CRM, Candidate routing, Qwen/Ollama, document intelligence runtime, canonical CRM DB | primary operator `<S13_SSH_USER>`; canonical local SSH alias: `s13` (`ssh s13`). User, HostName and IdentityFile come only from that existing Host block. |
| S7 | Logical name `S7`; source/history authority, source procurement data and source lifecycle/status | approved OS user `<S7_SSH_USER>`; canonical local SSH alias: `s7` (`ssh s7`). User, HostName and IdentityFile come only from that existing Host block. |

Не вводить дополнительные canonical hosts без отдельного project decision.

## Source control authority

Canonical GitHub repository:
`https://github.com/wanga1712/construction-opportunity-intelligence`.
Это монорепозиторий; CRM project расположен в `crm_streamlit/`, а document
runtime — в `tender_documents_research/`. Нельзя считать отдельную историю
S13 `/opt/CRM_Streamlit` той же Git history или напрямую merge/push её в
GitHub `main`: histories фактически не связаны. Сначала работать через
monorepo checkout и явно сопоставлять нужный subtree.

Локальный monorepo checkout на текущей Windows-машине:
`<HOME>\Projects\canonical_repo`. Remote `github` указывает на
canonical GitHub URL; existing remote `origin` указывает на S13 monorepo.
Не угадывать GitHub organization/repository и не создавать второй remote
repository, если этот URL доступен.

Windows SSH identity file для S13:
`<HOME>\.ssh\<SSH_IDENTITY>`. Это **private key identity
file**, не Linux username, DB user, application user или service user. Не
печатать и не документировать содержимое ключа. Approved explicit form:

```text
ssh -i <HOME>\.ssh\<SSH_IDENTITY> <S13_SSH_USER>@<S13_SSH_HOST>
```

Proven local SSH config (canonicalized 2026-10-30):

- `Host s13` is the only canonical S13 entry. It retains the already-approved
  S13 User, HostName and IdentityFile; the former `mint-lan` alias was renamed.
- 2026-11-08: after the owner confirmed the online Tailscale peer, the existing
  `Host s13` HostName was changed to that Tailscale address; the unavailable
  former LAN endpoint was removed from this canonical block. User and
  IdentityFile were preserved. `ssh s13` and the S13 Git remote were verified.
- `Host s7` is the only canonical S7 entry. Duplicate aliases `nyx`,
  `nyx-local` and `nyx-lan` were removed after machine-id verification.
- Obsolete alternate-route aliases `nyx-vpn` and `mint-vpn` were removed;
  the SSH config contains only the canonical project entries `s13` and `s7`.
- Use `ssh s13` and `ssh s7`. Do not invent another username, host, identity
  file, alias, ProxyJump or network overlay.
- Do not print HostName, addresses, usernames, or key contents in reports.

OPERATING_RULES_MATCH_REAL_SSH_CONFIG=YES

The local Git remote named `s13` uses `ssh://s13/opt/CRM_Streamlit`; do not
route it through the removed `mint-vpn` alias. This remote remains separate from
the canonical GitHub `origin`; the histories must not be merged or pushed
between one another.

## Canonical databases and technical roles

| Database | Endpoint | Runtime DB role | Meaning |
|---|---|---|---|
| CRM canonical DB | `127.0.0.1:5432/crm` on S13 | `crm_app` | application database role, не project user |
| Document intelligence | `127.0.0.1:5432/document_intelligence` on S13 | `doc_worker` | document pipeline database role, не project user |

`.env` — runtime configuration, не authority человеческой identity.
`CRM_DB_USER=crm_app` означает только PostgreSQL runtime identity. Никогда не
публиковать passwords/secrets из env-файлов.

### Ownership and DDL authority

Runtime DB role не обязана быть schema/table owner. Она может иметь DML
(`SELECT/INSERT/UPDATE/DELETE`), но не `ALTER TABLE`, `CREATE INDEX` или
`ALTER OWNER`. При `must be owner` запрещено слепо менять owner, выдавать
SUPERUSER, выбирать случайный `postgres/root` login или менять runtime role.

Обязательный порядок:

1. определить фактического owner из DB metadata;
2. найти canonical migration/admin route;
3. сообщить owner и route;
4. использовать только уже approved механизм; если он не документирован —
   остановиться с `IDENTITY_AUTHORITY_MISSING`.

Проверенные факты на 2026-08-16:

- `crm_v3_expert_annotations` существует; owner = PostgreSQL role `postgres`;
- `crm_app` не может создавать на ней индекс, потому что не owner; это не
  означает, что runtime role выбрана неверно;
- canonical CRM DDL admin route: approved SSH `<S13_SSH_USER>@S13`/S13, затем
  уже настроенный `sudo -n -u postgres psql -d crm`; этот route применяется
  только для явно разрешённого DDL, не для смены ownership;
- owner менять в рамках documentation WIP запрещено.

### DDL в `document_intelligence` и блокировки (проверено 2026-10-10)

- Owner таблицы `document_processing_queue` — роль `doc_worker`; фактический
  DDL-route для документной БД остаётся approved:
  `sudo -n -u postgres psql -d document_intelligence --single-transaction`.
- Воркеры держат таблицу очереди в состоянии **idle in transaction** (счётчик
  статусов), поэтому `ALTER TABLE` может упасть по `lock_timeout`. Порядок,
  который сработал: остановить писателей
  (`tender-docs-daemon-open`, `tender-docs-daemon-awarded`,
  `crm-v3-context-validator`), завершить `idle in transaction` бэкенды
  (`pg_terminate_backend`), применить DDL с `SET LOCAL lock_timeout`, поднять
  сервисы обратно и проверить `systemctl is-active`.
- Допустимые статусы `document_processing_queue.status` (CHECK-констрейнт):
  `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `NO_LINKS`,
  `PRE_RESEARCH_WAITING`, `SKIPPED_NOISE` (терминальный пропуск по политике
  файлов; воркеры его не клеймят — claim выбирает только `PENDING` и
  `PRE_RESEARCH_WAITING`).

### Retention и учёт файлов (2026-10-10)

- Политика: разобрали → удаляем (сырые файлы не копим). Retention-скрипт
  `tender_documents_research/scripts/document_retention_cleanup.py`
  (таймер `tender-docs-retention.timer`, `--days 3 --delete --peer-psql`)
  обязан проставлять `document_files.local_deleted_at` при фактическом
  удалении — иначе база показывает файлы, которых на диске нет (выявлено и
  вычищено: 85 009 «фантомных» записей).
- Следствие для контура: **весь разбор обязан происходить в момент парсинга**
  (`document_processor/parse_extractors.py`), потому что после retention файл
  уже не восстановить без повторного скачивания.

## Production service identity inventory

Read-only inventory получен через `systemctl show` 2026-08-16. Пустой
`User=` означает default/root systemd context; это факт, не догадка.

| Host / unit | OS_USER | Purpose | Working directory | Environment source |
|---|---|---|---|---|
| S13 `crm-streamlit.service` | `<S13_SSH_USER>` | CRM web UI | `/opt/CRM_Streamlit` | `/opt/CRM_Streamlit/.env` |
| S13 `crm-ai-assessment-runner.service` | `<S13_SSH_USER>` | V3 Candidate routing/backlog drain | `/opt/CRM_Streamlit` | `/opt/CRM_Streamlit/.env` |
| S13 `crm-v3-daily-medal-reevaluation.service` | `<S13_SSH_USER>` | deterministic medal reevaluation | `/opt/CRM_Streamlit` | `/opt/CRM_Streamlit/.env` |
| S13 `tender-docs-daemon-open.service` | `<S13_SSH_USER>` | open/new document worker | `/opt/tender_documents_research` | project `.env`, `/etc/tender-docs-db.env`, open-worker env, S13 overlays |
| S13 `tender-docs-daemon-awarded.service` | `<S13_SSH_USER>` | awarded document worker | `/opt/tender_documents_research` | project `.env`, `/etc/tender-docs-db.env`, awarded-worker env |
| S13 `ollama.service` | `<S13_SSH_USER>` | local model runtime | systemd default | no EnvironmentFile reported |
| S13 `postgresql@17-main.service` | default/root systemd context (wrapper unit) | canonical local PostgreSQL cluster | systemd default | no EnvironmentFile reported |
| S7 `postgresql@17-main.service` | default/root systemd context (wrapper unit) | source/history PostgreSQL cluster | systemd default | no EnvironmentFile reported |
| S7 `tendermonitor-eis-parser.service` | `tendermonitor` | forward EIS source parser | `/opt/tendermonitor` | no EnvironmentFile reported |
| S7 `tendermonitor-eis-parser-backward.service` | `tendermonitor` | backward source catch-up | `/opt/tendermonitor` | no EnvironmentFile reported |
| S7 `eis-stunnel.service` | `root` | CryptoPro EIS tunnel | systemd default | no EnvironmentFile reported |

Для не перечисленного unit сначала inspect actual configuration; service user
не переносится по аналогии с соседним unit.

## Approved CRM V3 application release path for reviewed hotfixes

For an explicitly reviewed change limited to:

```text
src/services/commercial_routing_v3/daily_retention.py
src/services/commercial_routing_v3/projection_writer.py
```

the approved S13 release route is the configured `ssh s13` identity and the
existing service-user-writable directory:

```text
/opt/CRM_Streamlit/src/services/commercial_routing_v3/
```

The release must:

- verify the production preimage SHA-256;
- stage reviewed bytes as sibling temporary files;
- create a timestamped preimage backup;
- run the runtime virtualenv's `py_compile`;
- atomically rename the old and staged files;
- verify live hashes, ownership/mode and a fresh-process import;
- automatically restore the backup on any failure.

Do not overwrite a root-owned target directly and do not copy a divergent local
branch file over runtime. Do not restart a running Python batch merely to load
the change; the next invocation imports the replacement. A restart requires a
separate process-model check.

This path does not authorize deletion, schema changes, service configuration,
or any file outside the two paths above.

## Owner-approved medal/category pipeline release 2026-11-12

The owner explicitly authorized release of the reviewed local medal and
post-parse category implementation on 2026-11-12. This scoped route uses the
canonical `ssh s13` identity and the existing service-owned runtime trees.

Allowed files:

```text
/opt/CRM_Streamlit/src/services/commercial_routing_v3/medal_timing.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/candidate_scoring.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/commercial_timing.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/daily_medal_reevaluation.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/medal_lineage.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/model_input.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/post_parse_category_assessment.py
/opt/CRM_Streamlit/src/services/procurement_card_dossier_service.py
/opt/CRM_Streamlit/src/services/procurement_card_category_service.py
/opt/CRM_Streamlit/src/services/category_overview_service.py
/opt/CRM_Streamlit/src/services/analytics_table_workspace_service.py
/opt/CRM_Streamlit/src/services/good_supply_facts_service.py
/opt/tender_documents_research/document_processor/crm_taxonomy_loader.py
/opt/tender_documents_research/document_processor/estimate_row_taxonomy.py
/opt/tender_documents_research/scripts/run_post_parse_category_batches.py
/opt/tender_documents_research/scripts/backfill_current_category_opportunities_from_rows.py
```

Release requirements:

- stage reviewed bytes beside each target and normalize line endings;
- record SHA-256 preimages and create a timestamped backup;
- verify the runtime virtualenv can compile/import every staged file;
- atomically replace only the allowed files;
- verify live hashes and fresh-process imports;
- restore every replaced file automatically if any verification fails.

This route does not authorize schema changes, mass deletion, service-unit
changes, or writes to any other path. Feature flags and live backfills remain
separate gates.

## Owner-approved GrandSmeta numeric parser hotfix 2026-11-12

The owner explicitly requested an urgent production correction for the
two-level GrandSmeta header after live PID `42971` showed normalized numeric
fields empty and raw quantity `5,65068493`. The scoped release allows exactly:

```text
/opt/tender_documents_research/document_processor/xlsx_table_reader.py
```

The release must use `ssh s13`, verify the preimage, stage the reviewed file
beside the target, normalize line endings, compile it with the runtime Python,
atomically replace the target, and retain a timestamped backup. Existing-row
numeric repair remains a separate hash-verified backfill gate. This route does
not authorize schema changes, a broad reparse, document downloads, queue
mutation, or service-unit changes.

## Owner-approved card category and commercial-offer split 2026-11-12

The owner explicitly requested that a category block show only rows assigned to
that category, that unclassified products move to an unassigned review block,
and that commercial offers receive a separate card tab with issuer, INN and
quoted rate. The scoped release allows exactly:

```text
/opt/CRM_Streamlit/src/services/commercial_offer_evidence_service.py
/opt/CRM_Streamlit/src/services/procurement_card_dossier_service.py
/opt/CRM_Streamlit/src/services/procurement_card_category_service.py
/opt/CRM_Streamlit/src/services/procurement_category_presentation.py
/opt/CRM_Streamlit/src/services/product_subcategory_composite_seed_data.py
/opt/CRM_Streamlit/src/services/good_supply_facts_service.py
/opt/CRM_Streamlit/src/services/composite_visibility_service.py
/opt/CRM_Streamlit/src/ui/procurement_card_page.py
```

Commercial-offer evidence must remain separate from estimate quantity and
category value. The release uses atomic replacement, timestamped preimages,
runtime compilation/import checks, and automatic rollback on failure. This
route does not authorize schema changes, category/model writes, queue changes,
document downloads, or a broad reparse.

## Owner-authorized Hydro Kanban sidecar release 2026-11-12

The owner explicitly authorized a one-time release of
`WIP_HYDRO_KANBAN_INLINE_SIDECAR_V1` after the active S13 CRM was confirmed to
serve the previous UI. This scoped route allows only:

```text
/opt/CRM_Streamlit/src/ui/waterproofing_kanban_tab.py
/opt/CRM_Streamlit/src/ui/hydro_inline_sidecar.py
/opt/CRM_Streamlit/src/ui/components/hydro_drag_drop/__init__.py
/opt/CRM_Streamlit/src/ui/components/hydro_drag_drop/index.html
```

The Kanban file on S13 is an existing untracked runtime file; preserve its
captured preimage and port the sidecar into that runtime version. Do not replace
it with a divergent working-tree version. Before release, verify the existing
CRM schema/read sources and stage all reviewed files beside their targets.
Record preimage SHA-256 values and timestamped backups, compile/import the
staged Python files with the runtime virtualenv, atomically replace only the
four listed paths, verify hashes and the CRM HTTP response, then perform one
service restart and confirm active state. Restore all preimages automatically
if any verification fails. This scoped authorization includes no DDL, DB
write, source-data change, scoring/funnel change, or release of any other file.
Store existing preimages and a checksum manifest only under
`/opt/CRM_Streamlit/backups/hydro_kanban_inline_sidecar_20261112_<HHMMSS>/`;
record absent-file preimages in the manifest. Sibling staging files must be
removed after successful verification.

## Mandatory access discovery order

1. полностью прочитать `AGENTS.md` и этот authoritative file;
2. использовать approved host/SSH configuration, указанную здесь;
3. inspect existing service/environment configuration без вывода secrets;
4. использовать подтверждённую existing identity;
5. только затем подключаться.

Нельзя начинать с перебора usernames. `docs/HOSTS.md` и service documentation
являются навигационными/операционными справками и обязаны ссылаться сюда.

## Operational fast path for AI agents

Этот раздел оптимизирует повторяющиеся операции после того, как approved
route уже определён выше. Он не расширяет identities, access или write
authority.

### SSH

- Не повторяй identity discovery на каждой операции и не перебирай
  usernames, hosts, aliases или keys.
- Если доступна persistent shell/session, переиспользуй её для связанных
  read-only команд.
- Без persistent session группируй связанные команды в один SSH invocation.
- Не изменяй SSH config ради оптимизации и не добавляй alias, ProxyJump или
  ControlMaster без отдельной необходимости и решения.

### PostgreSQL

- Несколько связанных read-only запросов выполняй одной psql-сессией или одним
  SQL batch. Для аудита допустим pattern:

```sql
BEGIN READ ONLY;

-- связанные SELECT-запросы

COMMIT;
```

- Не открывай отдельное подключение ради каждого `COUNT(*)`, если counts
  относятся к одному аудиту.
- CRM и document_intelligence остаются разными базами: не создавай фиктивную
  cross-database transaction.
- Write/DDL routes подчиняются существующим ownership, migration и approval
  правилам этого документа.

### Runtime inspection

За одну инфраструктурную задачу один раз зафиксируй baseline:

```text
host
working directory
deployed HEAD/source
dirty state
relevant service state
```

Не повторяй baseline перед каждым grep/query. Повтори его перед mutation или
deploy, либо если появился признак изменения состояния.

### Logs

Используй bounded logs: конкретный unit, ограниченное число строк и нужный
временной диапазон. Не читай весь journal без причины. Сначала ищи нужную
ошибку или событие, расширяй окно только при недостаточности первого среза.

## Owner-authorized post-parse, queue and kiosk repair release 2026-11-13

The owner explicitly requested `WIP_POST_PARSE_PERSISTENCE_QUEUE_AND_KIOSK_REPAIR_V1`
and the release of working queue/category corrections. This scoped route allows
only:

```text
/opt/tender_documents_research/document_processor/parse_extractors.py
/opt/tender_documents_research/document_processor/embedded_persistence.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/document_queue_reconciliation.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/reconciliation_document_plan.py
/opt/CRM_Streamlit/src/services/commercial_routing_v3/reconciliation_queue_writer.py
/usr/local/bin/s13_dashboard3.py
```

The release must preserve divergent production preimages, record timestamped
backups and SHA-256 preimages, compile each staged Python file with its runtime
interpreter, use atomic replacement, verify live hashes and fresh-process
imports, restart the affected document workers and kiosk service once, and
automatically restore all preimages on failure. This route authorizes no schema
migration, mass reparse, document redownload, normalization backfill,
taxonomy/medal logic change, or mass queue rewrite.

## Documentation consolidation record

На 2026-08-16 conflicting/stale access statements были найдены в
`docs/HOSTS.md`, `docs/DAEMONS_AND_MODELS.md`, корневом `README.md` и
pre-cutover readiness report. `HOSTS.md` превращён в stable pointer,
операционные документы явно подчинены этой authority, а historical report
помечен как superseded snapshot. Credentials, DB ownership и production
services в documentation WIP не изменялись.
