# tender_documents_research — карта модулей

> Canonical hosts, operators, SSH/DB/service identities and access rules:
> [docs/PROJECT_OPERATING_RULES.md](docs/PROJECT_OPERATING_RULES.md). Этот
> README описывает компоненты и не является authority доступа.

Сервер 13 (sergey / 10.8.0.13). Обрабатывает документы из очереди document_processing_queue на сервере 7.

## Статус (2026-07-31 13:07) — ошибок нет

| Параметр | Значение |
|---|---|
| Демонов активно | 5 (worker 13,14,15,16,17) |
| Pending в очереди | 585 |
| Completed | 237 |
| CPU темп | 56°C / порог 80°C |
| RAM | 10 / 31 ГБ |

## Модули

| Модуль | Назначение | README |
|---|---|---|
| daemon | Главный цикл: захват задач, скачивание, обработка | docs/modules/daemon/README.md |
| contract_classifier | LLM pre-classifier (Ollama qwen2.5:7b), оценки 0-10 для 11 категорий | docs/modules/contract_classifier/README.md |
| matcher | Поиск ключевых слов в тексте, fuzzy/exact/lite-mode | docs/modules/matcher/README.md |
| task_pipeline | Оркестратор: classifier → downloader → extractor → matcher | docs/modules/task_pipeline/README.md |
| queue_manager | Захват задач из БД (SKIP LOCKED), смена статусов | docs/modules/queue_manager/README.md |

## Сервисы systemd

| Сервис | worker_id | Источник |
|---|---|---|
| tender-docs-daemon-open | 13 | reestr_contract_44_fz, reestr_contract_223_fz |
| tender-docs-daemon-open-2 | 15 | reestr_contract_44_fz, reestr_contract_223_fz |
| tender-docs-daemon-open-3 | 16 | reestr_contract_44_fz, reestr_contract_223_fz |
| tender-docs-daemon-awarded | 14 | reestr_contract_44_fz_awarded |
| tender-docs-daemon-awarded-2 | 17 | reestr_contract_44_fz_awarded |

Env файлы: `/etc/tender-docs-worker-*.env` и `/etc/tender-docs-db.env`

## БД

PostgreSQL на 10.8.0.7, база `tender_monitor`. Таблицы: docs/database/tables/

## Архив старых документов

docs/archive/ — устаревшие AUDIT_*, STATUS_*, SUMMARY_* файлы

## Что нужно сделать

- CRM: UI настройки категорий классификатора
- docs/modules/ — наполнить READMEs фактическими данными
- UUID миграция ключей (риск потери ссылок)
- Self-learning демоны (README_analytical_daemons.md раздел 15)
