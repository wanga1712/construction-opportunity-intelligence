-- Базовая схема мультипрофильного поиска CRM.
-- Таблицы не заменяют существующие crm_objects_index / crm_leads.
-- Они добавляют слой: пользовательский профиль + товарная группа + решение по объекту.

CREATE TABLE IF NOT EXISTS crm_product_groups (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_search_profiles (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner_user_id BIGINT,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crm_search_profile_groups (
    id BIGSERIAL PRIMARY KEY,
    search_profile_id BIGINT NOT NULL REFERENCES crm_search_profiles(id) ON DELETE CASCADE,
    product_group_id BIGINT NOT NULL REFERENCES crm_product_groups(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority_weight INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (search_profile_id, product_group_id)
);

CREATE TABLE IF NOT EXISTS crm_search_rules (
    id BIGSERIAL PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('global', 'profile', 'product_group', 'profile_group')),
    search_profile_id BIGINT REFERENCES crm_search_profiles(id) ON DELETE CASCADE,
    product_group_id BIGINT REFERENCES crm_product_groups(id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('include_keyword', 'exclude_keyword', 'include_phrase', 'exclude_phrase', 'okpd2_include', 'okpd2_exclude', 'region_include', 'region_exclude')),
    value TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    reason TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_search_rules_scope_active
    ON crm_search_rules(scope, is_active);

CREATE INDEX IF NOT EXISTS idx_crm_search_rules_profile_group
    ON crm_search_rules(search_profile_id, product_group_id, is_active);

CREATE TABLE IF NOT EXISTS crm_object_profile_decisions (
    id BIGSERIAL PRIMARY KEY,
    object_key TEXT NOT NULL,
    registry_type TEXT,
    tender_id BIGINT,
    source_type TEXT,
    search_profile_id BIGINT REFERENCES crm_search_profiles(id) ON DELETE CASCADE,
    product_group_id BIGINT REFERENCES crm_product_groups(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK (
        decision IN (
            'global_reject',
            'profile_reject',
            'profile_keep',
            'profile_review',
            'needs_documents',
            'documents_queued',
            'documents_parsed',
            'qualified_lead',
            'in_work',
            'archived'
        )
    ),
    priority_score INTEGER NOT NULL DEFAULT 0 CHECK (priority_score >= 0 AND priority_score <= 100),
    reason TEXT,
    matched_terms JSONB NOT NULL DEFAULT '[]'::jsonb,
    rejected_terms JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_model TEXT,
    decided_by TEXT NOT NULL DEFAULT 'system',
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (object_key, search_profile_id, product_group_id)
);

CREATE INDEX IF NOT EXISTS idx_crm_object_profile_decisions_object
    ON crm_object_profile_decisions(object_key);

CREATE INDEX IF NOT EXISTS idx_crm_object_profile_decisions_queue
    ON crm_object_profile_decisions(search_profile_id, product_group_id, decision, priority_score DESC);

CREATE TABLE IF NOT EXISTS crm_ai_training_events (
    id BIGSERIAL PRIMARY KEY,
    object_key TEXT,
    registry_type TEXT,
    tender_id BIGINT,
    search_profile_id BIGINT REFERENCES crm_search_profiles(id) ON DELETE SET NULL,
    product_group_id BIGINT REFERENCES crm_product_groups(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    comment TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_crm_ai_training_events_object
    ON crm_ai_training_events(object_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_crm_ai_training_events_profile_group
    ON crm_ai_training_events(search_profile_id, product_group_id, created_at DESC);

INSERT INTO crm_product_groups (code, name, description)
VALUES
    ('flooring', 'Напольные покрытия', 'Линолеум, ПВХ-плитка, ковролин, спортивные и другие покрытия.'),
    ('lighting', 'Светотехника', 'Внутреннее и наружное освещение, светильники, опоры, LED.'),
    ('curbstone', 'Бордюрный камень', 'Бордюр, бортовой камень, благоустройство улиц и дорог.'),
    ('drainage', 'Водоотводные системы', 'Лотки, дождеприёмники, дренаж, водоотведение.'),
    ('waterproofing', 'Гидроизоляция', 'Подвалы, паркинги, подземные этажи, протечки, гидроизоляционные работы.'),
    ('computers', 'Компьютеры и ИТ-оборудование', 'Ноутбуки, ПК, моноблоки, серверы, периферия, анализ ТЗ и рыночных конфигураций.')
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_at = NOW();

INSERT INTO crm_search_profiles (code, name, description)
VALUES
    ('default_flooring', 'Профиль: напольные покрытия', 'Базовый профиль поиска напольных покрытий.'),
    ('default_multi_materials', 'Профиль: объектные материалы', 'Базовый профиль для нескольких товарных направлений.'),
    ('default_computers', 'Профиль: компьютеры и ИТ', 'Базовый профиль анализа компьютерных закупок и ТЗ.')
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_at = NOW();

INSERT INTO crm_search_profile_groups (search_profile_id, product_group_id)
SELECT sp.id, pg.id
FROM crm_search_profiles sp
JOIN crm_product_groups pg ON (
    (sp.code = 'default_flooring' AND pg.code = 'flooring')
    OR (sp.code = 'default_multi_materials' AND pg.code IN ('lighting', 'curbstone', 'drainage', 'waterproofing'))
    OR (sp.code = 'default_computers' AND pg.code = 'computers')
)
ON CONFLICT (search_profile_id, product_group_id) DO UPDATE
SET is_active = TRUE;

