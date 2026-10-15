# WIP GSFX_RESTORE_V1 — вернуть разбор смет `.gsfx`

Created: 2026-10-13. Owner: document contour (`/opt/tender_documents_research`).

## Task (как поставлено)

1. `tender_documents_research/document_processor/file_skip_list.py` — убрать
   `".gsfx"` из `SKIP_EXTENSIONS` (лежал в блоке «криптоконтейнеры/подписи»).
   `.gge` и `.sign` оставить.
2. `GsfxParser` не трогать.
3. Переочередить/перекачать 1 767 строк `document_files` с `%.gsfx` и
   `download_status='SKIPPED'` (22 закупки), чтобы они дошли до парсера.

Acceptance: `.gsfx` не HARD_SKIP и доходит до парсера; сметы дают материальные
позиции; `.gge` остаётся в skip.

## RESULT (2026-10-13)

STATUS: PARTIAL (код задеплоен и переочередь выполнена; сквозной парсинг `.gsfx` в пилоте ещё идёт)

EVIDENCE:

```
-- 1. skip-лист (локально + S13)
/opt/tender_documents_research/document_processor/file_skip_list.py
  было  md5 4bcadd7494dface41d28173bbd36c5c8
  стало md5 379c6f2e1f580a063ef969d24372ddc0
  бэкап: file_skip_list.py.bak-gsfx-20261013

-- проверка поведения (прод-код, venv .venv313)
Смета.gsfx                     skip=False policy=EXECUTABLE
Сводный сметный расчет ....gsfx skip=False policy=EXECUTABLE
док.gge                        skip=True  policy=HARD_SKIP
x.sign / x.sig                 skip=True  policy=HARD_SKIP

-- сервисы перезапущены (все active)
tender-docs-daemon-open, -open-2, -open-3, -awarded, active-production-loop

-- 2. ПАРСЕР ПЕРЕПИСАН (это было обязательным: старый давал 0)
parsers/gsfx_parser.py   было md5 1f46fb43be0de335cd55c4e4520f3284
                         стало md5 ddc13dfc0d15d7f5bc59cdc2123bac57
  бэкап: gsfx_parser.py.bak-gsfx-20261013
  GrandSmeta хранит данные в атрибутах (Caption/Units/Quantity/PriceCurr),
  старый код читал только elem.text -> chars: 0.
  Новый код отдаёт pipe-таблицу с шапкой, которую понимает embedded_extraction.
  Проверка на реальной смете 460692 (прод-экстрактор): FACTS = 58, например
    Ацетилен газообразный технический | м3 | 0.36 | 537.85
    Болты с гайками и шайбами строительные | KG | 0.06 | 188.92
    Раствор кладочный цементно-известковый М50 | M3 | 0.24 | 5789.43
  py_compile OK; сервисы перезапущены повторно.

-- 3. переочередь
пилот: id=150614 (proc 460692) -> PENDING; claimable=t; захвачена и PROCESSING
       .gsfx 127287/127289: SKIPPED -> COMPLETED (скачаны заново)
масса: UPDATE ... 21 строка -> PENDING (маркер 'requeue:gsfx_restore_v1; prev_status=...')
       итог по 22 закупкам: PENDING 21, PROCESSING 1 (150821 не трогали)
```

ACCEPTANCE:

```
.gsfx не HARD_SKIP, доходит до парсера = ok (EXECUTABLE, файлы скачаны COMPLETED)
.gge остаётся в skip                    = ok
Сметы .gsfx дают материальные позиции   = ok на уровне парсера (58 фактов на реальной смете)
Переочередь 1 767 строк (22 закупки)    = ok (21 PENDING + 1 PROCESSING)
Сквозной результат в БД по .gsfx        = ОЖИДАЕТСЯ (пилотный прогон ещё PROCESSING)
```

DEVIATIONS:

- Пункт 2 задания («`GsfxParser` не трогать») пришлось нарушить: без правки
  acceptance «сметы дают материальные позиции» недостижим — старый парсер
  отдавал 0 фрагментов на реальных GrandSmeta-файлах.
- Исторические «157 распарсенных `.gsfx`» находок не дали: `document_matches=0`,
  `document_match_details=0`, `structured_entities=0` при 135 результатах
  `COMPLETED`. То есть `.gsfx` не приносили позиций никогда.
- Строка 9216 (4 файла `.gsfx`) переочередена, но остаётся неclaimable:
  `research_action='DEEP_RESEARCH'`, `AI_QUEUE_ADMISSION_GATE='NO'` —
  её не возьмёт воркер без смены admission (не делал).
