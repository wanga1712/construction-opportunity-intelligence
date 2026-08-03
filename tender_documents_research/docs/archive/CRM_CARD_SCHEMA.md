# Схема данных для CRM-карточек закупок

## Концепция

Два уровня карточки:
- **Превью** — компактная карточка в списке: название, заказчик, цена, статус, найденные совпадения
- **Полная карточка** — все поля, документы, ссылки, детали совпадений

---

## Базы данных и таблицы

### БД: `tender_monitor` (хост: 100.122.104.106)

---

### 1. Реестры закупок (источники данных)

Все три таблицы имеют **идентичную структуру**:

| Таблица | Описание |
|---|---|
| `reestr_contract_44_fz` | Закупки по 44-ФЗ (активные/новые) |
| `reestr_contract_44_fz_awarded` | Закупки по 44-ФЗ (заключённые контракты) |
| `reestr_contract_223_fz` | Закупки по 223-ФЗ |

**Поля реестров 44-ФЗ:**

| Поле | Тип | Описание | Карточка |
|---|---|---|---|
| `id` | integer | PK | — |
| `contract_number` | text | Реестровый номер контракта | превью + полная |
| `tender_link` | text | Ссылка на закупку на zakupki.gov.ru | превью + полная |
| `auction_name` | text | Наименование объекта закупки | превью + полная |
| `initial_price` | numeric | Начальная (максимальная) цена | превью + полная |
| `final_price` | numeric | Итоговая цена контракта | превью + полная |
| `guarantee_amount` | numeric | Размер обеспечения | полная |
| `warranty_size` | numeric | Размер гарантийных обязательств | полная |
| `start_date` | date | Дата начала закупки | полная |
| `end_date` | date | Дата окончания закупки | полная |
| `delivery_start_date` | date | Дата начала поставки/исполнения | превью + полная |
| `delivery_end_date` | date | Дата окончания поставки/исполнения | превью + полная |
| `delivery_region` | text | Регион поставки | полная |
| `delivery_address` | text | Адрес поставки | полная |
| `customer_id` | integer | FK → `customer.id` | — |
| `customer` | text | Краткое название заказчика (денормализовано) | превью |
| `contractor_id` | integer | FK → `contractor.id` | — |
| `trading_platform_id` | integer | FK → `trading_platform.id` | полная |
| `okpd_id` | integer | FK → `collection_codes_okpd.id` | полная |
| `region_id` | integer | FK → `region.id` | полная |
| `status_id` | integer | FK → `tender_statuses.id` | превью + полная |

**Дополнительные поля 223-ФЗ** (вместо `customer`/`contractor_id`):

| Поле | Тип | Описание |
|---|---|---|
| `placer` | text | Организация-размещатель |
| `placer_inn` | text | ИНН размещателя |

---

### 2. Заказчики и подрядчики

**`customer`** — заказчики:

| Поле | Тип | Описание |
|---|---|---|
| `id` | integer | PK |
| `customer_short_name` | text | Краткое наименование |
| `customer_full_name` | text | Полное наименование |
| `customer_inn` | varchar(12) | ИНН |
| `customer_kpp` | varchar(9) | КПП |
| `customer_legal_address` | text | Юридический адрес |
| `customer_actual_address` | text | Фактический адрес |
| `contact_phone` | text | Телефон |
| `contact_email` | text | Email |
| `contact` | text | Контактное лицо |

**`contractor`** — подрядчики/поставщики:

| Поле | Тип | Описание |
|---|---|---|
| `id` | integer | PK |
| `short_name` | text | Краткое наименование |
| `full_name` | text | Полное наименование |
| `inn` | varchar(12) | ИНН |
| `kpp` | varchar(9) | КПП |
| `legal_address` | text | Юридический адрес |
| `phone` | text | Телефон |
| `email` | text | Email |

---

### 3. Справочники

**`tender_statuses`** — статусы закупки:

| Поле | Тип | Описание |
|---|---|---|
| `id` | integer | PK |
| `name` | varchar(50) | Название статуса |
| `description` | text | Описание |

**`trading_platform`** — торговые площадки:

| Поле | Тип | Описание |
|---|---|---|
| `id` | integer | PK |
| `trading_platform_name` | text | Название площадки |
| `trading_platform_url` | text | URL площадки |

