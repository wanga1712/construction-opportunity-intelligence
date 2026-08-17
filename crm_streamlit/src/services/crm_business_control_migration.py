"""Migration script to create CRM Business Control tables."""
from __future__ import annotations
import logging
import sys

logger = logging.getLogger("crm_business_control_migration")

_DDL_STEPS = [
    # 1. Rules for cheap signals
    """
    CREATE TABLE IF NOT EXISTS crm_category_signal_rules (
        id SERIAL PRIMARY KEY,
        category_code VARCHAR(100) NOT NULL,
        positive_terms TEXT[] NOT NULL DEFAULT '{}'::text[],
        negative_terms TEXT[] NOT NULL DEFAULT '{}'::text[],
        applicable_routes TEXT[] NOT NULL DEFAULT '{}'::text[],
        applicable_object_types TEXT[] NOT NULL DEFAULT '{}'::text[],
        source_fields TEXT[] NOT NULL DEFAULT '{"auction_name"}'::text[],
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_category_signal_rules_code ON crm_category_signal_rules(category_code)",
    
    # 2. Manual overrides at procurement level
    """
    CREATE TABLE IF NOT EXISTS crm_manual_overrides (
        procurement_id BIGINT PRIMARY KEY,
        business_relevance VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
        overall_research_action VARCHAR(50) NOT NULL DEFAULT 'METADATA_ONLY',
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        review_status VARCHAR(50) DEFAULT 'PENDING_REVIEW',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (business_relevance IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN', 'OUT_OF_PROFILE')),
        CHECK (overall_research_action IN ('SKIP', 'METADATA_ONLY', 'LIGHT_RESEARCH', 'PRIORITY_DOCS', 'DEEP_RESEARCH')),
        CHECK (review_status IN ('PENDING_REVIEW', 'APPROVED'))
    )
    """,

    # 3. Manual overrides at category opportunity level
    """
    CREATE TABLE IF NOT EXISTS crm_manual_category_overrides (
        id BIGSERIAL PRIMARY KEY,
        procurement_id BIGINT NOT NULL,
        category_code VARCHAR(100) NOT NULL,
        subcategory_code VARCHAR(100),
        opportunity_status VARCHAR(50) NOT NULL,
        expected_role VARCHAR(50) NOT NULL,
        commercial_entry_point VARCHAR(50) NOT NULL,
        expected_volume VARCHAR(50) NOT NULL,
        priority NUMERIC DEFAULT 0.0,
        research_action VARCHAR(50) NOT NULL,
        manual_candidate_level VARCHAR(50),
        manual_reason TEXT NOT NULL,
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(procurement_id, category_code),
        CHECK (opportunity_status IN ('CONFIRMED_SOURCE', 'LIKELY', 'POSSIBLE', 'UNLIKELY', 'ABSENT', 'MANUAL_REVIEW')),
        CHECK (expected_role IN ('PRIMARY_SUPPLY', 'EMBEDDED_MATERIAL', 'CONSUMABLE', 'OBJECT_OF_RESEARCH', 'AUXILIARY_CONTEXT', 'ABSENT', 'UNKNOWN')),
        CHECK (commercial_entry_point IN ('DIRECT_SUPPLY', 'SUPPLIER', 'SUB_CONTRACTOR', 'CONTRACTOR_PARTNER', 'NO_ENTRY', 'UNKNOWN')),
        CHECK (expected_volume IN ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN')),
        CHECK (research_action IN ('SKIP', 'METADATA_ONLY', 'LIGHT_RESEARCH', 'PRIORITY_DOCS', 'DEEP_RESEARCH')),
        CHECK (manual_candidate_level IN ('GOLD', 'SILVER', 'BRONZE', 'WOOD'))
    )
    """,

    # 4. Audit table
    """
    CREATE TABLE IF NOT EXISTS crm_manual_assessments_audit (
        id SERIAL PRIMARY KEY,
        procurement_id BIGINT NOT NULL,
        action_type VARCHAR(50) NOT NULL,
        user_name VARCHAR(100) NOT NULL,
        original_value JSONB,
        corrected_value JSONB,
        changed_fields JSONB,
        comment TEXT,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        approved_for_training BOOLEAN DEFAULT FALSE
    )
    """
]

def seed_default_signal_rules(crm_db) -> None:
    """Insert default registry rules for lighting and other categories."""
    rules = [
        {
            "category_code": "lighting",
            "positive_terms": ["освещение", "светильник", "опора", "электроосвещение", "светодиод", "линия освещения", "лампа", "прожектор"],
            "negative_terms": ["отопление", "водопровод"],
            "applicable_routes": ["CONSTRUCTION_INFRASTRUCTURE", "CONSTRUCTION_BUILDING"],
            "applicable_object_types": ["road_maintenance", "road"]
        }
    ]
    for r in rules:
        crm_db.execute_update(
            """
            INSERT INTO crm_category_signal_rules (
                category_code, positive_terms, negative_terms, applicable_routes, applicable_object_types
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (category_code) DO NOTHING
            """,
            (r["category_code"], r["positive_terms"], r["negative_terms"], r["applicable_routes"], r["applicable_object_types"])
        )

def run_migration(crm_db) -> dict:
    for i, ddl in enumerate(_DDL_STEPS, 1):
        try:
            crm_db.execute_update(ddl.strip())
            logger.info(f"DDL Step {i}/{len(_DDL_STEPS)} OK")
        except Exception as exc:
            logger.error(f"DDL Step {i} FAILED: {exc}")
            return {"ok": False, "error": str(exc)}
            
    try:
        seed_default_signal_rules(crm_db)
        logger.info("Signal rules seeding OK")
    except Exception as exc:
        logger.error(f"Rules seeding FAILED: {exc}")
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "error": None}

if __name__ == "__main__":
    sys.path.insert(0, "/opt/CRM_Streamlit")
    from dotenv import load_dotenv
    load_dotenv("/opt/CRM_Streamlit/.env")
    from src.services.db_bootstrap import connect_databases

    logging.basicConfig(level=logging.INFO)
    _, _, crm_db, warn = connect_databases()
    if warn:
        logger.warning(f"Bootstrap warning: {warn}")
    if crm_db:
        res = run_migration(crm_db)
        print(f"Migration result: {res}")
        sys.exit(0 if res["ok"] else 1)
    else:
        logger.error("CRM database connection failed.")
        sys.exit(1)
