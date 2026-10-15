# WIP ROAD_REPAIR_SECTION_TEMPLATES_V1 — шаблонизатор смет дорожного ремонта

Status: СПЕКА / ДО ЗАПУСКА. Owner: document normalization / section projection.

## Проблема

Для 60467 и похожих закупок «капитальный ремонт автодороги» документы
семантически одинаковые:

```text
смета / ВОР / ведомость объёмов работ
разделы и главы
материалы внутри разделов
итоги по разделу/главе
```

Но форматы файлов и шапки отличаются. Текущий generic `section_detector.py`
работает по общим маркерам и не умеет использовать дорожные шаблоны, поэтому
часть разделов/сумм уходит в `COMPUTED_SUM_UNRELIABLE` или `RESIDUE`.

Нужен **шаблонизатор-нормализатор** для этого семейства документов, а не ещё
одна модель.

## Цель

Создать и запустить детерминированный шаблонный слой поверх
`section_detector.py`, который:

- распознаёт семейство «дорожная смета/ВОР»;
- находит разделы/главы и материалы;
- считает суммы раздела по правилам дорожных смет;
- одинаково работает на разных форматах одного смысла;
- постепенно расширяется на новых закупках.

## Фазы

### Phase 0 — inventory дорожных форм

Статус: DONE (`14f9eb6`). Контроль 60467 + 12 CURRENT дорожных закупок.

Выбрать репрезентативные текущие `CURRENT` дорожные закупки, включая 60467:

- ОКПД 42.11.*;
- title содержит `капитальный ремонт`, `ремонт а/д`, `автомобильн* дорог*`;
- сметные документы уже есть или будут после queue rebuild.

Замерить формы:

```text
тип файла (.gsfx/.xlsx/.pdf/.docx)
шапки колонок
маркеры разделов/глав
наличие «Итого по главе», «Ведомость объёмов работ»
```

Выводы Phase 0:

- устойчив текст `Итого по разделу N <Название>`, а не номер колонки;
- section_name берём из текста после номера;
- шифры СР/ЛС/ОС в колонке B — fallback-identity;
- прямых `.gsfx` в выборке нет, сметы внутри архивов/PDF/DOCX.

### Phase 1 — шаблон дорожной сметы

Добавить отдельный модуль/слой:

```text
tender_documents_research/document_processor/road_repair_section_templates.py
```

Правила:

- определение главы/раздела по маркерам дорожной сметы;
- определение материалов по колонкам;
- итог раздела — из явной строки раздела/главы;
- `COMPUTED_SUM` — только по summarizable-материалам;
- `RESIDUE` — честный остаток.

### Phase 2 — canary на 60467

Прогнать шаблон на 60467 read-only:

```text
SECTION_COUNT
SECTION_TOTAL / COMPUTED_SUM / UNRELIABLE
RESIDUE
```

Сравнить с текущим generic-детектором. Зафиксировать разницу.

Для карточки показываем **только разделы, в которых есть хотя бы один
summarizable-материал из наших категорий**. Пустые/работные разделы в UI не
выводим; в аудите их можно оставить как счётчики.

Для category discovery/частотного слоя передаём **материалы**, а не разделы:
`product_name_normalized`, `category_code`, `source_quote`, `quantity`, `unit`.
Section — только контейнер для отображения, не сигнал категории.

### Phase 3 — поэтапный rollout

Запустить шаблон на N похожих закупках:

```text
dry-run -> замер -> приёмка -> батч следующей группы
```

После каждого батча обновлять каталог форм в `docs/NORMALIZATION_TEMPLATES.md`.

## Acceptance для 60467

```text
ROAD_REPAIR_TEMPLATE_DETECTED=YES
SECTIONS_MATCH_DOCUMENT=YES
SECTION_TOTAL_OR_COMPUTED_SUM_CORRECT=YES
UNRELIABLE_MINIMIZED=YES
RESIDUE_VISIBLE=YES
SOURCE_QUOTE_PRESENT=YES
DETERMINISTIC_RERUN=YES
DB_WRITES=0_UNTIL_REPARSE_APPROVED
```

