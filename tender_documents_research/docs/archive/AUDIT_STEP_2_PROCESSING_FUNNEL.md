# AUDIT STEP 2 — Фактическая статистика контура обработки документации

## Статус выполнения

Расчёт метрик напрямую на рабочей БД в этой сессии **не выполнен**, так как доступ к PostgreSQL недоступен по сети.

Факт проверки:
- Хост: `<S7_DB_HOST>`
- Порт: `5432`
- Результат: `psycopg2.OperationalError: connection ... failed: timeout expired`

Поэтому подготовлен файл с полным набором SQL-запросов:
- `AUDIT_STEP_2_QUERIES.sql`

---

## Перечень требуемых метрик и SQL

Ниже указано, каким запросом считать каждый показатель (те же запросы вынесены в SQL-файл).

1. **Общее количество записей в `document_processing_queue`**  
   SQL: `SELECT COUNT(*) FROM document_processing_queue;`

2. **Количество закупок по статусам `pending/processing/completed/no_links/error`**  
   SQL: группировка по `status` с фильтром по этим пяти значениям.

3. **Количество полностью завершённых закупок**  
   SQL: `WHERE status = 'completed'`.

4. **Количество закупок, оставшихся в очереди**  
   SQL: `WHERE status IN ('pending', 'processing')`.

5. **Количество обработанных файлов в `processed_documents`**  
   SQL: `SELECT COUNT(*) FROM processed_documents;`

6. **Количество файлов по статусам `completed/processing/error`**  
   SQL: группировка по `status` в `processed_documents`.

7. **Среди завершённых файлов: `is_interesting=true/false`**  
   SQL: `WHERE status='completed' GROUP BY is_interesting`.

8. **Количество записей в `tender_document_matches`**  
   SQL: `SELECT COUNT(*) FROM tender_document_matches;`

9. **Количество файлов с найденными совпадениями**  
   SQL: `WHERE COALESCE(match_count,0)>0 OR is_interesting IS TRUE`.

10. **Общее количество найденных совпадений**  
    SQL: `SUM(match_count)` (контрольный вариант: `COUNT(*)` в `tender_document_match_details`).

11. **Среднее и медианное количество совпадений на один файл**  
    SQL: `AVG(match_count)` + `PERCENTILE_CONT(0.5)`.

12. **Количество уникальных закупок с хотя бы одним совпадением**  
    SQL: `COUNT(DISTINCT tender_id, registry_type)` через подзапрос `DISTINCT`.

13. **Среднее, медианное, минимальное и максимальное `processing_time_seconds`**  
    SQL: `AVG`, `PERCENTILE_CONT(0.5)`, `MIN`, `MAX` по `tender_document_matches`.

14. **Количество результатов, успешно выгруженных на Яндекс.Диск**  
    SQL: `yandex_path IS NOT NULL AND BTRIM(yandex_path) <> ''`.

15. **Количество результатов без `yandex_path`**  
    SQL: `yandex_path IS NULL OR BTRIM(yandex_path) = ''`.

16. **Топ-10 наиболее частых `product_name`**  
    SQL: `GROUP BY product_name ORDER BY COUNT(*) DESC LIMIT 10` в `tender_document_match_details`.

---

## Что нужно сделать для получения фактических цифр

1. Выполнить `AUDIT_STEP_2_QUERIES.sql` в рабочем контуре БД `tender_monitor`.
2. Сохранить результаты выполнения (табличный вывод) и добавить их в этот отчёт.
3. При необходимости я сразу подготовлю следующий шаг: сводную таблицу метрик (с числами) и интерпретацию воронки.