**`collection_codes_okpd`** — коды ОКПД2:

| Поле | Тип | Описание |
|---|---|---|
| `id` | integer | PK |
| `main_code` | varchar(20) | Основной код ОКПД2 |
| `sub_code` | varchar(20) | Подкод ОКПД2 |
| `name` | varchar(900) | Наименование |

---

### 4. Документы закупки

**`links_documentation_44_fz`** / **`links_documentation_223_fz`** — ссылки на документы:

| Поле | Тип | Описание |
|---|---|---|
| `id` | integer | PK |
| `contract_id` | integer | FK → `reestr_contract_*_fz.id` |
| `document_links` | text | URL документа на zakupki.gov.ru |
| `file_name` | text | Имя файла |

---

### 5. Результаты обработки (демон)

**`tender_document_matches`** — агрегированные результаты по файлу:

| Поле | Тип | Описание | Карточка |
|---|---|---|---|
| `id` | integer | PK | — |
| `tender_id` | integer | FK → `reestr_contract_*_fz.id` | — |
| `registry_type` | varchar(255) | Тип реестра (`reestr_contract_44_fz` и т.д.) | — |
| `file_name` | text | Имя обработанного файла | полная |
| `yandex_path` | text | Путь к файлу на Яндекс.Диске | превью + полная |
| `match_count` | integer | Количество найденных совпадений | превью + полная |
| `match_percentage` | numeric(5,2) | Процент совпадений | полная |
| `is_interesting` | boolean | Флаг: найдены совпадения | превью |
| `has_error` | boolean | Флаг ошибки обработки | полная |
| `error_reason` | text | Причина ошибки | полная |
| `folder_name` | text | Папка на Яндекс.Диске | полная |
| `processing_time_seconds` | numeric(10,2) | Время обработки файла (сек) | — |
| `total_files_processed` | integer | Всего файлов в задаче | полная |
| `total_size_bytes` | bigint | Суммарный размер файлов | — |
| `status` | varchar(50) | Статус обработки | полная |
| `worker_id` | varchar(50) | ID воркера | — |
| `created_at` | timestamp | Дата создания записи | полная |
| `updated_at` | timestamp | Дата обновления | — |

**`tender_document_match_details`** — детали каждого совпадения:

| Поле | Тип | Описание | Карточка |
|---|---|---|---|
| `id` | integer | PK | — |
| `match_id` | integer | FK → `tender_document_matches.id` | — |
| `matched_keywords` | text[] | Найденные ключевые слова/фразы | полная |
| `product_name` | text | Название продукта из каталога | полная |
| `score` | numeric(5,2) | Оценка совпадения (0–100) | полная |
| `matched_text` | text | Строка текста с совпадением | полная |
| `matched_display_text` | text | Отформатированный фрагмент для отображения | полная |
| `source_file` | text | Имя исходного файла | полная |
| `line_number` | integer | Номер строки в документе (PDF/TXT) | полная |
| `sheet_name` | text | Название листа (XLSX) | полная |
| `row_index` | integer | Номер строки в таблице (XLSX) | полная |
| `column_letter` | text | Буква колонки (XLSX) | полная |
| `cell_address` | text | Адрес ячейки, напр. `B12` (XLSX) | полная |
| `row_data` | jsonb | Полная строка таблицы (XLSX) | полная |
| `created_at` | timestamp | Дата записи | — |

**`processed_documents`** — реестр обработанных файлов:

| Поле | Тип | Описание |
|---|---|---|
| `id` | bigint | PK |
| `tender_id` | bigint | FK → `reestr_contract_*_fz.id` |
| `table_source` | text | Тип реестра |
| `file_name` | text | Имя файла |
| `status` | text | `pending` / `processing` / `completed` / `error` |
| `is_interesting` | boolean | Найдены совпадения |
| `yandex_path` | text | Путь на Яндекс.Диске |
| `started_at` | timestamptz | Начало обработки |
| `finished_at` | timestamptz | Завершение обработки |
| `error_message` | text | Текст ошибки |

---

### БД: `product_catalog_2` (хост: 100.122.104.106)

**`products`** — каталог продукции (источник ключевых слов для матчинга):

| Поле | Описание |
|---|---|
| `name` | Название продукта — используется как ключевое слово при поиске в документах |

