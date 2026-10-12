-- WIP v1: обновлённая карточка УК / Паркингов — схема данных (PostgreSQL).
--
-- Идемпотентно: ALTER ... ADD COLUMN IF NOT EXISTS, CREATE TABLE/INDEX IF NOT EXISTS.
-- Применяется к канонической CRM DB (S13, база `crm`).
--
-- ОТОБРАЖЕНИЕ СПЕЦИФИКАЦИИ НА РЕАЛЬНУЮ СХЕМУ (проверено по DB metadata 2026-09-29):
--   * в спецификации таблица УК названа `companies`. В CRM такой таблицы НЕТ;
--     УК живут в `management_companies` (217 строк, owner crm_app) — это те же УК,
--     что показывает доска гидроизоляции. Поэтому расширяется `management_companies`.
--   * в спецификации объект назван `parking_objects`. В CRM такой таблицы НЕТ;
--     объекты/паркинги живут в `parking_prefunnel_objects` (owner crm_app).
--   * связь «УК <-> объект» УЖЕ существует как `mc_parking_links`
--     (mc_id -> management_companies.id, parking_object_id -> parking_prefunnel_objects.id).
--     Колонка `company_id` в объекте НЕ создаётся: это был бы второй источник истины.
--
-- Решения по типам:
--   * `serial` вместо identity — как в соседних таблицах домена;
--   * value-домены (reception_type, stage, access_status, severity, proposal_status,
--     activity_type, status) закрыты CHECK-констрейнтами: неизвестное значение
--     падает громко, а не пишется молча. Расширение списка требует миграции.
--   * `updated_at` имеет только DEFAULT now(); автоподдержка при UPDATE делается
--     в repository-слое (триггеры в этом домене не используются).

-- 1. УК: сайт, порядок приёма, стадия воронки УК
ALTER TABLE management_companies
  ADD COLUMN IF NOT EXISTS website varchar(255),
  ADD COLUMN IF NOT EXISTS reception_type varchar(30) DEFAULT 'daily',
  ADD COLUMN IF NOT EXISTS reception_schedule jsonb DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS stage varchar(50) DEFAULT 'lead';

ALTER TABLE management_companies
  DROP CONSTRAINT IF EXISTS management_companies_reception_type_check;
ALTER TABLE management_companies
  ADD CONSTRAINT management_companies_reception_type_check
  CHECK (reception_type IS NULL OR reception_type IN ('daily', 'scheduled'));

ALTER TABLE management_companies
  DROP CONSTRAINT IF EXISTS management_companies_stage_check;
ALTER TABLE management_companies
  ADD CONSTRAINT management_companies_stage_check
  CHECK (stage IS NULL OR stage IN (
    'lead', 'meeting_scheduled', 'meeting_held', 'access_granted', 'inspected',
    'offer_sent', 'tz_prep', 'bidding', 'in_progress', 'won', 'lost'));

CREATE INDEX IF NOT EXISTS idx_mc_stage ON management_companies (stage);

-- 2. Контактные лица УК (ЛПР / начальники эксплуатации / секретари)
CREATE TABLE IF NOT EXISTS company_contacts (
  id serial PRIMARY KEY,
  company_id integer NOT NULL REFERENCES management_companies (id) ON DELETE CASCADE,
  full_name varchar(255) NOT NULL,
  role varchar(100),
  phone varchar(50),
  phone_ext varchar(20),
  email varchar(100),
  is_primary boolean DEFAULT false,
  comment text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON company_contacts (company_id);
-- У УК не может быть двух «основных» контактов.
CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_company_primary
  ON company_contacts (company_id) WHERE is_primary;

-- 3. Встречи / активности УК (правая колонка карточки + Google Calendar)
CREATE TABLE IF NOT EXISTS company_activities (
  id serial PRIMARY KEY,
  company_id integer NOT NULL REFERENCES management_companies (id) ON DELETE CASCADE,
  activity_type varchar(30) NOT NULL,
  title varchar(255) NOT NULL,
  description text,
  start_time timestamptz NOT NULL,
  end_time timestamptz NOT NULL,
  status varchar(30) DEFAULT 'planned',
  google_event_id varchar(255),
  google_event_link text,
  assigned_user_id integer,
  created_at timestamptz DEFAULT now(),
  CONSTRAINT company_activities_type_check
    CHECK (activity_type IN ('meeting', 'call', 'inspection', 'follow_up')),
  CONSTRAINT company_activities_status_check
    CHECK (status IS NULL OR status IN ('planned', 'completed', 'cancelled')),
  CONSTRAINT company_activities_period_check CHECK (end_time >= start_time)
);

CREATE INDEX IF NOT EXISTS idx_activities_company ON company_activities (company_id);
CREATE INDEX IF NOT EXISTS idx_activities_start ON company_activities (start_time);
-- Одно событие Google Calendar не может быть привязано к двум встречам.
CREATE UNIQUE INDEX IF NOT EXISTS uq_activities_google_event
  ON company_activities (google_event_id) WHERE google_event_id IS NOT NULL;

-- 4. Объекты/паркинги: дефектовка, техрешение, КП, ТЗ и торги
ALTER TABLE parking_prefunnel_objects
  ADD COLUMN IF NOT EXISTS access_status varchar(50) DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS inspection_date timestamptz,
  ADD COLUMN IF NOT EXISTS leak_types jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS severity varchar(30) DEFAULT 'medium',
  ADD COLUMN IF NOT EXISTS inspection_notes text,
  ADD COLUMN IF NOT EXISTS inspection_photos jsonb DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS tech_solution_type varchar(100),
  ADD COLUMN IF NOT EXISTS commercial_proposal_sum numeric(12, 2),
  ADD COLUMN IF NOT EXISTS commercial_proposal_file_url text,
  ADD COLUMN IF NOT EXISTS proposal_status varchar(50) DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS tz_approved_by_client boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS tz_file_url text,
  ADD COLUMN IF NOT EXISTS tender_url text,
  ADD COLUMN IF NOT EXISTS tender_number varchar(100),
  ADD COLUMN IF NOT EXISTS tender_nmck numeric(12, 2),
  ADD COLUMN IF NOT EXISTS tender_end_date timestamptz;

ALTER TABLE parking_prefunnel_objects
  DROP CONSTRAINT IF EXISTS ppf_objects_access_status_check;
ALTER TABLE parking_prefunnel_objects
  ADD CONSTRAINT ppf_objects_access_status_check
  CHECK (access_status IS NULL OR access_status IN ('pending', 'granted', 'rejected'));

ALTER TABLE parking_prefunnel_objects
  DROP CONSTRAINT IF EXISTS ppf_objects_severity_check;
ALTER TABLE parking_prefunnel_objects
  ADD CONSTRAINT ppf_objects_severity_check
  CHECK (severity IS NULL OR severity IN ('critical', 'medium', 'minor'));

ALTER TABLE parking_prefunnel_objects
  DROP CONSTRAINT IF EXISTS ppf_objects_proposal_status_check;
ALTER TABLE parking_prefunnel_objects
  ADD CONSTRAINT ppf_objects_proposal_status_check
  CHECK (proposal_status IS NULL OR proposal_status IN ('draft', 'sent', 'approved', 'rejected'));

CREATE INDEX IF NOT EXISTS idx_ppf_objects_tender_end
  ON parking_prefunnel_objects (tender_end_date);