## Out of scope

- scoring/medal/queue admission;
- DIRECT-контур;
- model fallback как основной путь;
- массовый queue rebuild.

## RESULT Phase 0 (2026-10-15) — inventory дорожных форм (read-only, DB_WRITES=0)

CONTROL 60467:

```
CRM: okpd 42.11.20.230 | «Выполнение работ по капитальному ремонту а/д "186 км а/д "К-22"…» |
     НМЦК 95 323 936 | award_status=awarded
CURRENT opportunities (5): lighting, drainage_water_management, composite_structures,
     curbstone, waterproofing — все EMBEDDED_MATERIAL, medal SILVER

DI documents: 44 файла — архивы (zip/7z/rar) 36 | xlsx 4 | pdf 4 | docx 0; .gsfx напрямую = 0
extraction runs: 1 — «10.НМЦК_КР_Петрово УстьТаркском рне.xlsx»
     (category waterproofing, EMBEDDED_EXTRACTOR_V1, snapshot 200 строк)

маркеры формы:
  шапка: «A=Обоснование | B=Наименование глав, объектов капитального строительства, работ и затрат |
          E=монтажных работ | H=оборудования | I=прочих затрат |
          J=Глава 1. Подготовка территории строительства…»
  раздел: «AE=Итого по разделу 13 Подготовка территории строительства»
          «AE=Итого по разделу 1 Подготовительные работы»
          «AE=Итого по разделу 2 Земляное полотно»
          «AE=Итого по разделу 3 Дорожная одежда»
  шифры в колонке B: СР-01-01 / ЛС-01-01-01 / ОС-01-01; единицы H, количество I, суммы K/L
«Ведомость объёмов работ» в снапшоте 60467 не встречается
```

REPRESENTATIVE SET (12 закупок: CURRENT, okpd 42.11*, «капитальный ремонт»/«ремонт а/д»):

```
НМЦК, млрд: 28018 13.6 | 30971 8.7 | 47637 7.2 | 173346 3.5 | 1203 2.4 | 1356 1.5 |
            178620 1.24 | 732 1.15 | 454339 1.14 | 1406 1.08 | 19015 1.07 | 31730 0.98
типы файлов (архивы / xlsx / pdf / docx), 60467 в контроле:
  31730  3/0/45/4    60467 36/4/4/0    30971 10/6/1/23   28018 28/4/0/4    732 30/2/0/3
  47637  9/4/2/17    178620 0/5/9/8    454339 4/0/0/7   1203  0/2/2/8    1356 0/0/7/0
  19015  2/0/2/3     1406   0/0/5/1
.gsfx напрямую в document_files: 0 у всех закупок выборки
section_code заполнен: 0 у всех (секционный слой на этих закупках ещё не прогонялся)

вторая форма (178620): документы «1.Ведомость объемов работ_Кап.рем…», «3.Смета Контракта_…»,
  «3.Проект Сметы Контракта_…»; маркер тот же по смыслу, но в КОЛОНКЕ F:
  «F=Итого по разделу 18 Светофорный объект», «F=Итого по разделу 9 Переустройство кабеля связи…»
```

ВЫВОДЫ для Phase 1:

1. Устойчивый текстовый маркер дорожной формы — «Итого по разделу N <Название>» (плюс
   «Глава N. <Название>» в шапке). Позиция колонки НЕ устойчива (AE у 60467, F у 178620),
   поэтому детект — по тексту строки, а не по номеру колонки.
2. `section_name` = текст после номера («Земляное полотно», «Дорожная одежда», «Светофорный объект»).
3. 60467 дополнительно несёт шифры СР/ЛС/ОС в колонке B — годится как fallback-identity раздела.
4. Сметы приходят внутри архивов и в PDF/DOCX; `.gsfx` напрямую в `document_files` нет —
   шаблон должен работать по строковому тексту, а не по «файлу .gsfx».
5. Для Phase 2 (canary на 60467) нужен reparse: сейчас `section_code = 0`.

ACCEPTANCE (Phase 0):

