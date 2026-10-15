# WIP GOOD_SUPPLY_FACTS_V1 — чистые данные «что можно поставить»

Status: СПЕКА / ПРИОРИТЕТ. Owner: card data / document normalization.

## Цель

Перестать показывать сырые `document_match_details` как коммерческие находки.
Построить чистый слой данных для карточки:

```text
только реальные товарные/материальные факты
из наших категорий
не работы
с цитатой из сметы/ТЗ/ведомости
привязанные к разделу, где это возможно
```

## Приоритет вывода

Главное — **материал и его атрибуты**, а не раздел:

```text
product_name
quantity_value
quantity_unit_normalized
unit_price_value
total_price_value
технические характеристики (structured_attributes)
source_quote
section_name — только как лёгкая пометка «найдено в разделе»
```

Раздел второстепенный. Если раздел известен — показываем его как контекст,
но не блокируем вывод материала из-за отсутствия/ненадёжности section total.

## Источник хороших данных

Не `document_match_details`, а `structured_entities`.

Фильтры:

```text
category_code в активных товарных категориях
classify_fact_kind(...) = GOODS
не агрегатная строка
quantity_value IS NOT NULL
quantity_unit_normalized IS NOT NULL
total_price_value или line_total_value
source_quote непустой
section_code — если есть; иначе RESIDUE
```

`document_match_details` остаётся только evidence/candidate, а не «можно
поставить».

## Фазы

### Phase 0 — clean supply facts read-only

Создать `src/services/good_supply_facts_service.py`:

```text
build_good_supply_facts(procurement_id) -> {
    facts,
    hidden_works,
    hidden_aggregates,
    residue,
    audit
}
```

Сравнить на 60467 и 148391.

### Phase 1 — подключение к карточке

«Что можно поставить» строится из `good_supply_facts_service`.
Сырые `document_match_details` не выводятся как подтверждённые товары.

### Phase 2 — backfill/reparse выбранных закупок

Для закупок без section/старых фактов — точечный reparse.

## Acceptance

```text
NO_RAW_MATCH_AS_SUPPLY=YES
GOODS_ONLY=YES
WORKS_HIDDEN=YES
AGGREGATES_HIDDEN=YES
SOURCE_QUOTE_PRESENT=YES
SECTION_BOUND_WHERE_AVAILABLE=YES
DB_WRITES=0_UNTIL_APPROVED
```

## Out of scope

- scoring/medal/queue;
- model retraining;
- DIRECT-компьютеры.

## RESULT (2026-10-15) — DONE

### Phase 0 — чистый сервис (read-only)

```
new: src/services/good_supply_facts_service.py
  build_good_supply_facts(procurement_id, limit=300) -> {
      facts, hidden_works, hidden_aggregates, hidden_other, hidden_detail, residue, audit }
  источник — structured_entities (НЕ document_match_details) + preferred-suppression
    (предпочитаем строку с section_code, затем больший id);
  фильтры: category_code заполнен и != 'unknown'; classify_fact_kind == GOODS;
    не агрегат (^(итого|всего|стоимость|ндс|раздел|глава)); quantity_value и
    quantity_unit_normalized заполнены; total_price_value заполнен; source_quote непустой;
    section_code — если есть, иначе RESIDUE.
md5 локально == S13: 83f977bcdfcd1bc2afa96d09cc51b62a
```

ПРОВЕРКА:

```
60467 : scanned 300 | GOODS 52 | works hidden 248 | aggregates 0 | other 0 | residue 0
148391: scanned 300 | GOODS 82 | works hidden 117 | other 101 (no_category) | residue 44
29311 : scanned   6 | GOODS  0 | works hidden   6  -> «можно поставить» пусто
```

### Phase 1 — карточка

```
procurement_card_dossier_service: «Что можно поставить» строится из
  build_good_supply_facts; в dossier добавлен supply_audit
  {scanned, kept, hidden_works, hidden_aggregates, hidden_other, hidden_detail, residue};
DIRECT_SUPPLY — прежний путь (не трогаем): supply_candidates_direct_untouched;
document_match_details в «что можно поставить» не участвуют (остаются evidence —
вкладка «Находки»).
```

