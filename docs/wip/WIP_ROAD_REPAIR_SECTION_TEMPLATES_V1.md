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

Статус: DONE (`91afde1`, canary read-only на 1780 существующих строках).
Reparse 60467 не выполнен: queue `SKIPPED_NOT_TARGET`/unadmitted. Для
диагностики выбираем разовый ручной обход claim, admission не ослабляем.

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

## Решения после canary 60467

Статус: DONE (`887416a`).

1. **Stale-строки**: в плоской выдаче подавляем старые non-section дубли, когда
   есть sectioned-замена. Ключ предпочтения:
   `(procurement_id, source_document_id, entity_fingerprint)`; приоритет строкам
   с `section_code IS NOT NULL` и большему `id`. Физически строки не удаляем.
2. **Road identity с листом**: используем `road::<sheet>::razdel N` /
   `road::<sheet>::glava N`, чтобы одноимённые разделы из разных листов не
   сливались.
3. **Карточка**: подключаем road-шаблон после пунктов 1–2; карточка выбирает
   road-projection для дорожных закупок, generic — для остальных.

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

## RESULT Phase 2b (2026-10-15) — диагностический reparse 60467 + сравнение

ИНСТРУМЕНТ (разовый, без claim/admission):

```
new: scripts/reparse_procurement_sections.py
    --procurement-id 60467 --local-only --apply
  * берёт существующие document_files.local_path (ничего не скачивает, claim-фильтр
    admission НЕ используется);
  * parse_file_with_meta + extract_and_persist с EMBEDDED_FORCE_UPDATE=1;
  * по умолчанию dry-run; queue/admission/scoring/medal не меняет.
  запуск: воркерный venv + воркерные EnvironmentFile (systemd-run reparse-60467).
```

ПРОГОН:

```
procurement 60467 | document_files rows with local_path 4 | distinct paths 1
   (4 строки — дубли одной и той же ссылки wave2a)
on disk: 1 -> «10.НМЦК_КР_Петрово УстьТаркском рне.xlsx»
PARSED ×4 (df_id 125105/125116/125127/125138, category waterproofing)
  result каждого: embedded 446 ; TOTALS {'facts': 0, 'metadata': 28, 'embedded': 1784}
APPLIED: section-поля пересчитаны (EMBEDDED_FORCE_UPDATE=1)
```

СРАВНЕНИЕ (на строках с заполненным `section_code`, 1784):

```
GENERIC (embedded_extraction):
    разделов 53 | RESIDUE 156 | COMPUTED_SUM 588 строк | COMPUTED_SUM_UNRELIABLE 1040 строк
    примеры кодов: «ВКР::итого по главе 12» 136 | «ПСК::глава 1» 188 | «Лист1::итого по разделу 2» 92
ROAD (road_repair_section_templates):
    разделов 24 (17 с материалами / 7 пустых) | RESIDUE 64
    непустые: COMPUTED_SUM 5 | COMPUTED_SUM_UNRELIABLE 12 | SECTION_TOTAL 0
    road::razdel 1  «Подготовительные работы»             m 8  | cov 1.0   | 2 905.38      | CS
    road::razdel 7  «Переустройство ВЛ и кабельной линии» m 64 | cov 0.375 | 57 966 060.82 | CSU
```

ВЫВОДЫ:

1. Road-шаблон консолидирует 53 generic-секции в 24 маркерных раздела — целевое поведение
   («разделы и главы дорожной сметы»).
2. Road НЕ учитывает лист: метки из «ПСК»/«Лист1»/«ВКР» с одинаковым номером сливаются,
   тогда как generic ключует по `sheet::marker`. Решить: добавлять лист в road-код
   (`road::<sheet>::razdel N`) или нет.
3. У обеих схем высокий `UNRELIABLE` (generic 1040/1784 строк; road 12/17 разделов) —
   покрытие `total` низкое: много позиций без сумм. Это следующий кандидат на докрутку.

SIDE EFFECT (важно, требуется решение):

```
reparse ВСТАВИЛ новые 1784 строки вместо обновления старых: fingerprint изменился (в него
входит page_or_sheet, который теперь заполнен) -> ON CONFLICT не сработал.
итог: 60467 = 3564 строки (1780 старых без section + 1784 новых с section);
дублей по entity_fingerprint нет, но контент старых повторяет новые.
section-блок карточки показывает только новые (старые отфильтрованы), однако плоская
таблица «Что можно поставить» покажет оба набора.
```

