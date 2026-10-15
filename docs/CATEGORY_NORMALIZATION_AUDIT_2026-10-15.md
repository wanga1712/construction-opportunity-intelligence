# CATEGORY_NORMALIZATION_AUDIT_ALL_V1 — Phase 0 (read-only, 2026-10-15)

Инвентаризация нормализации по всем активным товарным категориям.
Источники: CRM `crm_procurement_category_opportunities` / `crm_product_categories` +
DI `structured_entities` / `document_files` / `document_match_details`.
`DB_WRITES=0`, scoring/medal/queue не затрагивались.

## 1. Coverage matrix

`SOURCE_SPLIT` = `SECTION_TOTAL / COMPUTED_SUM / COMPUTED_SUM_UNRELIABLE / RESIDUE`
(считано по строкам с section-контекстом).

| Категория | CURRENT opps (ACTIVE/AWARDED) | Закупок | Entities | WITH_SECTION | SOURCE_SPLIT | Форматы документов (top) |
|---|---:|---:|---:|---:|---|---|
| lighting | 1680 (372/1308) | 1680 | 19 620 | **0** | — | docx 845 · rar 477 · pdf 446 · xlsx 275 |
| drainage_water_management | 1581 (194/1387) | 1581 | 28 079 | **0** | — | docx 561 · pdf 508 · xlsx 315 · rar 158 |
| composite_structures | 1433 (215/1218) | 1421 | 41 594 | 7 894 | CS 97 · **CSU 7 644** · RESIDUE 153 | docx 657 · xlsx 395 · pdf 375 · rar 262 |
| curbstone | 1431 (180/1251) | 1431 | 15 532 | **0** | — | docx 505 · xlsx 221 · pdf 161 · rar 146 |
| computers | 853 (850/3) | 836 | 3 214 | **0** | — | docx 1081 · pdf 426 · xlsx 197 · doc 160 |
| waterproofing | 706 (153/553) | 706 | 16 486 | 1 869 | CS 588 · **CSU 1 040** · RESIDUE 241 | pdf 322 · docx 237 · xlsx 179 · rar 52 |
| flooring | 169 (47/122) | 169 | 25 935 | **0** | — | pdf 408 · docx 302 · rar 259 · xlsx 185 |
| cable_support_systems | 113 (107/5) | 113 | 713 | **0** | — | docx 164 · pdf 42 · xlsx 40 · doc 20 |
| *(без CURRENT)* cable_products | 0 | — | 94 | 10 | RESIDUE 10 | pdf 86 · xlsx 65 · docx 16 |
| *(без CURRENT)* structural_reinforcement | 0 | — | 43 | 7 | RESIDUE 7 | pdf 70 · xlsx 55 · docx 16 |
| *(без CURRENT)* waterproofing_concrete_repair | 0 | — | 18 | 1 | RESIDUE 1 | pdf 40 · xlsx 20 |
| *(без CURRENT)* roofing | 0 | — | 1 | 0 | — | docx 5 |
| `unknown` (вне реестра) | — | — | 122 159 | 120 | RESIDUE 120 | — |

## 2. Главные выводы

1. **Секции есть только у 2 из 8 активных категорий** (`composite_structures`,
   `waterproofing`) — у остальных `WITH_SECTION = 0`, то есть section-слой на них
   вообще не прогонялся.
2. **Качество секций там, где он есть, низкое**: `composite_structures` —
   7 644 из 7 894 (96.8 %) `COMPUTED_SUM_UNRELIABLE`; `waterproofing` — 1 040 из 1 869
   (55.6 %). `SECTION_TOTAL` не встретился ни разу (0/7 894 и 0/1 869) — явных строк
   «Итого по разделу» нормализатор не выставил.
3. **Форматы однотипны**: везде `docx` + `pdf` + `xlsx` и архивы (`rar`/`zip`) —
   значит шаблон должен, как `road_repair_section_templates`, работать **по тексту
   маркера**, а не по типу файла/колонке.
4. **Термины матчей шумные**: `document_match_details` = LEGACY_UNVERIFIED 957 960,
   VERIFIED 137 034, INVALID 3 040; среди VERIFIED есть общие словники —
   `мастика` 7 834, `управлен` 5 242, `жкх` 67. `VERIFIED` ≠ «товарный факт» —
   такие термины не должны попадать ни в «можно поставить», ни в модель.

## 3. Приоритизация (Phase 1 — предложение)

Порядок: сначала категории без секций с большим CURRENT и повторяющейся формой.

| # | Категория | Почему | Первый шаг |
|---|---|---|---|
| 1 | `lighting` | 1680 CURRENT, 19 620 entities, 0 % section | точечный reparse + шаблон маркеров |
| 2 | `curbstone` | 1431 CURRENT, 15 532 entities, 0 % section, docx-форма | точечный reparse + шаблон |
| 3 | `drainage_water_management` | 1581 CURRENT, 28 079 entities, 0 % | точечный reparse + шаблон |
| 4 | `flooring` | 25 935 entities, 0 % (CURRENT 169) | reparse, затем шаблон |
| 5 | `cable_support_systems` | 113 CURRENT, 713 entities, 0 % | reparse, затем шаблон |
| 6 | `composite_structures` | секции есть, но 96.8 % UNRELIABLE | докрутка качества покрытия (`section_total`/покрытие) |
| 7 | `waterproofing` | 55.6 % UNRELIABLE | докрутка качества |
| 8 | `computers` | DIRECT-контур | отдельный WIP `DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1` |

## 4. Acceptance (Phase 0)

```
CATEGORY_COVERAGE_MATRIX_EXISTS = YES (таблица выше)
EVERY_CATEGORY_HAS_STATUS       = YES (8 активных + 4 без CURRENT + unknown)
TEMPLATES_APPLIED_BY_PRIORITY   = N/A (только Phase 1 — предложение)
AI_FALLBACK_NOT_PRIMARY         = YES (fallback не запускался)
DB_WRITES                       = 0
SCORING_MEDAL_QUEUE_UNCHANGED   = YES
```