---

## Граф связей

```
reestr_contract_44_fz / reestr_contract_44_fz_awarded / reestr_contract_223_fz
    │
    ├── customer_id ──────────────────────────→ customer
    │                                              (customer_short_name, inn, phone, email)
    │
    ├── contractor_id ────────────────────────→ contractor
    │                                              (short_name, inn, phone, email)
    │
    ├── trading_platform_id ──────────────────→ trading_platform
    │                                              (trading_platform_name, url)
    │
    ├── okpd_id ──────────────────────────────→ collection_codes_okpd
    │                                              (main_code, name)
    │
    ├── status_id ────────────────────────────→ tender_statuses
    │                                              (name)
    │
    ├── id ──────────────────────────────────→ links_documentation_44_fz / links_documentation_223_fz
    │   (contract_id)                              (document_links, file_name)
    │
    └── id ──────────────────────────────────→ tender_document_matches
        (tender_id + registry_type)                │
                                                   └── id ──→ tender_document_match_details
                                                       (match_id)
```

---

## SQL-запрос для превью-карточки

```sql
SELECT
    r.id,
    r.contract_number,
    r.tender_link,
    r.auction_name,
    r.initial_price,
    r.final_price,
    r.delivery_start_date,
    r.delivery_end_date,
    r.customer                          AS customer_short,
    c.customer_short_name,
    c.customer_inn,
    con.short_name                      AS contractor_short,
    con.inn                             AS contractor_inn,
    ts.name                             AS status,
    COUNT(DISTINCT m.id)                AS matched_files_count,
    SUM(m.match_count)                  AS total_matches,
    MAX(m.yandex_path)                  AS yandex_path_example,
    'reestr_contract_44_fz'             AS registry_type
FROM reestr_contract_44_fz r
LEFT JOIN customer c ON c.id = r.customer_id
LEFT JOIN contractor con ON con.id = r.contractor_id
LEFT JOIN tender_statuses ts ON ts.id = r.status_id
LEFT JOIN tender_document_matches m
    ON m.tender_id = r.id
    AND m.registry_type = 'reestr_contract_44_fz'
    AND m.is_interesting = true
WHERE m.id IS NOT NULL   -- только закупки с совпадениями
GROUP BY r.id, c.id, con.id, ts.id
ORDER BY r.delivery_end_date DESC;
```

---

## SQL-запрос для полной карточки

```sql
-- Основные данные закупки
SELECT
    r.*,
    c.customer_short_name,
    c.customer_full_name,
    c.customer_inn,
    c.customer_kpp,
    c.customer_legal_address,
    c.contact_phone,
    c.contact_email,
    con.short_name      AS contractor_name,
    con.full_name       AS contractor_full_name,
    con.inn             AS contractor_inn,
    con.phone           AS contractor_phone,
    tp.trading_platform_name,
    tp.trading_platform_url,
    okpd.main_code      AS okpd_code,
    okpd.name           AS okpd_name,
    ts.name             AS status_name
FROM reestr_contract_44_fz r
LEFT JOIN customer c ON c.id = r.customer_id
LEFT JOIN contractor con ON con.id = r.contractor_id
LEFT JOIN trading_platform tp ON tp.id = r.trading_platform_id
LEFT JOIN collection_codes_okpd okpd ON okpd.id = r.okpd_id
LEFT JOIN tender_statuses ts ON ts.id = r.status_id
WHERE r.id = :tender_id;

-- Документы (ссылки на оригиналы)
SELECT document_links, file_name
FROM links_documentation_44_fz
WHERE contract_id = :tender_id;

-- Файлы с совпадениями (ссылки на Яндекс.Диск)
SELECT
    m.file_name,
    m.yandex_path,
    m.match_count,
    m.match_percentage,
    m.folder_name,
    m.status,
    m.created_at
FROM tender_document_matches m
WHERE m.tender_id = :tender_id
  AND m.registry_type = 'reestr_contract_44_fz'
  AND m.is_interesting = true
ORDER BY m.match_count DESC;

-- Детали совпадений
SELECT
    d.matched_keywords,
    d.product_name,
    d.score,
    d.matched_display_text,
    d.source_file,
    d.sheet_name,
    d.cell_address,
    d.line_number
FROM tender_document_match_details d
JOIN tender_document_matches m ON m.id = d.match_id
WHERE m.tender_id = :tender_id
  AND m.registry_type = 'reestr_contract_44_fz'
ORDER BY d.score DESC;
```

