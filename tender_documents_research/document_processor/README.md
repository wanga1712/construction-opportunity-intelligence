# Document Processor — README модуля

> Сервер 13 · `/opt/tender_documents_research/document_processor/`  
> Обновлён: 2026-08-04

---

## 1. Назначение

Скачивает, парсит и классифицирует документы тендеров из реестров 44-ФЗ и 223-ФЗ.  
Главная цель — **GOLD-охота**: найти закупки с ранним сроком и объёмом выше медианы по категории.

---

## 2. Архитектура воркеров

| Сервис systemd | Worker ID | Лэйны очереди | Назначение |
|---|---|---|---|
| `tender-docs-daemon-open` | 13 | `crm_active_hot`, `open_active` | Новые 44/223-ФЗ |
| `tender-docs-daemon-open-2` | 15 | `crm_active_hot`, `open_active` | Новые 44/223-ФЗ |
| `tender-docs-daemon-open-3` | 16 | `crm_active_hot`, `open_active` | Новые 44/223-ФЗ |
| `tender-docs-daemon-awarded` | 14 | `awarded_recent`, `historical_awarded` | Разыгранные |
| `tender-docs-daemon-awarded-2` | 17 | flex (open→awarded) | Flex: open если есть, иначе awarded |

### Планируемые (не реализованы)
| Сервис | Worker | Лэйны | Назначение |
|---|---|---|---|
| `tender-docs-daemon-computers` | 18 | `computers_okpd` | ОКПД компьютеры/ИТ only |
| `tender-docs-daemon-computers-2` | 19 | `computers_okpd` | ОКПД компьютеры/ИТ only |

---

## 3. Система приоритетов (лэйны)

Порядок обслуживания (меньше = выше):

```
1. crm_active_hot      — CRM-карточки с открытой подачей / пользовательский буст
2. open_active         — все новые закупки (кроме computer-OKPD)
3. awarded_recent      — разыгранные (до 90 дней)
4. retry               — повтор после ошибки
5. historical_awarded  — старые разыгранные
```

Внутри лэйна: `priority_score DESC → submission_end_at ASC → id ASC`

---

## 4. Классы приоритета (P0–P4)

Назначаются до скачивания документов (`queue_priority_calculator.py`):

| Класс | Баллы | Обработка |
|---|---|---|
| P0 | 85–100 | Немедленно |
| P1 | 70–84 | После P0 |
| P2 | 50–69 | Обычная |
| P3 | 25–49 | Слабый кандидат |
| P4 | 0–24 | Закрытая подача / архив |

**Формула:** `commercial_scale + category_prob + deadline_feasibility + title_specificity + hist_gold + customer_region + aging_bonus - penalties`

---

## 5. GOLD-карта — определение

GOLD = ранний дедлайн + объём выше медианы по категории.

```
predicted_gold_probability = f(commercial_scale, deadline_feasibility, category_confidence, hist_gold)
```

- Медиана `initial_price` по категории считается за скользящее окно
- Ежедневный пересчёт в 06:00 (`PriorityRecalculator.run_full_sweep()`)
- Aging bonus: +1 балл каждые 24 ч ожидания, макс +10

---

## 6. CRM Bridge (`crm_queue_bridge.py`)

Запускается каждый час (`CRM_BRIDGE_INTERVAL_SEC`, default 3600).

1. Читает `crm_tender_match_cache` → JOIN с реестрами 44/223
2. Вставляет/обновляет `document_processing_queue`
3. Лэйн: `crm_active_hot` если подача открыта + `match_score ≥ 6` + `remaining ≥ required`

---

## 7. ТЗ-экстракция (ПЛАНИРУЕТСЯ)

**Условие:** ОКПД начинается с `71` (проектирование) ИЛИ название содержит все три: `проект` + `заключение` + `работы`

**Действие:** Дополнительно ставить в очередь связанный тендер на ТЗ (поиск по ИНН заказчика + ключевые слова).  
Модуль: `tz_extractor.py` (не реализован).

Применяется к обоим потокам: новые + разыгранные.

---

## 8. Петля обратной связи (ПЛАНИРУЕТСЯ)

Пользователь в CRM может отметить закупку как приоритетную → запись в `crm_priority_feedback`:
- `CrmQueueBridge` читает feedback → поднимает `priority_score` + лэйн до `crm_active_hot`
- Накопленные данные → переобучение scoring-модели (замена `v1_formula`)

Таблица `crm_priority_feedback` не создана.

---

## 9. Боты для ОКПД «Компьютеры» (ПЛАНИРУЕТСЯ)

- Два отдельных воркера (18/19), только таблица «новые», только компьютерный ОКПД
- Основные боты (13/15/16) **исключают** этот ОКПД
- Логика: скачать ТЗ → Qwen7B формирует спецификацию товаров → в CRM-карточку

---

## 10. Ключевые файлы

| Файл | Назначение |
|---|---|
| `daemon.py` | Главный цикл, инициализация, расписание |
| `queue_manager.py` | Populate, claim, purge; лэйны и приоритеты |
| `queue_claim.py` | SQL-claim с `FOR UPDATE SKIP LOCKED` |
| `queue_priority_calculator.py` | Формула P0-P4, `PriorityInput/Result` |
| `priority_recalculator.py` | Ежедневный пересчёт всех pending-строк |
| `crm_queue_bridge.py` | CRM → document_processing_queue |
| `document_downloader.py` | Скачивание, checksum, архивы |
| `document_parser.py` | Текст, таблицы, OCR |

---

## 11. База данных (сервер 7, БД tender_monitor)

**Основная таблица:** `document_processing_queue`

Ключевые колонки приоритетов:
- `queue_lane` — лэйн (`crm_active_hot` / `open_active` / ...)
- `priority_class` — P0-P4
- `priority_score` — 0-100, основная сортировка
- `predicted_gold_prob` — вероятность GOLD-карты
- `deadline_slack` — `remaining_workdays - required_workdays`
- `submission_end_at` — дедлайн подачи

**Индекс для claim:**
```sql
CREATE INDEX ix_dpq_lane_claim ON document_processing_queue 
USING btree (status, queue_lane, priority_score DESC, submission_end_at, id)
WHERE status='pending';
```

---

## 12. Переменные окружения воркеров

| Переменная | Описание |
|---|---|
| `WORKER_ID` | ID воркера (13-17) |
| `QUEUE_LANES` | Лэйны через запятую (напр. `crm_active_hot,open_active`) |
| `QUEUE_LANES_FLEX` | `1` = flex-режим (worker 17) |
| `QUEUE_TABLE_SOURCES` | Фильтр по table_source (не применяется когда задан QUEUE_LANES) |
| `CRM_BRIDGE_INTERVAL_SEC` | Интервал CRM bridge (default 3600) |

---

## 13. SSH доступ

```bash
# Прямо на сервер 13 через прокси сервер 7
ssh -i ~/.ssh/<SSH_IDENTITY> -o ProxyJump=<S7_SSH_USER>@S7 <S13_SSH_USER>@S13

# Логи воркера
journalctl -u tender-docs-daemon-open.service -n 50 --no-pager

# Рестарт
sudo systemctl restart tender-docs-daemon-open.service
```