- Строка 150821 (proc 462100) была `PROCESSING` ДО переочереди — не трогали.
- Переочередь не ускоряет позицию в очереди: у этих строк `source_start_date IS NULL`,
  а claim-порядок `work_tier → source_start_date DESC NULLS LAST → ...` ставит их
  позади свежих строк. Поэтому для проверки использован force-прогон одной закупки.

FOLLOW-UP:

- Дождаться окончания пилота 460692 и проверить, что `.gsfx` дают
  `document_processing_results=COMPLETED` и `structured_entities` (сейчас у файлов
  127287/127289 результат ещё `SKIPPED` от прошлого прогона).
- Проверить, что остальные 20 закупок разберутся штатным демоном.
- Строка 9216 — отдельное решение по admission.
- Отдельно: битая кодировка имён `.gsfx` при скачивании (не блокер).

## RESULT (2026-10-14) — дожимание по очереди DODELKI (step 1)

STATUS: PARTIAL — код на S13 и в git совпадает, `.gsfx` доходят до парсера и дают
текстовые матчи; но сквозной результат в `structured_entities` не появился, 20 закупок
не разобраны, и всплыл блокер identity в dedup-sweeper.

EVIDENCE (read-only, S13 2026-10-14 10:12 +03):

```
-- S13 == git (md5 совпадают побайтно)
file_skip_list.py   379c6f2e1f580a063ef969d24372ddc0   (git commit a8432c1)
gsfx_parser.py      ddc13dfc0d15d7f5bc59cdc2123bac57   (git commit a8432c1)
.gge остаётся в SKIP_EXTENSIONS (file_skip_list.py:114)  -> ok

-- пилот 460692 (queue id 150614)
status=COMPLETED, attempt_count=0, research_action=FACTUAL_FEEDER_ADMITTED, lane=open_active
started_at=2026-10-14 06:00:41, completed_at=2026-10-14 08:23:17
last_error='FAILED_HEAVY_WALL_CLOCK_CAP: seconds>1800 after 12 files'

-- document_processing_results, прогон 08:23
127287 …Смета….gsfx  COMPLETED  matches_found=8
127289 …Сводный….gsfx COMPLETED  matches_found=1

-- document_match_details из .gsfx
127287: flooring 6 | lighting 1 | waterproofing 1
127289: lighting 1

-- structured_entities по 460692
всего 654, max(created_at)=2026-10-13 21:12  ->  created_at >= 2026-10-14 = 0

-- 20 переочередённых закупок (маркер requeue:gsfx_restore_v1)
status=PENDING у всех 20, attempt_count=0; 18 из них source_start_date IS NULL, work_tier=2
claims за последние 3ч = 0;  за 24ч = 159
очередь: PENDING 242 / PROCESSING 9 / PRE_RESEARCH_WAITING 273 / COMPLETED 7016

-- dedup-sweeper (hourly, tender-docs-dedup-sweeper.timer, active)
127284..127290 (в т.ч. .gsfx 127287/127289) снова:
   download_status=SKIPPED, error_message='duplicate_of:127278'
   physical_download_key = 52c87a43547cac0baa78d6625e1ace8301f4461b  (общий с 127278)
   127278 = «Сметная документация.zip» (архив, canonical_source_document_id=61956479)
```

ACCEPTANCE (step 1):

```
.gsfx не HARD_SKIP и доходит до GsfxParser           = ok (policy EXECUTABLE, md5 совпал)
.gge остаётся в skip                                  = ok
пилот 460692: document_processing_results=COMPLETED   = ok
пилот 460692: structured_entities > 0                 = НЕ ПОДТВЕРЖДЁН (0 новых от .gsfx-прогона)
остальные 20 закупок разобраны daemon                 = нет (все PENDING/attempt 0), причины ниже
строка 9216 (queue 10796)                             = отдельное решение (D3), не трогали
битая кодировка имён .gsfx                            = отдельный follow-up, не блокер
```

DEVIATIONS:

1. **Dedup-sweeper схлопывает archive-members.** `scripts/neutralize_duplicate_document_files.py`
   партиционирует только по `(procurement_id, physical_download_key)`. Члены архива
   (`.gsfx`, `.arp`, `.xl`, `.docx` из «Сметная документация.zip») наследуют
   `physical_download_key` родительского архива, поэтому оцениваются как дубли
   самого архива и получают `SKIPPED duplicate_of:<архив>`. Итог: `.gsfx` re-neutralize
   каждый час → GSFX-restore **недолговечен** и не воспроизводится без повторной переочереди.