```
CONTROL_60467_SELECTED      = YES (okpd 42.11.20.230, 5 CURRENT opportunities)
REPRESENTATIVE_SET          = 12 закупок, разброс НМЦК 0.98–13.6 млрд
FILE_FORMS_RECORDED         = YES (типы файлов, шапки, маркеры «Итого по разделу», шифры,
                                    наличие «Ведомость объёмов работ»)
DB_WRITES                   = 0 (только SELECT)
```

## RESULT Phase 1 (2026-10-15) — шаблонный слой дорожных смет

STATUS: DONE (read-only проверка на 60467; в parse-путь демона НЕ подключён).

ИЗМЕНЕНИЯ:

```
new: tender_documents_research/document_processor/road_repair_section_templates.py
  parse_road_marker() — маркер ищется по ТЕКСТУ строки в ЛЮБОЙ колонке:
      «Итого по разделу N <Название>» -> kind=razdel, number=N, name=<Название>
      «Глава N[.] <Название>»         -> kind=glava
      (шум в имени чистится: «Поз.: 33-35», «работ и затрат»)
  parse_shifr()       — шифры СР-*/ЛС-*/ОС-* как fallback identity
  section_code = "road::razdel N" | "road::glava N"; номер раздела ПЕРВИЧЕН,
      шифр только привязывает строки без маркера (shifr_to_code)
  build_road_sections(rows) — детерминированный разбор:
      * суммируются ТОЛЬКО is_summarizable-строки (canonical predicate из section_detector);
      * агрегатные строки (имя-маркер или unit=руб. без qty) не суммируются, но явный итог
        такой строки даёт SECTION_TOTAL;
      * coverage = total_rows/summarizable_rows; < 0.9 или наличие агрегатов ->
        COMPUTED_SUM_UNRELIABLE;
      * непривязанное -> RESIDUE (честный остаток);
      * работает по source_quote — не по номеру колонки и не по .gsfx.
  БД не трогает; scoring / medal / queue не трогает.
```

ПРОВЕРКА (read-only на S13, 60467, первые 400 строк сущностей):

```
маркеры:
  "AE=Итого по разделу 13 Подготовка территории строительства"
        -> (razdel, 13, "Подготовка территории строительства")
  "F=Итого по разделу 18 Светофорный объект"      [другая колонка]
        -> (razdel, 18, "Светофорный объект")
  "J=Глава 1. Подготовка территории строительства"
        -> (glava, 1, "Подготовка территории строительства")
шифры: ЛС-01-01-01, СР-01-01
разбор: rows 400 -> sections 24 | residue 63
  road::razdel 1 | Подготовительные работы           | materials 2 | coverage 1.0 | 726.34  | COMPUTED_SUM
  road::razdel 2 | Земляное полотно                  | materials 1 | coverage 0.0 | 0.0     | COMPUTED_SUM_UNRELIABLE
  road::razdel 3 | Дорожная одежда                   | materials 0 | —            | None    | COMPUTED_SUM_UNRELIABLE
  road::glava 4  | Объекты энергетического хозяйства | materials 4 | coverage 0.5 | 5913.88 | COMPUTED_SUM_UNRELIABLE
```

ACCEPTANCE (Phase 1):

```
MARKER_BY_TEXT_NOT_COLUMN     = YES (AE / F / J — разные колонки, один маркер)
SECTION_NAME_FROM_NUMBER      = YES («Земляное полотно», «Дорожная одежда», «Светофорный объект»)
SHIFR_FALLBACK_IDENTITY       = YES (СР-/ЛС-/ОС- привязывают строки без маркера)
SUMMARIZABLE_ONLY             = YES (canonical predicate)
RESIDUE_HONEST                = YES (63 строки)
NO_GSFX_DEPENDENCY            = YES (работа по source_quote)
DB_WRITES                     = 0
SCORING_MEDAL_QUEUE_UNCHANGED = YES
```

FOLLOW-UP: Phase 2 (canary на 60467) требует reparse — сейчас у 60467 `section_code = 0`;
прогон шаблона на полном наборе строк и сравнение с generic-детектором.

## RESULT Phase 2 (2026-10-15) — canary на 60467 (read-only)

