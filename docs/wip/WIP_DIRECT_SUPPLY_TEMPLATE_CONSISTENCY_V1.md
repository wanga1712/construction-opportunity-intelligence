# WIP DIRECT_SUPPLY_TEMPLATE_CONSISTENCY_V1 — отдельные правила DIRECT и PROJECT/OBJECT

Status: PHASE 3 PERSIST DONE (2026-10-25).
Owner: document processor + commercial routing.

## Проблема

Сейчас DIRECT-закупки и проектно-объектные закупки проходят через один и тот же
generic extractor. Для отдельных простых кейсов это случайно работает, но
согласованности нет:

- `467984` «Поставка светильников светодиодных»: raw matcher 24, а
  `structured_entities` 0;
- в других DIRECT-кейсах появляются выдуманные факты без обязательной пары
  `quantity + unit`;
- шаблоны выбираются по имени файла/формату, а не по
  `category + track + document_class + format`;
- lifecycle и отображение в CRM для DIRECT и PROJECT/OBJECT не разделены.

## Разделение контуров

### DIRECT_SUPPLY

```text
короткий коммерческий цикл:
  документ -> факты -> current opportunity

после закрытия приёма заявок:
  НЕ переводим в проектно-объектный follow-up
  НЕ показываем как «разыгранные» в CRM в том же смысле, что объектные
  НЕ заводим отдельный медальный lifecycle
```

### PROJECT / OBJECT

```text
EMBEDDED_MATERIAL
DESIGN_REQUIREMENT
DESIGN_INFLUENCE

это отдельный lifecycle:
  проектная документация -> смета -> объектные факты
  свои медали и current_effective lifecycle
```

## Правила шаблонов

Ключ шаблона:

```text
(commercial_category_code, opportunity_track, document_class, формат)
```

Примеры:

```text
lighting + DIRECT_SUPPLY + TECH_SPEC + docx
lighting + DIRECT_SUPPLY + TECH_SPEC + xlsx
computers + DIRECT_SUPPLY + TECH_SPEC + docx
computers + DIRECT_SUPPLY + PRODUCT_SPECIFICATION + xlsx
flooring + DIRECT_SUPPLY + ESTIMATE + xlsx
cable_support_systems + DIRECT_SUPPLY + TECH_SPEC + docx
```

Обязательные правила факта:

```text
quantity_value обязателен
unit_normalized обязателен
price/total только через arithmetic proof
без quantity+unit факт не пишется
никаких fallback-догадок из ОКПД при отсутствии реальной строки
```

## Что нужно сделать

1. Ввести реестр DIRECT-шаблонов по ключу выше.
2. Отделить DIRECT-факты от PROJECT/OBJECT-фактов на уровне `direct_runtime`.
3. Сделать первые шаблоны:

```text
lighting DOCX/XLSX
computers DOCX/XLSX
flooring XLSX
cable_support_systems DOCX/XLSX
```

4. Прогнать не одну закупку, а все похожие DIRECT-кейсы по категориям.
5. Для каждой категории сделать dry-run и strict validation до записи.

## Phase 1 — реализовано

- добавлен `direct_template_registry.py` со строгим ключом
  `(category_code, DIRECT_SUPPLY, document_class, format)`;
- первые шаблоны: lighting DOCX/XLSX, computers TECH_SPEC DOCX/XLSX и
  PRODUCT_SPECIFICATION XLSX, flooring ESTIMATE XLSX,
  cable_support_systems TECH_SPEC DOCX/XLSX;
- `document_class` протянут из `selected_documents` через daemon →
  pipeline → parse_extractors → direct_runtime;
- generic fallback полностью отключён для DIRECT;
- DIRECT fact создаётся только при наличии `quantity_value` и
  нормализованного unit;
- price/total остаются только при arithmetic proof и `CONSISTENT`;
- в Analytics вкладка «Разыгранные» больше не принимает DIRECT;
- commercial portal разделяет `OPEN`, `AWARDED_FOLLOWUP`,
  `CLOSED_DIRECT`; требование `AWARDED_DIRECT_IN_LIVE_MARKET=0`
  выполняется.

Read-only dry-run по всем текущим DIRECT-парам:

```text
CURRENT_DIRECT_PAIRS=1 322
DOCUMENTS_CHECKED=187
TEMPLATE_SUPPORTED=89
TEMPLATE_UNSUPPORTED=98
STRICT_FACTS_CURRENT_DIRECT=5 041
HISTORICAL_FACTS_MISSING_QTY=751
HISTORICAL_FACTS_MISSING_UNIT=945
```

Поддержанные документы:

```text
lighting TECH_SPEC docx            11
computers TECH_SPEC docx           72
computers TECH_SPEC xlsx            3
cable_support_systems TECH_SPEC docx 3
flooring ESTIMATE xlsx              0 selected documents
```

Strict synthetic canary:

```text
VALID_ROW: qty=10 PCS price=100 total=1000 CONSISTENT -> KEPT
ROW_WITHOUT_UNIT                                -> DROPPED
UNSUPPORTED_DOCUMENT_CLASS                      -> 0 facts
STRICT_CANARY=PASS
```

Lifecycle live-check:

```text
AWARDED_DIRECT_IN_LIVE_MARKET=0
open_awarded_closed_direct_eq_universe=true
DIRECT_NOT_SHOWN_AS_OBJECT_RAZYGRANYE=YES
```

Исторический canary `467984` пока не может пройти на реальном файле:
`document_files.local_path` сохранён, но файл удалён retention'ом.
Нужен out-of-order download перед фактическим reparse.

