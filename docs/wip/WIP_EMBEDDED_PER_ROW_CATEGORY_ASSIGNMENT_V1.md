# WIP EMBEDDED_PER_ROW_CATEGORY_ASSIGNMENT_V1 — категория факта по search phrases

Status: ГОТОВ К РАБОТЕ. Owner: embedded extraction / document processor.

## Проблема

Для PROJECT/OBJECT закупок `structured_entities.category_code` сейчас берётся
из `selected_documents`, а не из названия строки. Поэтому сметный документ,
помеченный как `composite_structures`, вываливает в композиты все строки:

```text
сваи, бетон, песок, арматура, опоры, земляные работы
```

Хотя категория должна определяться по поисковым фразам:

```text
composite_structures -> композитные перильные ограждения,
                        композитные водоотводные лотки,
                        стеклопластик
lighting             -> светильник, прожектор, опора освещения
```

## Цель

Каждый извлечённый факт классифицировать в категорию по
`product_name_raw` и поисковым фразам категорий/подкатегорий.

```text
category_code = best_match(product_name_raw, registry search phrases)
```

Строки без уверенного совпадения не получают категорию.

## НЕ хранить всю смету

Сейчас legacy `_persist_estimate` пишет в `structured_entities` каждую строку
сметы. Это порождает десятки тысяч нерелевантных фактов. Новый контракт:

```text
в structured_entities пишутся только строки с уверенным category match;
остальное остаётся максимум в structured_extraction_runs.source_text_snapshot;
не пишем category_code='unknown' как коммерческий факт.
```

## Правила

```text
search phrases читаются из crm_product_categories.positive_signals
  и crm_product_subcategory_terms.term_type='search'
совпадение только по названию строки, не по ОКПД
нет совпадения -> category_code='unknown'
ничего не выдумываем
DIRECT track не трогаем — там свой strict registry
```

## Кандидат в новую категорию

Сваи/шпунт требуют отдельного частотного аудита. Первичный поиск
`%сва%`/`%шпунт%` шумит сваркой и самосвалами, поэтому нужны точные
термы:

```text
свая / сваи / свай
шпунт / шпунтовое ограждение
```

## Acceptance

```text
PER_ROW_CATEGORY_FROM_SEARCH_PHRASES=YES
NO_CATEGORY_FROM_SELECTED_DOCUMENTS_FOR_EMBEDDED=YES
NO_OKPD_ONLY_CATEGORY=YES
UNKNOWN_WITHOUT_MATCH=YES
DIRECT_REGISTRY_UNCHANGED=YES
DB_WRITES=APPROVED_REPARSE_ONLY
```

## Out of scope

- изменение scoring/medal;
- DIRECT strict registry;
- массовый reparse без отдельного approval.
