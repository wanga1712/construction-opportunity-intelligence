# WIP EMBEDDED_CATEGORY_DISCOVERY_CONFIRMATION_V1 — предложение новой категории из находок

Status: ГОТОВ К РАБОТЕ. Owner: embedded extraction + category registry + CRM UI.

## Цель

Для PROJECT/OBJECT закупки карточка должна показывать только категории, где
реально найдены товарные факты. Если найден устойчивый товарный кластер без
категории, система должна:

```text
показать в карточке «новая категория: <название>»
спросить подтверждение
при подтверждении создать category/subcategory
отправить название в модель для генерации search phrases
```

## Поведение

```text
категории с фактами          -> показываем
категории без фактов         -> скрываем
unmatched товарные кластеры  -> предлагаем как новую категорию
подтверждение пользователя   -> обязательный gate
создание без подтверждения   -> запрещено
```

## Кандидат

Полимерные водоотводные лотки:

```text
название: Полимерные водоотводные лотки
сигналы:  полимербетонные лотки, CompoMax Monoblock,
          водоотводные лотки
```

## Acceptance

```text
CARD_SHOWS_ONLY_FACTUAL_CATEGORIES=YES
EMPTY_CATEGORIES_HIDDEN=YES
UNMATCHED_CLUSTER_SUGGESTED=YES
NEW_CATEGORY_REQUIRES_CONFIRMATION=YES
MODEL_GENERATES_SEARCH_PHRASES=YES
DB_WRITES=APPROVED_ONLY_AFTER_CONFIRMATION
```

## Out of scope

- автоматическое создание без подтверждения;
- изменение scoring/medal;
- DIRECT strict registry.
