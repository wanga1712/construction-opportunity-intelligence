# WIP ARCHIVE_MEMBER_BULK_RESTORE_V1 — backlog по 41714 archive-member строкам

Status: BACKLOG / НЕ СТАРТОВАН. Owner: document_intelligence.

## Контекст

Старая identity sweeper'а `(procurement_id, physical_download_key)` погасила
41714 строк, которые на самом деле являются членами архивов, а не дублями.
После `ARCHIVE_MEMBER_DEDUP_IDENTITY_V1` эти строки больше не будут гаситься,
но исторический остаток остаётся в `SKIPPED duplicate_of:*`.

Для GSFX-очереди уже восстановлены только нужные 1775 `.gsfx`-строк.

## Почему не массово сейчас

```text
восстановление 41714 строк = повторный разбор ~44k файлов;
большой риск повторного HTTP/parse-нагрузки;
не все члены архивов коммерчески нужны;
нужен батчированный dry-run и выборочный restore по категориям/маркерам.
```

## Когда стартуем

Только по отдельному явному запросу/authority, после того как текущая очередь
закрыта.

## Предполагаемые шаги

1. Read-only inventory 41714 строк по `physical_download_key`, `file_name`,
   `url_hash`, `category`/planned context.
2. Отобрать только нужные для активных category opportunities и не дубли.
3. Батчированный restore с маркером `restored_from:archive_member_bulk_restore_v1`.
4. Dry-run -> замер would-parse -> узкий force-run -> recheck sweeper idempotent.
5. Не трогать CRM/medal/queue authority.

## Acceptance (на старте)

```text
RESTORE_BATCH_BOUNDED=YES
HTTP_REQUESTS_PLANNED=KNOWN
ARCHIVE_MEMBERS_NOT_SWEPT_AGAIN=YES
TRUE_DUPLICATES_NOT_RESTORED=YES
DB_WRITES=APPROVED_ONLY
```

## Out of scope

- GSFX parser/skip-list;
- dedup identity (уже исправлена);
- queue admission;
- scoring/medals.
