# Контур обработки закупок и светотехника (2026-07-23)

## Как сейчас работает контур

```text
Реестры 44/223/615 (tender_monitor)
        │
        ▼
1. Отбор в очередь  (регион + ОКПД + стоп-слова в названии)
   → document_processing_queue
        │
        ▼
2. Демон на sergey (10.0.0.13): tender-docs-daemon.service
   /opt/tender_documents_research
        │
        ├─ скачать links_documentation_*
        ├─ распаковать / OCR (ENABLE_OCR=1)
        └─ KeywordMatcher:
              product_catalog_2.products.name
            + user_keywords.json   ← сюда добавлена светотехника
            − document_stop_phrases
        │
        ▼
3. tender_document_matches + tender_document_match_details
        │
        ▼
4. CRM Streamlit (:8504)
   индекс объектов → карточка → AI (материалы только из реальных совпадений)
```

Очередь сейчас roughly: pending ~400+, completed ~180+, sales_window_expired много.

Профиль `lighting` в `search_profiles.json` / CRM уже есть как **маршрутизация**, но до этого шага **фразы светотехники в live-матчер не входили** — совпадений по свету в документах быть не могло.

## Что добавлено

1. `scripts/merge_lighting_keywords.py` — ~200+ уточнённых фраз (офис/пром/улица/авария/ЖКХ/VARTON…).
2. Стоп-контекст бытового мусора → `document_stop_phrases`.
3. Эвристика чипов CRM (`product_groups.py`) сужена под те же формулировки.
4. Демон перезапущен, чтобы подхватить новый `user_keywords.json`.

Голое слово «светильник» в матчер **не** кладём — только уточнённые словосочетания.