### Phase 2 — точечный reparse

```
кандидаты (entity есть, section нет; >=20 строк): 658 закупок
топ: 461729 (37047) | 17236 (16321) | 462454 (4506) | 26386 (3747) | 462552 (3603) |
     12111 (3218) | 44209 (3169) | 102844 (2982)
инструмент: scripts/reparse_procurement_sections.py --procurement-id N --local-only --apply
  (без claim/admission, только локальные файлы, EMBEDDED_FORCE_UPDATE=1)
```

ACCEPTANCE:

```
NO_RAW_MATCH_AS_SUPPLY        = YES (только structured_entities)
GOODS_ONLY                    = YES
WORKS_HIDDEN                  = YES (60467: 248 | 148391: 117 | 29311: 6)
AGGREGATES_HIDDEN             = YES (фильтр есть; на контроле 0 — агрегаты отсекаются и по qty/unit)
SOURCE_QUOTE_PRESENT          = YES (обязательное условие)
SECTION_BOUND_WHERE_AVAILABLE = YES (section_code или RESIDUE)
DB_WRITES                     = 0 (сервис read-only)
```

DEVIATIONS / FOLLOW-UP:

- Работы с числовой нумерацией («2.2.4 Устройство участка…», «1.13 Рекультивация…»)
  сначала проходили как GOODS — в `classify_fact_kind` добавлено снятие номера-префикса
  (148391: hidden works 110 → 117).
- Слой подтверждений не изменился (TRUSTED_PRODUCTION: 10433 товарных факта / 523
  подтверждения) — нумерованные работы в него не попадали.
- Остаточные пограничные/фрагментарные названия («верха земляного полотна») остаются GOODS.
- 658 закупок-кандидатов на reparse не прогонялись (Phase 2 — по запросу).

## RESULT (2026-10-15, v2) — плоский материалоцентричный набор

STATUS: DONE (схема вывода приведена к приоритету «материал и атрибуты»).

ИЗМЕНЕНИЯ:

```
src/services/good_supply_facts_service.py — to_flat_fact(): факт карточки
    material | quantity | unit | unit_price | total | attributes | source_quote | section_name
  + аудит: section_code (RESIDUE), row_or_line, page_or_sheet, category_code, trust_state;
  + старые ключи (product_name_*, quantity_*, unit_price_value, total_price_value,
    quantity_unit_raw/normalized, entity_type, product_relation) — для совместимости рендера.
  Раздел — ЛЁГКАЯ ПОМЕТКА: если section_code неизвестен/ненадёжен, материал всё равно
  выводится; section_total НЕ является гейтом.
src/ui/procurement_card_page.py — «Что можно поставить»: колонки
  Материал | Кол-во | Ед. | Цена | Сумма | Характеристики | Цитата | Раздел.
md5 локально == S13: good_supply_facts_service 17121c15090b3dab61a497562b1d2528,
                     procurement_card_page c2a69bcec7c3217379b8567fc1d547d2
```

ПРОВЕРКА:

```
60467 : kept 52 | works 248 | residue 0
        flat: {"material":"верха земляного полотна","quantity":7396.0,"unit":"M2",
               "unit_price":5.0865…,"total":37620.18…,"attributes":[],"source_quote":"A=…",
               "section_name":"Глава 4"}
148391: kept 82 | works 117 | residue 44
        flat: {"material":"Изготовление и доставка …","quantity":1948.4,"unit":"M",
               "unit_price":124494.834,"total":242565735.0,"attributes":[…],
               "source_quote":"A=…","section_name":null}   <- раздел не известен, материал всё равно в выдаче
29311 : kept 0 | works 6
```

ACCEPTANCE (v2):

```
FLAT_MATERIAL_SCHEMA      = YES (material|quantity|unit|unit_price|total|attributes|source_quote|section_name)
SECTION_IS_CONTEXT_ONLY   = YES (не блокирует вывод материала)
SECTION_TOTAL_NOT_REQUIRED= YES
WORKS_HIDDEN              = YES
AGGREGATES_HIDDEN         = YES
SOURCE_QUOTE_PRESENT      = YES
DB_WRITES                 = 0
```