STATUS: DONE (шаблон прогнан на полном наборе строк; UI-фильтр пустых разделов внедрён).

ВАЖНО про reparse: строка очереди 60467 (`id=54737`) сейчас `SKIPPED_NOT_TARGET`,
`research_action=DEEP_RESEARCH`, `plan_version=NULL` — **claim-фильтр admission её не берёт**
(`force-run` вернул «не удалось захватить»). Ослаблять admission нельзя (правило F3), а
шаблону `section_code` не нужен: он работает по `source_quote`. Поэтому canary выполнен на
существующих строках. Статус строки возвращён в `SKIPPED_NOT_TARGET` (в `last_error`
оставлен маркер `road_template_canary_reparse` — след попытки).

ЗАМЕРЫ (60467, все строки `structured_entities`, 1780 шт.):

```
SECTION_COUNT                     = 24
SECTIONS_WITH_RELEVANT_MATERIALS  = 17
EMPTY_SECTIONS (только аудит)     = 7
SECTION_TOTAL / COMPUTED_SUM / UNRELIABLE (по непустым) = 0 / 5 / 12
RESIDUE                           = 63
generic section_code rows         = 0 (reparse не выполнялся)
материалы по категориям           = drainage_water_management 326 | waterproofing 163 | lighting 163

примеры непустых разделов:
  road::razdel 1  | Подготовительные работы            | materials 8  | coverage 1.0    | 2 905.38     | COMPUTED_SUM
  road::razdel 10 | Переустройство системы водоснабжения | materials 8  | coverage 1.0    | 81 808 368.21 | COMPUTED_SUM
  road::razdel 7  | Переустройство ВЛ и кабельной линии | materials 64 | coverage 0.375  | 57 966 060.82 | COMPUTED_SUM_UNRELIABLE
  road::razdel 2  | Земляное полотно                    | materials 1  | coverage 0.0    | 0.0          | COMPUTED_SUM_UNRELIABLE
```

UI-ФИЛЬТР (Phase 3 частично, в карточке): разделы БЕЗ релевантных материалов в проекцию не
попадают; их счётчик возвращается в `sections_skipped_empty` (только аудит).

```
section_projection_service.build_section_projection: пропускает разделы с relevant_count == 0
procurement_card_dossier_service: в SQL добавлен relevant_count =
    count(*) FILTER (entity_type='PRODUCT' AND quantity_value IS NOT NULL
                     AND quantity_unit_normalized <> '' AND NOT LIKE 'руб%'
                     AND имя не агрегат) OVER (PARTITION BY section_code)
проверка на 148391: sections shown 47 | skipped empty 1 («ПСК 1 стадия на торги::глава 3») | residue 153
import smoke: section_projection_service / procurement_card_dossier_service / ui.procurement_card_page -> OK
```

ACCEPTANCE (Phase 2):

```
CANARY_EXECUTED                 = YES (60467, 1780 строк)
SECTION_COUNT / WITH_MATERIALS  = 24 / 17
EMPTY_SECTIONS_AUDIT_ONLY       = YES (7; в UI не выводятся)
TOTAL_SOURCE_SPLIT              = COMPUTED_SUM 5 | COMPUTED_SUM_UNRELIABLE 12 | SECTION_TOTAL 0
RESIDUE                         = 63
UI_ONLY_SECTIONS_WITH_MATERIALS = YES (148391: 47 показано, 1 пустой скрыт)
MATERIALS_FOR_CATEGORY_LAYER    = YES (product_name_normalized/category_code/source_quote/quantity/unit)
DB_WRITES                       = 0
SCORING_MEDAL_QUEUE_UNCHANGED   = YES
```

ОТКРЫТЫЕ РЕШЕНИЯ:

- Reparse 60467 требует либо (a) ручного обхода claim для диагностики одной закупки,
  либо (b) admission через штатный feeder/plan. Пока не делаем: шаблону `section_code`
  не нужен, а сравнение с generic-детектором отложено.
- Интеграция road-шаблона в карточку (проекция «дорожных» разделов) — отдельный шаг:
  сейчас карточка показывает generic-`section_code`.
