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
| S13 | `10.8.0.13`, alias `mint-vpn`; CRM, Candidate routing, Qwen/Ollama, document intelligence runtime, canonical CRM DB | primary operator and OS user `sergey`; `ssh sergey@mint-vpn` or `ssh sergey@10.8.0.13` |
| S7 | `10.8.0.7`, hostname `nyx`; source/history authority, source procurement data and source lifecycle/status | approved OS user `wanga`; `ssh wanga@10.8.0.7` |

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
`C:\Users\Lenovo\Projects\canonical_repo`. Remote `github` указывает на
canonical GitHub URL; existing remote `origin` указывает на S13 monorepo.
Не угадывать GitHub organization/repository и не создавать второй remote
repository, если этот URL доступен.

Windows SSH identity file для S13:
`C:\Users\Lenovo\.ssh\id_ed25519_codex_worker`. Это **private key identity
file**, не Linux username, DB user, application user или service user. Не
печатать и не документировать содержимое ключа. Approved explicit form:

```text
ssh -i C:\Users\Lenovo\.ssh\id_ed25519_codex_worker sergey@10.8.0.13
```

Локальный SSH config отдельно содержит approved alias `mint-vpn` с
`HostName 10.8.0.13` и `User sergey`; команда через alias использует identity,
уже назначенную этому alias в SSH config. Не подменять и не угадывать её.

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
- canonical CRM DDL admin route: approved SSH `sergey@mint-vpn`/S13, затем
  уже настроенный `sudo -n -u postgres psql -d crm`; этот route применяется
  только для явно разрешённого DDL, не для смены ownership;
- owner менять в рамках documentation WIP запрещено.

## Production service identity inventory

Read-only inventory получен через `systemctl show` 2026-08-16. Пустой
`User=` означает default/root systemd context; это факт, не догадка.

| Host / unit | OS_USER | Purpose | Working directory | Environment source |
|---|---|---|---|---|
| S13 `crm-streamlit.service` | `sergey` | CRM web UI | `/opt/CRM_Streamlit` | `/opt/CRM_Streamlit/.env` |
| S13 `crm-ai-assessment-runner.service` | `sergey` | V3 Candidate routing/backlog drain | `/opt/CRM_Streamlit` | `/opt/CRM_Streamlit/.env` |
| S13 `crm-v3-daily-medal-reevaluation.service` | `sergey` | deterministic medal reevaluation | `/opt/CRM_Streamlit` | `/opt/CRM_Streamlit/.env` |
| S13 `tender-docs-daemon-open.service` | `sergey` | open/new document worker | `/opt/tender_documents_research` | project `.env`, `/etc/tender-docs-db.env`, open-worker env, S13 overlays |
| S13 `tender-docs-daemon-awarded.service` | `sergey` | awarded document worker | `/opt/tender_documents_research` | project `.env`, `/etc/tender-docs-db.env`, awarded-worker env |
| S13 `ollama.service` | `sergey` | local model runtime | systemd default | no EnvironmentFile reported |
| S13 `postgresql@17-main.service` | default/root systemd context (wrapper unit) | canonical local PostgreSQL cluster | systemd default | no EnvironmentFile reported |
| S7 `postgresql@17-main.service` | default/root systemd context (wrapper unit) | source/history PostgreSQL cluster | systemd default | no EnvironmentFile reported |
| S7 `tendermonitor-eis-parser.service` | `tendermonitor` | forward EIS source parser | `/opt/tendermonitor` | no EnvironmentFile reported |
| S7 `tendermonitor-eis-parser-backward.service` | `tendermonitor` | backward source catch-up | `/opt/tendermonitor` | no EnvironmentFile reported |
| S7 `eis-stunnel.service` | `root` | CryptoPro EIS tunnel | systemd default | no EnvironmentFile reported |

Для не перечисленного unit сначала inspect actual configuration; service user
не переносится по аналогии с соседним unit.

## Mandatory access discovery order

1. полностью прочитать `AGENTS.md` и этот authoritative file;
2. использовать approved host/SSH configuration, указанную здесь;
3. inspect existing service/environment configuration без вывода secrets;
4. использовать подтверждённую existing identity;
5. только затем подключаться.

Нельзя начинать с перебора usernames. `docs/HOSTS.md` и service documentation
являются навигационными/операционными справками и обязаны ссылаться сюда.

## Documentation consolidation record

На 2026-08-16 conflicting/stale access statements были найдены в
`docs/HOSTS.md`, `docs/DAEMONS_AND_MODELS.md`, корневом `README.md` и
pre-cutover readiness report. `HOSTS.md` превращён в stable pointer,
операционные документы явно подчинены этой authority, а historical report
помечен как superseded snapshot. Credentials, DB ownership и production
services в documentation WIP не изменялись.
