# task_pipeline — оркестратор обработки задачи

Файл: document_processor/task_pipeline.py

## Порядок обработки одной задачи

1. contract_classifier.classify(contract_number, table_source) → category_scores
2. Скачивание документов (download_task_files)
3. Извлечение текста (extract_text / OCR)
4. matcher.process_text(text, line_meta, category_scores=category_scores)
5. Запись результатов в tender_document_matches, tender_document_match_details

## Fallback

При ошибке classifier → category_scores = {} (полный поиск по всем категориям).
