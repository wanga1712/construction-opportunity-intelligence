# contract_classifier — LLM pre-classifier

Файл: document_processor/contract_classifier.py

## Что делает

Перед обработкой документов вызывает Ollama qwen2.5:7b (localhost:11434).
Передаёт: auction_name + OKPD2 код.
Получает: JSON с оценками 0-10 для 11 товарных категорий.
Кеширует в БД: таблица contract_category_scores (contract_number, category_code, score).

**Важно: классификатор НЕ пропускает контракты.** Он только устанавливает приоритеты поиска для каждой категории. Контракт всегда обрабатывается полностью (task_pipeline.py не делает early return по оценкам).

## 11 категорий

flooring, lighting, waterproofing, waterproofing_concrete_repair, drainage_water_management, cable_support_systems, composite_structures, concrete_materials, bridge_road_infrastructure, external_utility_networks, structural_reinforcement

## Как использовать результат (matcher.py)

- score < 1 (CLASSIFIER_SKIP_THRESHOLD, default=1, не задан в env) → поиск по ключевым словам этой КАТЕГОРИИ пропускается (continue в цикле — не весь контракт)
- score 1-3 (< CLASSIFIER_LITE_THRESHOLD=4, default) → только exact matching для этой категории (lite-mode)
- score 4-10 → полный fuzzy matching для категории

Порог CLASSIFIER_SKIP_THRESHOLD=1 означает: только категории с оценкой 0 (совсем не релевантны) пропускают поиск. Оценки 1+ — обрабатываются.

## Кеш

Таблица contract_category_scores: ~8382 контрактов кешировано (2026-08-03).
classified_by = llm (авто) или human (ручная правка через CRM UI — не реализовано).

## Что ещё не реализовано

- CRM UI для просмотра и ручной правки оценок категорий
- Авто-подхват категорий из БД в промпт (сейчас хардкод CATEGORY_DESCRIPTIONS в коде)
