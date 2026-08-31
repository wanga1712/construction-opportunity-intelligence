# Отчёт о состоянии системы — 2026-07-31 13:07

**Проверку провёл:** Claude Sonnet 4.6  
**Дата:** 2026-07-31  
**Ошибок на момент проверки: НЕТ**

---

## Сервер 13 (<S13_SSH_USER> / S13) — Linux Mint

| Параметр | Значение | Статус |
|---|---|---|
| CPU темп | 56°C (предел 80°C) | OK |
| GPU темп | 60°C | OK |
| RAM | 10 ГБ / 31 ГБ | OK |
| Load average | 2.08 / 8 (26%) | OK |
| Ночное выключение | ОТКЛЮЧЕНО | OK |
| Авто-выключение при перегреве | 80°C > 10 мин → shutdown | OK |

### Демоны обработки документов

| Сервис | worker_id | Статус |
|---|---|---|
| tender-docs-daemon-open | 13 | active |
| tender-docs-daemon-open-2 | 15 | active |
| tender-docs-daemon-open-3 | 16 | active |
| tender-docs-daemon-awarded | 14 | active |
| tender-docs-daemon-awarded-2 | 17 | active |

Все 5 демонов включены в autostart (enabled).  
Ollama qwen2.5:7b: работает на localhost:11434

---

## Сервер 7 (<S7_SSH_USER> / S7) — PostgreSQL

| Параметр | Значение | Статус |
|---|---|---|
| БД tender_monitor | 4.79 ГБ | OK |
| pending в очереди | 585 | OK |
| no_links | 673 | ждут ссылок от парсера |
| completed | 237 | OK |
| sales_window_expired | 1475 | окно продаж закрыто |
| error | 0 | OK |
| contract_category_scores (LLM кеш) | 272 контракта | OK |

---

## Что сделано в этой сессии

### LLM Pre-classifier (Ollama qwen2.5:7b)
- contract_classifier.py — классифицирует контракт перед обработкой, ставит оценки 0-10 для 11 товарных категорий
- Кеш в таблице contract_category_scores — повторный вызов мгновенный
- Lite-mode: категории с оценкой 1-3 проходят только точное совпадение (без fuzzy)
- Skip: категории с оценкой < 1 пропускаются полностью
- Реальный результат: дорога/мост — 8/11 категорий только exact match, 52% ключевых слов быстрее
- Preclassify 600 pending контрактов: запущен в фоне на сервере 13 (/tmp/preclassify2.log)
- Env переменные: CLASSIFIER_SKIP_THRESHOLD=1, CLASSIFIER_LITE_THRESHOLD=4

### Параллельность: 5 демонов вместо 2
- Добавлены: open-2 (worker 15), open-3 (worker 16), awarded-2 (worker 17)
- Ожидаемый прирост: с 20 до ~50 закупок/день (+150%)
- Env файлы: /etc/tender-docs-worker-open-2.env, /etc/tender-docs-worker-open-3.env, /etc/tender-docs-worker-awarded-2.env
- RAM на воркер: ~71 МБ фактически, лимит 6 ГБ

### Температурный мониторинг
- /usr/local/bin/temp_shutdown_guard.sh — каждую минуту (crontab root)
- CPU >= 80°C более 10 минут → принудительное выключение + запись в daemon_alerts
- Ночной таймер выключения (worker-shutdown.timer) — ОТКЛЮЧЁН

### Бекапы (настроены 2026-07-31)
- DB: воскресенье 02:00 — pg_dump — rsync на сервер 13
- Код 7→13: воскресенье 02:30
- Код 13→7: воскресенье 14:00
- Скрипт: <HOME>/weekly_backup.sh
- SSH ключ сервера 7 добавлен в authorized_keys на сервере 13

### Автоматическая очередь
- no_links re-check: каждый день 06:00 — /usr/local/bin/requeue_no_links.sh
- Проверяет, появились ли ссылки у контрактов без документов, переводит в pending

### Алерты на ошибки
- 3 ошибки скачивания подряд — запись в daemon_alerts (уже реализовано в daemon.py, строки 254-261)

### Документация
- README_analytical_daemons_Mint13_v5.md задеплоен:
  - /opt/tender_documents_research/README_analytical_daemons.md (сервер 13)
  - /opt/tender_documents_research/README_analytical_daemons.md (сервер 7)
  - /opt/tendermonitor/README_analytical_daemons.md (сервер 7)

### Предыдущая сессия (2026-07-30)
- Split-tunnel VPN на сервере 13 (был full-tunnel — прямой доступ к zakupki.gov.ru восстановлен)
- VACUUM FULL links_documentation_44_fz: 7606 МБ → 194 МБ, удалено 23.4М орфанов
- contracts_migration.py переписан с архивированием ссылок
- CRM: daemon_alerts UI, get_system_alerts(), acknowledge_alert()

---

## Что осталось сделать

### HIGH
- CRM — настройки категорий: UI для ручной корректировки оценок классификатора
- docs/ структура: README на каждый демон, .md на каждую таблицу (по SONNET_MEMORY_MODULE_DOCUMENTATION.md)
- UUID миграция: перейти на procurement_uuid / contract_uuid как стабильный ключ (риск: повторение потери 22.5М ссылок)

### MEDIUM
- Self-learning демоны: category_object_observations, learned_category_patterns, association_lift, динамический effective_priority
- Anchor search daemon — дешёвый первичный поиск перед полным
- Opportunity ranker — медали GOLD/SILVER/BRONZE/WOOD
- Personal relevance service — персональный рейтинг для менеджеров

### LOW / МОНИТОРИНГ
- Проверить завершение preclassify (/tmp/preclassify2.log на сервере 13)
- Проверить code sync 7→13 (<HOME>/backup.log на сервере 7)
- Воздушное охлаждение сервера 13 (сейчас водяное)

---

*Следующий отчёт: следующая сессия работы или после недельного прогона демонов*