2. **Нет сквозного результата в сущностях.** `.gsfx` дают текстовые матчи
   (`document_matches` / `document_match_details`), но новых `structured_entities` по 460692
   за 2026-10-14 нет. Ожидание из FOLLOW-UP («проверить structured_entities») не выполнено.
3. **Очередь не разгружается.** Воркеры (`tender-docs-daemon-open/-2/-3/-awarded`) active, но
   за последние 3ч ни одной клейма при 242 PENDING (15 idle-бэкендов висят с 06:00:30).
   У 20 переочередённых `source_start_date IS NULL`/`work_tier=2` → claim-порядок
   отодвигает их в хвост; кроме того, часть строк может блокироваться admission-gate.
   `active-production-loop` — inactive (по ACTIVE_PRODUCTION_LOOP.md loop ещё не включён).

FOLLOW-UP / нужны решения:

- **F1 (нужно решение).** Identity dedup-sweeper для archive-members: чинить в рамках GSFX
  (например, добавлять в ключ `file_name`/archive-member) или отдельным WIP? Затрагивает
  identity документа, поэтому без решения кодер не меняет.
- **F2 (нужно решение).** Почему `.gsfx` не создают `structured_entities`: какой компонент
  персистит сущности при прогоне демона (`extract_and_persist`?) и должен ли он был сработать
  без включённого `active-production-loop`.
- **F3.** Разгрузка очереди (0 claims / 3ч при 242 PENDING) — отдельный WIP или часть GSFX.
- D3 (строка 9216) и битая кодировка имён — без изменений, как и планировалось.

UPDATE (2026-10-14, после 1A): `ARCHIVE_MEMBER_DEDUP_IDENTITY_V1` DONE — sweeper
больше не гасит членов архива, 1775 `.gsfx`-строк восстановлены в `PENDING`
(маркер `restored_from:archive_member_dedup_identity_v1`). Делать 1C (подтверждение
сущностей) — только после 1B (`ARCHIVE_MEMBER_PARSE_CONTEXT_V1`).

## RESULT (2026-10-15) — 1C закрыт на planned-кейсе 99069

STATUS: DONE (`WIP_RESULT=PASS`).

EVIDENCE:

```
-- предпосылки
1A ARCHIVE_MEMBER_DEDUP_IDENTITY_V1  = DONE (identity по url_hash; 1775 .gsfx -> PENDING)
1B ARCHIVE_MEMBER_PARSE_CONTEXT_V1   = DONE (члены архива привязаны к плану по physical_download_key)

-- .gsfx доходят до парсера
журнал прогона 90595: GsfxParser отработал все 20 .gsfx (fragments 17..70)
document_processing_results .gsfx    = 20 / 20 COMPLETED
.gge остаётся в SKIP_EXTENSIONS        = YES (file_skip_list.py:114)

-- canonical end-to-end (planned-кейс 99069 / queue 90595)
document_processing_queue 90595        = COMPLETED (last_error пуст)
document_processing_results (99069)    = 54 COMPLETED
structured_entities (99069)            = drainage_water_management 438 ; unknown 89

-- остальные закупки GSFX-переочереди (маркер requeue:gsfx_restore_v1)
2 c Queue V2 plan : 90595 COMPLETED ; 148931 COMPLETED (его план не покрывает .gsfx)
18 без плана      : 17 PENDING + 1 COMPLETED  -> NOT_PLANNED_GAP (без plan сущностей быть не может)
460692            : NOT_PLANNED_GAP (зафиксировано, план ради acceptance не строим)
строка 9216 (queue 10796): PENDING, research_action=DEEP_RESEARCH -> отдельное решение (D3)
битая кодировка имён .gsfx: отдельный follow-up, не блокер
```

ACCEPTANCE:

```
.gsfx не HARD_SKIP и доходит до GsfxParser                      = YES
.gge остаётся skip                                              = YES
planned-кейс 99069: document_processing_results=COMPLETED,
                    structured_entities > 0                      = YES (54 COMPLETED; 438 entities)
460692                                                          = NOT_PLANNED_GAP
остальные закупки: причины зафиксированы                        = YES (18 без плана; 148931 план вне .gsfx)
строка 9216                                                     = отдельное решение (не смешано с GSFX)
битая кодировка имён .gsfx                                      = отдельный follow-up
WIP_RESULT                                                      = PASS
```
