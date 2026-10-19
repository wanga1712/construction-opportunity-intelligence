# WIP EMBEDDED_ESTIMATE_PARSE_FIRST_V1 — сначала смета, потом остальное

Status: ПРИОРИТЕТ / СПЕКА. Owner: document selection + embedded parsing.

## Цель

Для OBJECT / EMBEDDED_MATERIAL не качать все документы и не искать категорию
везде. Сначала разбираем смету:

```text
скачать Excel/сметные файлы
-> распарсить
-> определить разделы
-> найти в разделах материалы/категории
-> если категория подтверждена в смете, записать section-принадлежность
-> только потом решать, нужны ли дополнительные документы
```

Если в смете категория не подтверждена — дальше документы не качаем.

## Правила

```text
ESTIMATE_FIRST=YES
NO_BROAD_DOWNLOAD_BEFORE_ESTIMATE_CONFIRMATION=YES
SECTION_MEMBERSHIP_RECORDED=YES
CATEGORY_CONFIRMED_BY_SECTION=YES
OBJECT_SECTION_TITLE_COMPARED_WITH_PROCUREMENT=YES
PRELIMINARY_MEDAL_REVALIDATED=YES
DB_WRITES=APPROVED_ONLY
```

## Фазы

### Phase 0 — inventory current selection

Read-only: для объектных закупок посмотреть, какие документы сейчас выбираются
первыми и сколько лишних скачивается до сметы.

### Phase 1 — selection: estimate first

В plan selection приоритет:

```text
.xlsx/.xlsm/.xls сметы/расчёты/ВОР
```

Остальные документы — только после подтверждения категории в смете или по
явному model-driven запросу.

### Phase 2 — section-aware parse

При разборе сметы:

- определить разделы;
- писать `section_code`/`section_name`;
- искать материалы только внутри разделов;
- фиксировать, к какому разделу относится найденный материал.

### Phase 3 — object/section matching

Сравнивать:

```text
название объекта/раздела из сметы
с title закупки / ОКПД / object classification
```

Это уточняет принадлежность категории и предварительную медаль.

### Phase 4 — medal revalidation

Пересчитать preliminary medal по существующей authority после section-level
подтверждения. Не менять scoring thresholds.

## Acceptance

```text
ESTIMATE_SELECTED_FIRST=YES
NO_ALL_DOCS_BEFORE_SECTION_CONFIRMATION=YES
SECTIONS_RECORDED=YES
CATEGORY_ONLY_FROM_CONFIRMED_SECTION=YES
OBJECT_SECTION_COMPARED_WITH_TITLE=YES
PRELIMINARY_MEDAL_REVALIDATED=YES
SCORING_THRESHOLDS_UNCHANGED=YES
```

## Out of scope

- DIRECT_SUPPLY queue;
- TORGI queue;
- category discovery promotion;
- scoring/medal logic changes.

## RESULT (2026-10-19) — Phase 0/1/3 + dry-run Phase 4

### Phase 0 — inventory (read-only)

```text
текущие планы с PARTICIPANT_REQUIREMENTS как FALLBACK: 129 procurements
из них в PENDING: 0 (исторические планы уже завершены)
причина: plan builder передавал СЫРОЙ opportunity_track
         («EMBEDDED_MATERIAL»/«DIRECT_SUPPLY») в category_plan(), а политика
         ключуется по GROUP_* («EMBEDDED»/«DIRECT»). Lookup промахивался,
         accepted-class policy отключалась, выбирался fallback:
         сначала CONTRACT_PROJECT, затем PARTICIPANT_REQUIREMENTS.
```

### Phase 1 — estimate first (реализовано)

