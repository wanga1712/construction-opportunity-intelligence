"""???????? ????????? ?????? category_object_* ? CRM ??.

?????? ??????????? ?? ??????? 13, ?? ????? ? CRM ?? ?? 7-?.
?? ?? ?????? ??????? ?????????? ????????: ?????? ??????? ?????? ? seed-???????.
"""
from __future__ import annotations

import sys

sys.path.insert(0, '/opt/CRM_Streamlit')
sys.path.insert(0, '/opt/CRM_Streamlit/src')

from src.bootstrap import setup_source_path
setup_source_path()
from src.services.db_bootstrap import connect_databases

DDL = """
CREATE TABLE IF NOT EXISTS category_object_applicability (
    id BIGSERIAL PRIMARY KEY,
    category_code TEXT NOT NULL,
    subcategory_code TEXT NOT NULL DEFAULT '',
    object_class TEXT NOT NULL DEFAULT '',
    object_type TEXT NOT NULL DEFAULT '',
    work_type TEXT NOT NULL DEFAULT '',
    base_priority INTEGER NOT NULL DEFAULT 50,
    processing_mode TEXT NOT NULL DEFAULT 'candidate_search',
    min_anchor_score INTEGER NOT NULL DEFAULT 35,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    rules_version TEXT NOT NULL DEFAULT 'v1',
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (category_code, subcategory_code, object_class, object_type, work_type)
);

CREATE TABLE IF NOT EXISTS category_object_observations (
    id BIGSERIAL PRIMARY KEY,
    category_code TEXT NOT NULL,
    subcategory_code TEXT NOT NULL DEFAULT '',
    object_class TEXT NOT NULL DEFAULT '',
    object_type TEXT NOT NULL DEFAULT '',
    work_type TEXT NOT NULL DEFAULT '',
    document_id BIGINT,
    object_id BIGINT,
    tender_id BIGINT,
    registry_type TEXT,
    match_strength INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    quantity_found TEXT,
    technical_attributes_found JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_confidence NUMERIC(5,4),
    manager_status TEXT NOT NULL DEFAULT 'unreviewed',
    observation_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS category_object_priority_stats (
    category_code TEXT NOT NULL,
    subcategory_code TEXT NOT NULL DEFAULT '',
    object_class TEXT NOT NULL DEFAULT '',
    object_type TEXT NOT NULL DEFAULT '',
    work_type TEXT NOT NULL DEFAULT '',
    base_priority INTEGER NOT NULL DEFAULT 50,
    observed_precision NUMERIC(6,4) NOT NULL DEFAULT 0,
    observed_frequency NUMERIC(10,4) NOT NULL DEFAULT 0,
    manager_confirmation_rate NUMERIC(6,4) NOT NULL DEFAULT 0,
    sample_size INTEGER NOT NULL DEFAULT 0,
    suggested_adjustment INTEGER NOT NULL DEFAULT 0,
    effective_priority INTEGER NOT NULL DEFAULT 50,
    auto_apply_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    last_recalculated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (category_code, subcategory_code, object_class, object_type, work_type)
);

CREATE INDEX IF NOT EXISTS ix_category_object_observations_category
    ON category_object_observations(category_code, subcategory_code, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_category_object_observations_tender
    ON category_object_observations(tender_id, registry_type, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_category_object_applicability_enabled
    ON category_object_applicability(enabled, category_code, subcategory_code);
"""

SEED = """
INSERT INTO category_object_applicability (
    category_code,
    subcategory_code,
    object_class,
    object_type,
    work_type,
    base_priority,
    processing_mode,
    min_anchor_score,
    enabled,
    rules_version,
    notes
)
SELECT
    c.category_code,
    s.subcategory_code,
    '',
    '',
    '',
    CASE
        WHEN c.contour_code = 'computers' THEN 90
        WHEN c.category_code IN ('lighting', 'flooring', 'waterproofing', 'composites') THEN 65
        ELSE 55
    END,
    CASE
        WHEN c.contour_code = 'computers' THEN 'always'
        ELSE 'candidate_search'
    END,
    35,
    TRUE,
    'v1',
    'seed_from_crm_product_subcategories'
FROM crm_product_categories c
JOIN crm_product_subcategories s ON s.category_id = c.id
WHERE c.is_active = TRUE
  AND s.is_active = TRUE
ON CONFLICT (category_code, subcategory_code, object_class, object_type, work_type)
DO NOTHING;

INSERT INTO category_object_priority_stats (
    category_code,
    subcategory_code,
    object_class,
    object_type,
    work_type,
    base_priority,
    effective_priority,
    suggested_adjustment,
    auto_apply_allowed,
    updated_at
)
SELECT
    category_code,
    subcategory_code,
    object_class,
    object_type,
    work_type,
    base_priority,
    base_priority,
    0,
    FALSE,
    NOW()
FROM category_object_applicability
ON CONFLICT (category_code, subcategory_code, object_class, object_type, work_type)
DO NOTHING;
"""


def main() -> None:
    _radar, _tender, crm, warn = connect_databases()
    print('db_warning=', warn)
    crm.execute_update(DDL)
    crm.execute_update(SEED)
    counts = crm.execute_query(
        """
        SELECT 'applicability' AS kind, COUNT(*) AS total FROM category_object_applicability
        UNION ALL
        SELECT 'observations' AS kind, COUNT(*) AS total FROM category_object_observations
        UNION ALL
        SELECT 'priority_stats' AS kind, COUNT(*) AS total FROM category_object_priority_stats
        """
    )
    for row in counts:
        print(row)


if __name__ == '__main__':
    main()
