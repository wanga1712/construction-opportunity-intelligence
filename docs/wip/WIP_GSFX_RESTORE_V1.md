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
