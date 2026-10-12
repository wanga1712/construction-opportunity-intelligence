-- hydro_manual_override_1.sql
-- Разделение «источник (автозагрузка)» и «поле менеджера (ручной ввод)».
--
-- Зачем: ночной синк NSPD обновляет только source-owned факты. Ручные правки
-- менеджера живут в отдельном jsonb и не могут быть затёрты загрузчиком по
-- построению: загрузчик физически не пишет manual_overrides.
--
-- Совместимо: только ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS,
-- без DROP/RENAME/DELETE и без смены владельцев.
--
-- Владельцы (проверено в pg_class 2026-09-29):
--   parking_prefunnel_objects -> crm_app  (DDL применяет crm_app)
--   management_companies      -> crm_app  (DDL применяет crm_app)
--
-- Метрики синка намеренно НЕ добавляются: crm_hydro_source_health принадлежит
-- роли postgres, а уже существующих колонок достаточно для требования
-- «время последнего синка + количество записей + SUCCESS/FAILED»:
--   last_attempt_at / last_success_at / status / rows_seen / safe_error_class
--   / safe_error_message.

-- 1. Ручные переопределения по объектам/паркингам (бизнес-поля карточки).
ALTER TABLE parking_prefunnel_objects
  ADD COLUMN IF NOT EXISTS manual_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

-- 2. Ручные переопределения по УК (сайт, тип приёма, график, стадия).
ALTER TABLE management_companies
  ADD COLUMN IF NOT EXISTS manual_overrides jsonb NOT NULL DEFAULT '{}'::jsonb;

-- 3. Дешёвый поиск объектов, у которых есть ручные правки.
CREATE INDEX IF NOT EXISTS idx_ppf_objects_manual_overrides
  ON parking_prefunnel_objects USING gin (manual_overrides);

COMMENT ON COLUMN parking_prefunnel_objects.manual_overrides IS
  'Ручные правки менеджера по колонкам карточки. Ночной синк их не читает и не пишет.';
COMMENT ON COLUMN management_companies.manual_overrides IS
  'Ручные правки менеджера по УК. Ночной синк их не читает и не пишет.';