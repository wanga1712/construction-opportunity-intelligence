# Карточка закупки + правильный запрос на модель (черновик v0)

Статус: **черновик для согласования**. Код-инкремент: UI-карточка
(`src/ui/procurement_card_page.py`), read-only досье
(`src/services/procurement_card_dossier_service.py`). Модель **не запускается**.

## 1. Что карточка умеет показать уже сейчас (read-only)

Источники: CRM `crm_procurements`, `crm_procurement_category_opportunities`,
`crm_objects_index`; DI `document_files`, `document_matches`,
`document_match_details`.

| Секция | Поля | Источник |
|---|---|---|
| Реквизиты | №, название, закон (44/223), стадия, статус, регион, ОКПД, ссылка на закупку | crm_procurements |
| Стороны | заказчик (+источник/уверенность), подрядчик/поставщик (имя+ИНН), победитель (имя+ИНН), балансодержатель | crm_procurements, crm_objects_index |
| Деньги/сроки | НМЦК, публикация, приём заявок до, исполнение с/по | crm_procurements |
| Категории/медаль | категория, подкатегория, трек, статус, confidence, prelim/current медаль, score, action | crm_procurement_category_opportunities |
| Документы | файл, тип, статус скачивания, есть URL, есть локальная копия, дата скачивания, ошибка | document_files |
| Находки | термин, метод, score, provenance, строка, matched_text, файл | document_match_details/matches/files |

Двойной клик по закупке в левой колонке открывает досье справа.

## 2. Что НЕ показано (осознанно, пока нет источника/контракта)

- нет отдельного поля «балансодержатель» в `crm_procurements` — берём из
  `crm_objects_index` (может отсутствовать);
- «что можно скачать по одной ссылке по очереди» — пока только список файлов с
  флагом `has_url`; очередь скачивания живёт в document-контуре;
- нет inline-редактирования (карточка read-only).

## 3. Что сейчас не так в запросе на модель (второй проход)

Send-путь: `src/services/second_pass_evidence.py` →
`src/services/second_pass_prompt_v2.py` → `qwen2.5:7b`
(`v4_second_pass_category_semantics_7b_v1`) → `normalizer.py`.

Проблемы (по коду):

1. **Нет фильтра provenance.** `extract_evidence_snippets` берёт топ-50 деталей
   по score без `provenance_status`. В промпт попадут `INVALID` и
   `LEGACY_UNVERIFIED` — то есть недоказуемые совпадения (pid64/pid203).
2. **Вход = `matched_term` + `row_data`** (нормализованный лейбл + фрагмент), а
   не проверенный `source_span`/`matched_text`.
3. **Нет category admission** перед отправкой — гейт стоит только в scoring и
   project document admission.
4. **Нет project-ветки набора кандидатов** — `crm_stage='torgi' AND
   award_status='submission_open'`; awarded/EMBEDDED-проекты не попадают.

## 4. Предлагаемый контракт запроса (v1)

Кандидаты (что вообще отправлять):
```
provenance_status = 'VERIFIED'                         -- обязательно
AND has_admissible_category_signal                      -- категорийный гейт
AND (DIRECT: medal IN (GOLD,SILVER) AND remaining_ratio >= 0.80)
AND (PROJECT: track=EMBEDDED_MATERIAL AND project_end > today)
```

Полезная нагрузка (на один вызов модели):
```
proc_meta:   id, contract_number, auction_name, customer, okpd_code, law, stage
doc_stats:   document_count, processed, evidence_count
evidence[]:  {document_name, location(page:row), rule_term, matched_text,
              source_span, match_method, provenance_status, score}
subjects[]:  найденные в span сущности (товар/материал/квалификатор)
```

Правила, уже зашитые в промпт (сохранить): только relevance
`STRONG|MODERATE|WEAK|NONE`; цена/НМЦК не подаётся; ОКПД не доказательство;
каждый уровень кроме NONE обязан опираться на цитату.

Выход: `object_classification`, `category_evaluations[]`
(`category_code`, `relevance_level`, `evidence_refs[]`, `positive/negative_signals`),
`commercial_exclusions[]`, `found_facts[]`. Валидация — существующий
`normalizer.py` (отсев ОКПД-как-категории, coercion трека, снятие медалей модели).

## 6. Changelog 2026-10-09 (реализовано и задеплоено)

- **Карточка закупки** (`src/ui/procurement_card_page.py`,
  `src/services/procurement_card_dossier_service.py`): компактная шапка, 6 KPI,
  шкала окна, вкладки `Обзор | Документы | Находки | Что можно поставить |
  История/Модель | Очередь`; отображаемый статус — read-model
  (`_display_status`): «Идут торги / Подведение итогов / Победитель определён /
  Ожидает исполнения / Идёт исполнение / Исполнено», для контракта шкала —
  период исполнения с пометкой «по плановым датам».
- **Таблица закупок** (`src/ui/analytics_table_workspace_page.py`,
  `src/services/analytics_table_workspace_service.py`): группировка по закупке
  (`<details>`), 6 колонок в строке категории, пагинация по закупкам,
  приоритет GOLD → SILVER → BRONZE → WOOD → документы → свежесть → статус →
  дата (в SQL), шкала окна в шапке группы, ссылка «карточка ↗».
- **Ручные категории** (`src/services/manual_category_service.py`): хранилище —
  `crm_manual_category_overrides`; добавление, удаление, `set_manual_medal`
  (быстрая смена медали по категории), дедуп; медаль группы учитывает ручные
  override. Авто-классификация не меняется.
- **Данные из S7**: добавлены и заполнены `trading_platform`, `source_status`,
  `delivery_address`, `guarantee_amount`, `warranty_size`
  (`src/migrations/crm_procurements_card_fields_1.sql`, бэкфилл 234 256 закупок).
- **Документный контур**: фикс падения на `uq_canonical_source_file_gen`
  (`tender_documents_research/document_processor/backends/state_repository.py`).

## 5. Открытые вопросы к заказчику

1. Что для карточки первично: список документов + находок (есть сейчас) или
   ещё и «какие товары/материалы можно поставить» (нужен extraction/point 1)?
2. Нужен ли в карточке блок «можно скачать по одной ссылке» с кнопкой
   постановки в очередь (интерактив), или пока только просмотр?
3. Отправлять ли в модель только `VERIFIED` (сразу теряем ~81% legacy) или
   сначала гонять offline-recovery?
