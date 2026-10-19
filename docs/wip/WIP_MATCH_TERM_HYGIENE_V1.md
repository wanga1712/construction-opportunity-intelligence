# WIP MATCH_TERM_HYGIENE_V1 — чистим ложные термины находок

Status: ПРИОРИТЕТ / ГОТОВ К РАБОТЕ. Owner: document matching / card findings.

## Проблема

`document_match_details` даёт ложные VERIFIED-находки из общих документов
(заявка участника, порядок оценки), а не из сметы/ТЗ.

Пример 678 · № 0830500000226002090:

```text
waterproofing: ввод коммуникаций, примыкание, мембрана, мастика
lighting:      производствен, прожектор, операцион, управлен, проспект
composite:     солидтех
```

Все эти 14 деталей имеют `matched_text` из «Заявка на участие в закупке…»,
поэтому не являются коммерческими материалами.

## Цель

1. Очистить поисковые термины категорий от общих/участнических слов.
2. Не показывать в находках матчи из документов участника/оценки.
3. В «Что можно поставить» выводить только нормализованные товарные факты из
   `structured_entities`:

```text
материал | кол-во | ед. | цена | сумма | характеристики | quote | раздел
```

## Фазы

### Phase 0 — inventory ложных терминов

Для каждой активной категории собрать `matched_term` из `document_match_details`,
сгруппировать по источнику документа. Выделить:

```text
общие слова (управлен, операцион, производствен, проспект)
участнические слова (заявк, декларац, солидтех)
неоднозначные термины (мастика, мембрана)
```

### Phase 1 — чистка поисковых терминов

Убрать/деактивировать ложные термины в реестре/поисковых профилях категорий.
`мастика`, `мембрана` не удаляем слепо: они могут быть реальными материалами,
но должны находиться только в смете/ТЗ, а не в заявке.

### Phase 2 — source filter для находок

Матчи принимаются только из документов-источников:

```text
смета, ведомость объёмов работ, ТЗ, спецификация, расчёт НМЦК
```

Документы участника/оценки/порядка рассмотрения не дают находок.

### Phase 3 — подключение good_supply_facts

«Что можно поставить» использует `good_supply_facts_service`, а не сырые
`document_match_details`.

## Acceptance для 678

```text
FALSE_TERMS_IN_FINDINGS=0
MASTIKA_SHOWN_ONLY_IF_IN_ESTIMATE_WITH_QTY_PRICE=YES
PROJECTOR_FALSE_POSITIVE=0
SUPPLY_FACTS_FROM_STRUCTURED_ENTITIES=YES
SOURCE_QUOTE_PRESENT=YES
DB_WRITES=0_UNTIL_CLEANUP_APPROVED
```

## Out of scope

- scoring/medal/queue admission;
- section template rollout;
- `.xls` parser;
- DIRECT-компьютеры.

## RESULT (2026-10-19) — source-filter находок

РЕАЛИЗОВАНО:

```text
new: src/services/match_source_filter.py
  classify_match_source(file_name) -> RESEARCHABLE | NON_RESEARCHABLE | UNKNOWN
  NON_RESEARCHABLE: требования к содержанию/составу/заявке, инструкция по,
                    порядок рассмотрения/оценки, критерии оценки, протокол,
                    разъяснение, жалоба.
  RESEARCHABLE:     смета, ЛСР, локальная смета, ведомость, спецификация,
                    ТЗ, расчёт/обоснование НМЦК, дефектная ведомость, КС-2/3.

procurement_card_dossier_service:
  findings фильтруются по source_class; NON_RESEARCHABLE скрываются,
  в counts.findings_hidden_non_researchable пишется счётчик.
document_queue_progress_service:
  counts находок в таблице закупок считаются с тем же фильтром.
UI: в технической истории показывается «Скрыто матчей из
    требований/оценки/протоколов: N».
```

ПРОВЕРКА 678 · № 0830500000226002090 (read-only):

```text
было: 14 VERIFIED-матчей из «Требования к содержанию_ составу заявки…»,
      включая прожектор / проспект / управлен / операцион / производствен /
      солидтех / мастика / мембрана;
стало: findings=0, hidden_non_researchable=14, false_terms=0;
       analytics findings_count(678)=0 (было 14);
       карточка: categories=5, findings=0, RENDER_OK.
```

ACCEPTANCE:

```text
FALSE_TERMS_IN_FINDINGS=0                 = YES (678)
PROJECTOR_FALSE_POSITIVE=0                = YES
SOURCE_FILTER_APPLIED_TO_CARD             = YES
SOURCE_FILTER_APPLIED_TO_TABLE_COUNTS     = YES
RAW_MATCHES_DELETED                       = NO (строки в БД сохранены)
MASTIKA_SHOWN_ONLY_IF_IN_ESTIMATE...      = по мере data; в 678 не показывается
DB_WRITES                                 = 0
SCORING_MEDAL_QUEUE_UNCHANGED             = YES
```
