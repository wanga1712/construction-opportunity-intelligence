# WIP CATEGORY_DISCOVERY_DYNAMIC_V1 — динамическое открытие embedded-категорий

Status: PARTIAL — фазы A/B реализованы и прогнаны read-only; фаза C и миграция
не применены. Owner: product registry / document intelligence.

Полная спека: `.codex_worktrees/category_discovery_dynamic_v1/WIP.md`.

## Текущее состояние

`scripts/promote_discovered_categories.py` уже реализует:

```text
Phase A: 279 фраз -> 44 семейства
Phase B: 25 SYNONYM_EXISTING / 19 NEW
Phase C: DRY_RUN, --promote не запускался
```

Таблицы `category_discovery_config` в БД ещё нет; скрипт работает на DEFAULTS
`10/20`.

## Что осталось

1. Применить миграцию `src/migrations/category_discovery_config_1.sql`.
2. Перепроверить Phase A/B с таблицей конфига:
   - конфиг должен читаться из `category_discovery_config`;
   - `min_distinct_procurements=10`, `min_occurrences=20`,
     `min_supply_value_rub=0`, `okpd_cluster_digits=4`,
     `default_medal='WOOD'`, `enabled=true`.
3. Согласовать список 19 NEW перед Phase C. Автопромоушен без ручного approval
   НЕ делаем.
4. Запустить Phase C `--promote` только для согласованных семейств:
   - создавать `crm_product_categories`/`crm_product_subcategories`;
   - `category_kind='PRODUCT'`, `lifecycle_state='DRAFT'`,
     `updated_by='AUTO_CANDIDATE'`, медаль `WOOD`;
   - идемпотентно: ключ `family + okpd_cluster`, повторный прогон не дублирует.
5. Зафиксировать отклонение: `category_registry_service.create_category()` не
   принимает `category_kind`/`lifecycle_state`; в скрипте уже есть отдельный
   `UPDATE` — проверить, что он корректен и задокументирован.

## Правила, которые нельзя сломать

```text
Только OBJECT / EMBEDDED_MATERIAL.
DIRECT исключён.
SERVICE_NO_OBJECT / AMBIGUOUS исключены.
Существующие категории не трогаем.
Новая категория по умолчанию DRAFT + WOOD.
Поставка 50 тыс. руб. не отбрасывается (min_supply_value_rub=0).
Повторный прогон не создаёт дубликаты.
```

## Acceptance

```text
CATEGORY_DISCOVERY_CONFIG_EXISTS=YES
CONFIG_READ_FROM_DB=YES
PHASE_A_FAMILIES=44
PHASE_B_SYNONYM_EXISTING=25
PHASE_B_NEW=19
PHASE_C_CREATES_ONLY_APPROVED_NEW=YES
NEW_CATEGORY_STATE=DRAFT
NEW_CATEGORY_MEDAL=WOOD
DIRECT_NOT_PROMOTED=YES
MIN_SUPPLY_50K_NOT_DROPPED=YES
IDEMPOTENT_RERUN=YES
DB_WRITES=APPROVED_ONLY
```

## Проверки

```text
py_compile scripts/promote_discovered_categories.py
применение migration без ошибок; SELECT из category_discovery_config
dry-run с конфигом из таблицы: конфиг применяется
Phase C DRY_RUN до --promote; список NEW сверен вручную
после --promote: повторный dry-run/promote не создаёт дубликаты
```

## Out of scope

- правила/шаблоны встроенных категорий;
- admission / scoring / медали существующих категорий;
- layout/tabs карточки;
- DIRECT.
