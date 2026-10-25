# WIP OBJECT_QUEUE_MODEL_NORMALIZATION_V1 — объектные продажи: очередь и модель

Status: ПРИОРИТЕТ / СПЕКА УТОЧНЯЕТСЯ. Owner: document queue + model normalization.

## Цель

Для OBJECT / EMBEDDED_MATERIAL:

1. Если закупка уже «Идёт исполнение» (торги завершены, подрядчик определён,
   есть даты поставки/исполнения), а документы ещё не скачаны/разобраны,
   она должна попадать в очередь впереди по свежести.
2. Первыми скачиваем Excel/сметные файлы.
3. Не трогаем очереди DIRECT_SUPPLY и «Идут торги».
4. После находки в смете отправляем в модель; если данных достаточно —
   нормализуем технические характеристики, наименование, количество, цену.
5. Модель перепроверяет медаль по тем же правилам категории.
6. Если есть средняя цена по аналогичной категории/товару — используем как
   ориентир «ниже/выше среднего».

## Правила

```text
OBJECT_EXECUTION_FIRST=YES
DIRECT_SUPPLY_QUEUE_UNTOUCHED=YES
TORGI_QUEUE_UNTOUCHED=YES
DOWNLOAD_ORDER=EXCEL_SMETA_FIRST
MODEL_NORMALIZATION_ONLY_WHEN_ENOUGH_DATA=YES
MODEL_MAY_REQUEST_MORE_DOCUMENTS=YES
NO_MATCH_IN_ESTIMATE_STOPS_DOWNLOAD=YES
MODEL_BATCH_SIZE=30
MEDAL_REVALIDATION_SAME_RULES=YES
AVERAGE_PRICE_BENCHMARK=OPTIONAL
DB_WRITES=APPROVED_ONLY
MODEL_DOC_REQUESTS_COUNTED=YES
ALWAYS_SHOW_CATEGORY_RESULT=YES
```

## Фазы

### Phase 0 — inventory очереди объектных исполнений

Read-only:

```text
CURRENT OBJECT/EMBEDDED opportunities
commercial_state / crm_stage = исполнение
document_processing_queue status NOT COMPLETED
```

Посчитать объём и свежесть.

### Phase 1 — отдельный lane/priority для object execution

Добавить/настроить queue lane/priority так, чтобы object-execution шёл впереди,
но не пересекался с DIRECT_SUPPLY и OPEN/TORGI.

### Phase 2 — download order: Excel/smeta first

В selection/download plan сначала `.xlsx/.xlsm/.xls` сметы/расчёты, затем
остальные документы.

### Phase 3 — model normalization

Если в смете найдена категория:

- собрать:
  - product_name / manufacturer / brand / model;
  - quantity / unit;
  - unit_price / total;
  - technical attributes;
- если данных достаточно — нормализовать и **сразу писать в карточку**;
- если нет — оставить сырое, но не выдумывать.

Правки в карточке разрешены по ходу.

### Phase 3.1 — model-driven document request

Модель должна уметь возвращать команду на доскачивание/переразбор:

```text
если в смете категория найдена, но данных для нормализации мало:
    модель запрашивает дополнительные документы закупки;
    закупка ставится в отдельную model-driven очередь;
    скачиваются/парсятся только запрошенные документы.

контракт/приложения подрядчика тоже могут быть запрошены:
    внутри может быть смета подрядчика;
    если файл не получен или внутри нет таблиц/текста — NO_FACTS, не ошибка;
    scanned-таблицы без OCR-результата — не ошибка.

если в смете ничего не нашлось:
    дальше документы не качаем;
    закупка не уходит в глубокую обработку.
```

Батчинг:

```text
MODEL_BATCH_SIZE = 30
модель берёт накопленный пул по 30 штук
очередь пополняется по мере готовности
```

Для каждой category opportunity считаем:

```text
model_document_requests_count
```

Это число раз, когда модель запрашивала доскачивание/переразбор документов.

### Phase 3.2 — model revalidation and feedback

После переразбора модель повторяет:

```text
normalization -> medal revalidation -> commit proposal
```

Если данных снова недостаточно — фиксируем reason, не зацикливаемся.
Итог показываем в любом случае: найдено/ошибка/не найдено дальше ничего.

### Phase 4 — medal revalidation

Прогнать текущие правила медали для этой opportunity; сравнить с выданной
ранее медалью. Не менять authority модели.

### Phase 5 — average price benchmark

Опционально:

```text
средняя цена по category_code + subcategory_code + product_name_normalized
если данных нет — не выводим бенчмарк
```

Показывать «цена ниже/выше среднего по категории».

## Acceptance (canary)

```text
OBJECT_EXECUTION_CLAIMED_AHEAD=YES
DIRECT_AND_TORGI_QUEUE_UNCHANGED=YES
EXCEL_DOWNLOADED_FIRST=YES
NORMALIZED_WHEN_ENOUGH_DATA=YES
MODEL_CAN_REQUEST_MORE_DOCUMENTS=YES
NO_MATCH_IN_ESTIMATE_STOPS_DOWNLOAD=YES
MODEL_BATCH_SIZE=30
MEDAL_REVALIDATED=YES
AVERAGE_PRICE_OPTIONAL_NOT_FAKED=YES
DB_WRITES=APPROVED_ONLY
```

## Открытые вопросы

1. Исполнение определяем как: торги завершены, подрядчик определён, есть даты
   поставки/исполнения. Базово `commercial_state=FOLLOW_UP_AWARDED` +
   `delivery_start_date`/`delivery_end_date`/`execution_*`.
2. Model normalization пишется сразу в карточку; правим по ходу.
3. Benchmark: `category_code + subcategory_code + product_name_normalized`.

## Out of scope

- DIRECT_SUPPLY queue;
- TORGI/OPEN queue;
- `.xls` parser (отдельный WIP);
- scoring authority changes.

## Формат обработки файлов (принят 2026-10-16)

Задокументированный формат: скачивание нужных документов **вне очереди** через
штатный `DownloadCoordinator` + разбор **вне очереди** по категории закупки, без
ослабления admission. Автоконвертация `.xls/.rtf` (soffice) работает в pipeline.

Политика по контрактам (UNSUPPORTED_DOC_RECOVERY_V1, Phase 3.1):

```text
контракт/приложение подрядчика НЕ исключаем: внутри может быть смета подрядчика;
он допустим как fallback/model-requested документ, но не primary researchable;
если fallback-файл не скачался      -> NO_FACTS, а не FAILED;
если внутри нет текста/таблиц       -> NO_FACTS, а не FAILED;
ZIP под чужим расширением (.rtf/.doc/.xls) определяется по содержимому
и распаковывается (внутренние сметы извлекаются).
```

Практика: 8 FAILED `LOCAL_CLASSIFIED:*:UNSUPPORTED` закрыты (7 `xls->xlsx`,
1 контракт-как-ZIP с извлечением ЛСР). Нужен рестарт document-демонов.