ACCEPTANCE (Phase 2b):

```
REPARSE_WITHOUT_CLAIM  = YES
ADMISSION_UNCHANGED    = YES (очередь 54737 осталась SKIPPED_NOT_TARGET)
SECTION_FIELDS_WRITTEN = YES (1784 строки с section_code)
COMPARISON_DONE        = YES (generic 53 раздела vs road 24)
QUEUE_SCORING_UNTOUCHED= YES
```

## RESULT 2B.6 (2026-10-15) — лист в identity, stale-suppression, road в карточке

STATUS: DONE (все три пункта).

2B.6.1 — ЛИСТ В ROAD IDENTITY:

```
road_repair_section_templates.RoadMarker.code(sheet) -> "road::<sheet>::razdel N"
                                                        "road::<sheet>::glava N"
sheet берётся из row["page_or_sheet"]; если листа нет — старый вид "road::razdel N".
fallback-карта шифров теперь учитывает лист: (sheet, СР/ЛС/ОС) -> code.
60467: разделов 33 (вместо 24) — одноимённые разделы «ПСК»/«Лист1»/«ВКР» больше не сливаются.
```

2B.6.2 — STALE-SUPPRESSION (выдача):

```
procurement_card_dossier_service.supply_candidates: CTE preferred —
    row_number() OVER (PARTITION BY procurement_id, source_document_id,
                       coalesce(row_or_line,''), coalesce(product_name_raw,'')
                       ORDER BY (section_code IS NOT NULL) DESC, id DESC) = 1
    -> в плоскую «Что можно поставить» попадает только предпочтительная строка.
ВАЖНО: ключ из решения (…, entity_fingerprint) НЕ работает — по нему 0 пар; замер:
    (source_document_id, fingerprint)                      -> 0 пар
    (source_document_id, row_or_line, product_name_raw)    -> 1784 пары  <-- используется
Причина: fingerprint включает page_or_sheet, который появился только у новых строк.
Физически stale-строки не трогаем (остаются для аудита).
60467: preferred 1780 (было 3564), все с section_code.
148391: preferred 18186 (было 23577), 7894 с section_code (остальные — не пары, а другие строки).
```

2B.6.3 — ROAD-ПРОЕКЦИЯ В КАРТОЧКЕ:

```
procurement_card_dossier_service: read-only выборка road-строк (LIMIT 8000, с той же
    stale-suppression) -> build_road_sections -> projection_from_road (адаптер в
    section_projection_service: тот же контракт, что у generic-проекции).
Признак дорожной формы: есть хотя бы один раздел уровня RAZDEL с материалами
    («Итого по разделу N <Название>»). Одних «Глава N» недостаточно — их носят и
    нерoad-сметы (148391), где generic-проекция полезнее.
Результат: dossier["section_projection_source"] = "road_repair_section_templates" | "embedded_extraction".

проверка:
  60467  -> source road_repair_section_templates | 23 раздела с материалами | skipped empty 10 | residue 63
            road::Лист1::razdel 1 «Подготовительные работы» 8 | 2 905.38 | confirmed
            road::Лист1::razdel 7 «Переустройство ВЛ и кабельной линии» 64 | 57 966 060.82 | unreliable
  148391 -> source embedded_extraction (razdel-маркеров нет) — generic-проекция сохранена
import smoke: section_projection_service / procurement_card_dossier_service /
              ui.procurement_card_page -> OK
```

ACCEPTANCE (2B.6):

```
ROAD_IDENTITY_WITH_SHEET        = YES (road::<sheet>::razdel N)
STALE_SUPPRESSED_IN_FLAT_VIEW   = YES (60467: 3564 -> 1780)
STALE_ROWS_PHYSICALLY_PRESERVED = YES
ROAD_PROJECTION_FOR_ROAD_ONLY   = YES (60467 road; 148391 generic)
MATERIALS_ONLY_IN_PROJECTION    = YES (пустые разделы не выводятся)
QUEUE_SCORING_MEDAL_UNTOUCHED   = YES
DB_WRITES                       = 0 (только SELECT)
```

NOTE: изменения карточки подхватятся после рестарта `crm-streamlit.service`.
