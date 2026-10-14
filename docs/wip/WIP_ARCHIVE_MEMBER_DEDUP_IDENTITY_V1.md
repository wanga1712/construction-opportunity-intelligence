# WIP ARCHIVE_MEMBER_DEDUP_IDENTITY_V1 — dedup-sweeper не гасит члены архива

Status: СПЕКА / ПРИОРИТЕТ ПЕРЕД GSFX-добивкой. Owner: document_intelligence.

## Проблема

`scripts/neutralize_duplicate_document_files.py` партиционирует дубликаты по
`(procurement_id, physical_download_key)`. При распаковке архива дочерние файлы
получают тот же `physical_download_key`, что и родительский архив:

```text
download → «Сметная документация.zip» (parent)
extract → «....gsfx» и другие члены архива
ensure_download_file(child):
    canonical_source_document_id = None
    physical_download_key = phys_key(parent)
```

Поэтому часовой sweeper считает parent и всех членов архива «одним физическим
документом» и гасит `.gsfx`/другие члены как `duplicate_of:<parent>`.

Это не GSFX-специфичный баг: он затронет любой архив с несколькими извлечёнными
файлами. Но GSFX_RESTORE_V1 первый это вскрыл.

## Правильная identity

Физический файл внутри закупки должен различать члены архива. Минимально:

```text
(procurement_id, physical_download_key, COALESCE(file_name, ''))
```

Либо более устойчиво — `COALESCE(url_hash, file_name, '')`, потому что
`url_hash` у parent и child разный. Решение зафиксировать в SQL и в
`state_repository.ensure_download_file` / downloader.

Важно не вернуть исходный баг «NULL в canonical_source_document_id позволяет
бесконечные дубли»: partition-key должен быть непустым и уникальным для
повторных строк того же файла.

## Задачи

1. Read-only inventory: найти все группы `(procurement_id, physical_download_key)`,
   где более одного `file_name`/`url_hash`; отделить true duplicates от
   archive members.
2. Изменить `SWEEP_SQL` в
   `scripts/neutralize_duplicate_document_files.py` на identity с
   `file_name` (или `url_hash`), сохранив survivor-правило:
   `local_path IS NOT NULL` first, else `min(id)`.
3. Убедиться, что `ACTIVE_DUP_SQL` использует ту же identity.
4. Прогнать dry-run на S13; ожидаемо neutralized_now должен быть 0 для уже
   чистых групп, но больше не гасить `.gsfx` и прочие archive members.
5. Перегнать/восстановить уже погашенные GSFX-строки:
   `download_status='PENDING'`, снять `error_message='duplicate_of:...'`
   обратимо и с маркером `restored_from:archive_member_dedup_identity_v1`.
6. Обновить WIP_GSFX_RESTORE_V1 и зафиксировать evidence.

## Acceptance

```text
ARCHIVE_MEMBERS_NOT_SWEPT_AS_DUPLICATES=YES
TRUE_DUPLICATES_STILL_SWEPT=YES
SWEEPER_IDEMPOTENT=YES
ROWS_PHYSICALLY_DELETED=0
GSFX_ROWS_RESTORED=127284..127290 (или актуальный набор)
B_HTTP_REQUESTS=0
```

## Out of scope

- Схемный unique index `(procurement_id, physical_download_key, file_name)`
  пока не добавляем: сначала sweeper должен поработать.
- CRM/medal/queue.
- GSFX parser и skip-list.

## RESULT (2026-10-14)

STATUS: DONE

EVIDENCE (read-only inventory + S13 apply):

```
-- identity выбрана по данным: url_hash различает членов архива, file_name — нет
группа proc 459462 / key 062e42bd8c: 6349 строк, 6349 distinct url_hash, 5118 distinct file_name
под identity (proc, key, coalesce(url_hash,file_name,'')): истинных dup-групп 6 (12 строк), ACTIVE 0
под старой (proc, key): нейтрализованных строк 41725, из них 41714 с другим file_name, чем survivor

-- код (scripts/neutralize_duplicate_document_files.py)
SWEEP_SQL/ACTIVE_DUP_SQL теперь партиционируют по
  (procurement_id, physical_download_key, coalesce(url_hash, file_name, ''))
md5 sweeper локально == S13: 2d990eadfcb2afca083187e52226ca02
backup на S13: neutralize_duplicate_document_files.py.bak-archive-identity-20261014

-- новый обратимый restore: scripts/restore_archive_member_dedup_rows.py
md5 локально == S13: 4672714b04db229326d989ace068f88c
dry-run:  candidates_before=1775 (26 закупок)
--apply:   restored_now=1775, candidates_after=0
маркер: error_message='restored_from:archive_member_dedup_identity_v1; prev=duplicate_of:<n>'

-- sweeper больше не гасит членов архива
neutralize --apply x2: {"active_duplicate_groups_before":0,"neutralized_now":0,"active_duplicate_groups_after":0}
.gsfx по статусам: PENDING 1775 (все); 127287/127289 = PENDING

-- контраст old vs new identity (read-only, status<>SKIPPED)
old identity would-sweep = 1775   (это ровно восстановленные .gsfx)
new identity would-sweep = 0
-- истинные дубли ещё ловятся: rank>1 под новой identity (все статусы) = 6; url_hash-групп 6 (по 2 строки)
```

ACCEPTANCE:

```
ARCHIVE_MEMBERS_NOT_SWEPT_AS_DUPLICATES = YES (new would-sweep=0; .gsfx остались PENDING)
TRUE_DUPLICATES_STILL_SWEPT            = YES (identity с url_hash; 6 dup-групп детектируются)
SWEEPER_IDEMPOTENT                     = YES (двойной --apply: neutralized_now=0)
ROWS_PHYSICALLY_DELETED                = 0
GSFX_ROWS_RESTORED                     = 1775 (26 закупок; включает 127287/127289)
B_HTTP_REQUESTS                        = 0
```

DEVIATIONS:

- Identity взята с `url_hash`, а не с одним `file_name`: `file_name` даёт коллизии
  (5118 distinct на 6349 строк в группе 459462), `url_hash` — 6349 distinct. Формула
  `coalesce(url_hash, file_name, '')` покрывает оба случая.
- Restore ограничен `.gsfx` (по решению F1), но под старой identity погашено **41714**
  строк с другим file_name (члены архивов по всей БД). Их массовое восстановление в
  PENDING = повторный разбор ~44k файлов — вынесено на отдельное решение, не делалось здесь.

FOLLOW-UP:

- Решить судьбу остальных 41714 archive-member строк (отдельный WIP/решение).
- 1B (ARCHIVE_MEMBER_PARSE_CONTEXT_V1) — чтобы восстановленные `.gsfx` дошли до сущностей.