```text
queue_plan_v2:
  units[category] теперь хранит НОРМАЛИЗОВАННУЮ группу (track_group(...)),
  а не сырой opportunity_track.

document_needs_plan_v2:
  EMBEDDED_ESTIMATE_CLASS_PRIORITY:
    ESTIMATE -> NMCK_JUSTIFICATION -> BOQ -> MATERIAL_SPECIFICATION ->
    PROJECT_DOCUMENTATION -> WORKING_DOCUMENTATION -> TECH_SPEC ->
    PRODUCT_SPECIFICATION;
  для EMBEDDED выбранный estimate-класс скачивается первым;
  остальные accepted-документы получают
  DEFERRED_UNTIL_SECTION_CONFIRMATION и НЕ скачиваются;
  NMCK_JUSTIFICATION принимается как estimate-класс (обоснование НМЦК);
  EMBEDDED fallback order: NMCK_JUSTIFICATION -> CONTRACT_PROJECT -> ...
  -> PARTICIPANT_REQUIREMENTS (последний, известный источник ложных терминов);
  план отдаёт deferred_documents/deferred_source_document_ids
  (в БД не пишутся — второй проход пересобирает их из document_files).
```

Проверка плана на реальных данных (read-only):

```text
60467: selected 1 -> 8 (все NMCK/расчёты), deferred 20 (ПСД/rar)
678:   selected PARTICIPANT_REQUIREMENTS -> NMCK_JUSTIFICATION, deferred 3
       (ТЗ, проектная документация zip/rar)
45848: selected PARTICIPANT_REQUIREMENTS -> 3 ESTIMATE PDF (СМ1/СМ2/СМ4),
       deferred 12
1157:  selected ESTIMATE xlsx (без изменений)
```

### Phase 2 — section-aware parse

Секции уже пишутся (`section_detector` 2A, road 2B, lighting 3A).
Estimate-first теперь гарантирует, что первым парсится именно смета.

### Phase 3 — object/section comparison (реализовано, read-only)

```text
new: src/services/object_section_match_service.py
  сравнение section_name с title закупки / ОКПД / object classification;
  state: MATCHED | PARTIAL | NO_MATCH | NO_DATA; overlap + score.
dossier:
  object_classification (crm_procurement_object_classifications, is_current);
  categories[].section_confirmed / section_codes / object_match;
  object_section_matches (по каждому разделу).
UI: в блоке категории — «Подтверждено разделом …» / «Вне раздела (RESIDUE)»
    и «объект: MATCHED/PARTIAL/NO_MATCH».
```

Проверка:

```text
60467: waterproofing section_confirmed=True (ПСК::глава 1/4/6/7/12);
       road::Лист1::razdel 3 «Дорожная одежда» -> MATCHED (overlap «дорожная»)
       с title «капитальный ремонт а/д … дорог».
678:   секций нет -> NO_DATA/NO_MATCH, section_confirmed=False.
```

### Phase 4 — dry-run пересчёта confirmed_base (НЕ применено)

`scripts/audit_estimate_first_confirmation.py` (read-only):

```text
CURRENT_OPPORTUNITIES=7983
GOODS_FACTS_TOTAL=14027
GOODS_FACTS_IN_SECTION=22      (0.2%)
GOODS_FACTS_RESIDUE=14005
OPPORTUNITIES_WITH_SECTION_FACTS=1
CONFIRMED_BASE_WOULD_LOSE=522
CONFIRMED_BASE_DISTRIBUTION={'BRONZE': 1}
DB_WRITES=0
```

ВЫВОД: включать «подтверждение только разделом» сейчас нельзя — оно обнулит
522 из 523 подтверждённых категорий, потому что секции есть только у 0.2%
товарных фактов. Сначала нужен rollout section detection на категории
(curbstone/drainage/flooring/...), затем повторный dry-run и только потом
apply (отдельным approval).

ACCEPTANCE (текущий этап):

```text
ESTIMATE_SELECTED_FIRST=YES
NO_ALL_DOCS_BEFORE_SECTION_CONFIRMATION=YES
DEFERRED_DOCUMENTS_RECORDED=YES (в плане; в БД не пишутся)
SECTIONS_RECORDED=YES (2A/2B/3A)
CATEGORY_ONLY_FROM_CONFIRMED_SECTION=НЕ ПРИМЕНЕНО
  (read-model флаг section_confirmed=YES; запись confirmed_base не менялась)
OBJECT_SECTION_COMPARED_WITH_TITLE=YES
PRELIMINARY_MEDAL_REVALIDATED=DRY_RUN_ONLY
SCORING_THRESHOLDS_UNCHANGED=YES
DB_WRITES=0
```