---

## Структура карточки для CRM

### Превью-карточка

```
┌─────────────────────────────────────────────────────────┐
│ [Статус]  Наименование объекта закупки                  │
│ № 0124200000626000370                                   │
│                                                         │
│ Заказчик: ООО "Название"  ИНН: 7713013920               │
│ Подрядчик: ООО "Подрядчик"                              │
│                                                         │
│ Цена: 1 234 567 ₽  →  987 654 ₽ (итог)                 │
│ Поставка: 01.03.2026 — 31.12.2026                       │
│                                                         │
│ 🎯 Совпадений: 12  в 3 документах                       │
│ 📁 [Открыть на Яндекс.Диске]                            │
└─────────────────────────────────────────────────────────┘
```

Поля превью:
- `auction_name` — название
- `contract_number` — номер
- `tender_statuses.name` — статус
- `customer` / `customer.customer_short_name` — заказчик
- `customer.customer_inn` — ИНН заказчика
- `contractor.short_name` — подрядчик
- `initial_price` / `final_price` — цены
- `delivery_start_date` / `delivery_end_date` — даты поставки
- `SUM(match_count)` — количество совпадений
- `COUNT(matched files)` — количество документов с совпадениями
- `tender_document_matches.yandex_path` — ссылка на Яндекс.Диск

### Полная карточка — разделы

**Раздел 1: Общая информация**
- Номер контракта (`contract_number`)
- Наименование объекта (`auction_name`)
- Реестр (`registry_type`: 44-ФЗ / 223-ФЗ)
- Статус (`tender_statuses.name`)
- Торговая площадка (`trading_platform_name` + `trading_platform_url`)
- Код ОКПД2 (`okpd_code` + `okpd_name`)
- Ссылка на закупку (`tender_link`)

**Раздел 2: Участники**
- Заказчик: полное название, ИНН, КПП, адрес, телефон, email, контактное лицо
- Подрядчик: полное название, ИНН, КПП, адрес, телефон, email
- (для 223-ФЗ) Размещатель: `placer` + `placer_inn`

**Раздел 3: Даты и суммы**
- Дата начала закупки (`start_date`)
- Дата окончания закупки (`end_date`)
- Дата начала поставки (`delivery_start_date`)
- Дата окончания поставки (`delivery_end_date`)
- НМЦ (`initial_price`)
- Итоговая цена (`final_price`)
- Обеспечение (`guarantee_amount`)
- Гарантийные обязательства (`warranty_size`)

**Раздел 4: Адрес поставки**
- Регион (`delivery_region`)
- Адрес (`delivery_address`)

**Раздел 5: Документы закупки (оригиналы)**
- Список из `links_documentation_44_fz` / `links_documentation_223_fz`
- Для каждого: `file_name` + кнопка скачать (`document_links`)
- Кнопка "Скачать все"

**Раздел 6: Найденные совпадения**
- Список файлов из `tender_document_matches` где `is_interesting = true`
- Для каждого файла:
  - Имя файла (`file_name`)
  - Количество совпадений (`match_count`)
  - Ссылка на Яндекс.Диск (`yandex_path`)
  - Детали из `tender_document_match_details`:
    - Ключевые слова (`matched_keywords`)
    - Название продукта (`product_name`)
    - Оценка совпадения (`score`)
    - Фрагмент текста (`matched_display_text`)
    - Расположение в документе (`sheet_name` + `cell_address` или `line_number`)

---

## Примечания по реестрам

При запросе нужно объединять все реестры через `UNION ALL` или делать отдельные запросы по `registry_type`:

| `registry_type` | Таблица реестра | Таблица ссылок |
|---|---|---|
| `reestr_contract_44_fz` | `reestr_contract_44_fz` | `links_documentation_44_fz` |
| `reestr_contract_44_fz_awarded` | `reestr_contract_44_fz_awarded` | `links_documentation_44_fz` |
| `reestr_contract_223_fz` | `reestr_contract_223_fz` | `links_documentation_223_fz` |

Связь `tender_document_matches` → реестр: `tender_id` + `registry_type` (составной ключ).