## Remaining

1. После отдельного approval — reparse/persist 156 strict facts.
2. 751/945 исторических malformed facts не переписывать без этого apply.
3. После сохранения удалить временно скачанные raw files по штатному
   retention/cleanup.

## Phase 2 — download + fact dry-run

Live inventory вырос с исходных 89 до 94 supported contexts:

```text
SUPPORTED_CONTEXTS=94
UNIQUE_SOURCE_DOCUMENTS=92
```

Out-of-order download через штатный DownloadCoordinator:

```text
DOWNLOAD_APPLY=92/92
DOWNLOADED=92
FAILED=0
ERRORS=0
NO_URL=0
```

Fact-only dry-run без `structured_entities` persistence:

```text
DOCUMENTS_PRESENT=94
DOCUMENTS_MISSING=0
DOCUMENTS_WITH_FACTS=46
DOCUMENTS_WITHOUT_FACTS=48
STRICT_FACTS=156
  cable_support_systems=16
  computers=123
  lighting=17
FACTS_MISSING_QTY=0
FACTS_MISSING_UNIT=0
FACTS_BAD_PRICE_PROOF=0
FAILURES=0
```

Исходный canary `467984`:

```text
Светильник светодиодный ДСП45-50-023 Liner Р RD 840
qty=100 PCS
price/total=NULL
CANARY_467984=PASS
```

Для merged-header DOCX добавлено безопасное восстановление trailing
`unit + quantity`; строки без unit всё равно отбрасываются.

Контроль отсутствия записи:

```text
STRUCTURED_FACTS_BEFORE=5 041
STRUCTURED_FACTS_AFTER=5 041
HISTORICAL_MISSING_QTY=751 (не изменено)
HISTORICAL_MISSING_UNIT=945 (не изменено)
STRUCTURED_ENTITIES_WRITES=0
```

## Phase 3 — canary + persist

Canary `467984`:

```text
before structured_entities=0
after structured_entities=1
product_name_raw=С ветильник светодиодный ДСП45-50-023 Liner Р RD 840
qty=100 PCS
unit_normalized=PCS
price/total=NULL
```

Полный approved persist:

```text
items=94
created=68
reused=88
before_global structured_facts=362414
after_global structured_facts=362482
missing_qty=93722 (без изменений)
missing_unit=84772 (без изменений)
```

Исторические malformed facts не переписывались.

Acceptance:

```text
CANARY_PERSIST_OK=YES
ALL_SUPPORTED_DIRECT_FACTS_PERSISTED=YES
STRUCTURED_ENTITIES_WRITES=APPROVED_STRICT_FACTS
HISTORICAL_FACTS_UNCHANGED=YES
```

## Phase 3b — расширение supported templates

Добавлены strict-шаблоны:

```text
TECH_SPEC pdf для lighting/computers/cable_support_systems
PRODUCT_SPECIFICATION docx для computers
NMCK_JUSTIFICATION xlsx для computers/lighting
```

Повторный download + dry-run:

```text
supported documents=124
documents_with_facts=47
strict_facts=160
facts_missing_qty=0
facts_missing_unit=0
facts_bad_price_proof=0
```

Persist:

```text
created=4
reused=156
structured_facts 362482 -> 362486
missing_qty=93722 (без изменений)
missing_unit=84772 (без изменений)
```

Оставшиеся unsupported классы (`CONTRACT_PROJECT`, `LEGAL_GENERAL`,
`PARTICIPANT_REQUIREMENTS`, `OTHER`, архивы) требуют отдельного решения:
некоторые из них принципиально не должны давать товарные факты.

## Phase 3c — классификация unsupported

Введены явные классы:

```text
MUST_SKIP:
  LEGAL_GENERAL
  PARTICIPANT_REQUIREMENTS
  OTHER

DEFERRED_ARCHIVE:
  zip / rar / 7z
```

Добавлены supported-шаблоны:

```text
CONTRACT_PROJECT docx/pdf
NMCK_JUSTIFICATION pdf
```

Live audit:

```text
SUPPORTED=135
MUST_SKIP=44
DEFERRED_ARCHIVE=8
```

Повторный download/dry-run/persist:

```text
documents=142
documents_with_facts=49
strict_facts=163
created=1
reused=162
structured_facts 362486 -> 362487
missing_qty/unit без изменений
```

## Acceptance

```text
DIRECT_AND_PROJECT_TEMPLATES_SEPARATED=YES
TEMPLATE_KEY_CATEGORY_TRACK_CLASS_FORMAT=YES
DIRECT_NO_FOLLOWUP_AWARDED_LIFECYCLE=YES
DIRECT_NOT_SHOWN_AS_OBJECT_RAZYGRANYE=YES
PROJECT_OBJECT_HAS_OWN_MEDAL_LIFECYCLE=YES
STRUCTURED_FACTS_HAVE_QTY_AND_UNIT=YES_FOR_NEW_DIRECT
NO_PRICE_WITHOUT_ARITHMETIC_PROOF=YES
NO_INVENTED_FACTS=YES
ALL_SIMILAR_DIRECT_PROCUREMENTS_RECHECKED=DOWNLOAD_AND_DRYRUN_YES
FACT_REPARSE=PENDING_APPROVAL
DB_WRITES=DOWNLOAD_METADATA_ONLY
STRUCTURED_ENTITIES_WRITES=0
```

## Out of scope

- изменение scoring/medal threshold;
- изменение S7 parser;
- массовый reparse PROJECT/OBJECT без отдельного WIP.
