# tender_documents_research — карта документного контура

Актуальность карты: **2026-10-25**. Канонические хосты, БД, роли, service
identities и порядок доступа описаны только в
[`docs/PROJECT_OPERATING_RULES.md`](../docs/PROJECT_OPERATING_RULES.md).
Число активных workers и размер очереди являются runtime-метриками и
намеренно не фиксируются в README.

## Назначение

Контур получает задания из `document_processing_queue`, скачивает и проверяет
файлы, разбирает поддерживаемые форматы, извлекает текст/таблицы/факты, ищет
категорийные сигналы и сохраняет evidence с provenance. Сырые файлы имеют
ограниченный retention, поэтому извлечение выполняется во время парсинга.

## Структура

| Путь | Назначение |
|---|---|
| `document_processor/daemon.py` | Главный цикл worker |
| `document_processor/queue_*.py` | Populate, priority, claim и lifecycle очереди |
| `document_processor/downloader.py` | Загрузка документов и архивов |
| `document_processor/parser_factory.py`, `document_processor/parsers/` | Парсеры PDF, Office, text и таблиц |
| `document_processor/parse_extractors.py` | Синхронные hooks извлечения при парсинге |
| `document_processor/matching/` | Нормализация, поиск и provenance совпадений |
| `document_processor/structured_fact_*.py` | Контракт, извлечение и запись структурированных фактов |
| `document_processor/backends/` | Репозитории очереди, состояния и результатов |
| `document_processor/pipelines/` | Оркестрация актуального pipeline |
| `migrations/` | Миграции document intelligence DB |
| `scripts/` и `tools/` | Эксплуатационные команды и CLI |
| `tests/` | Локальные контракты document runtime |
| `docs/modules/` | Подробности отдельных legacy-модулей |
| `docs/archive/` | Исторические отчёты, не источник текущей истины |

Полное описание связей с CRM, зависимостей и результаты статического аудита:
[`docs/PROJECT_OVERVIEW_AND_AUDIT.md`](../docs/PROJECT_OVERVIEW_AND_AUDIT.md).

## Установка зависимостей

```bash
python -m pip install -r tender_documents_research/requirements.txt
```

Конкретный запуск workers выполняется только по текущему WIP и утверждённым
systemd units/drop-ins. Наличие unit-файла в репозитории не подтверждает, что
он установлен или активен в production.
