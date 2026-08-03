# matcher — поиск ключевых слов в тексте

Файл: document_processor/matcher.py

## Метод process_text(text, line_meta=None, category_scores=None)

Принимает category_scores из contract_classifier.
Для каждого ключевого слова:
1. Определяет категорию через keyword_meta[keyword]['category_codes'][0]
2. Проверяет score категории → skip / lite / full mode
3. Lite-mode: use_strict_match=True (только regex exact match, без fuzzy)
4. Full-mode: fuzzy matching через rapidfuzz, threshold из custom_thresholds

## Env

CLASSIFIER_SKIP_THRESHOLD=1 (пропуск)
CLASSIFIER_LITE_THRESHOLD=4 (lite-mode ниже этого)

## Бекапы

matcher.py.bak_20260731_001556 — до интеграции classifier
matcher.py.bak_20260731_lite — до добавления lite-mode
