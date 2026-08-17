"""Queue Policy V2A DDL Migration.

Реализует:
1. Использование pg_advisory_xact_lock для предотвращения конкурентных миграций.
2. Ведение истории миграций в таблице migration_history.
3. Версионирование через rule_key UUID и supersedes_id lineage.
4. CRM Read Projection с authoritative_rule_key и authoritative_version.
5. Таблицу queue_policy_shadow_runs для общих параметров запусков.
6. Таблицу okpd_registry_revisions для отслеживания ревизий и хэшей правил.
7. Таблицу cohort_medians для хранения когортных медиан цен и сроков.
8. Версионированную таблицу AI-оценок procurement_ai_assessments (БД tender_monitor и crm).
9. Поля и CHECK constraints в crm_procurements для синхронизации статуса карточки закупки.
10. Восстановление после частичного успеха и идемпотентность.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

# Lock ID для pg_advisory_xact_lock (произвольное 64-битное число)
MIGRATION_LOCK_ID = 892341235612349012

# DDL для базы tender_monitor (сервер 7)
_TENDER_DDL_STEPS = [
    # 0. Расширения и история миграций
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    """
    CREATE TABLE IF NOT EXISTS migration_history (
        id SERIAL PRIMARY KEY,
        migration_name VARCHAR(100) NOT NULL UNIQUE,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # 1. Глобальные ревизии правил ОКПД
    """
    CREATE TABLE IF NOT EXISTS okpd_registry_revisions (
        revision BIGINT PRIMARY KEY,
        snapshot_hash VARCHAR(64) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by VARCHAR(100) NOT NULL
    )
    """,
    # 2. Справочник маршрутизации ОКПД
    """
    CREATE TABLE IF NOT EXISTS okpd_route_profiles (
        id BIGSERIAL PRIMARY KEY,
        rule_key UUID NOT NULL DEFAULT gen_random_uuid(),
        okpd_code VARCHAR(50) NOT NULL,
        match_mode VARCHAR(20) NOT NULL DEFAULT 'EXACT',
        okpd_name TEXT,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        route_profile VARCHAR(50) NOT NULL,
        prefilter_action VARCHAR(50) NOT NULL DEFAULT 'AI_REQUIRED',
        priority_weight NUMERIC NOT NULL DEFAULT 1.0,
        category_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
        document_policy VARCHAR(50),
        law_scope VARCHAR(50) NOT NULL DEFAULT 'ALL',
        lifecycle_scope VARCHAR(50) NOT NULL DEFAULT 'ALL',
        region_scope TEXT NOT NULL DEFAULT 'ALL',
        version INTEGER NOT NULL DEFAULT 1,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        supersedes_id BIGINT REFERENCES okpd_route_profiles(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        created_by VARCHAR(100) NOT NULL,
        CHECK (match_mode IN ('EXACT', 'PREFIX')),
        CHECK (
            prefilter_action IN (
                'AUTO_ROUTE',
                'AI_REQUIRED',
                'MANUAL_REVIEW',
                'EXCLUDE'
            )
        ),
        CHECK (law_scope IN ('44_FZ', '223_FZ', '615_PP', 'ALL')),
        CHECK (lifecycle_scope IN ('OPEN', 'AWARDED', 'ALL')),
        CHECK (priority_weight >= 0),
        CHECK (jsonb_typeof(category_candidates) = 'array')
    )
    """,
    # 3. Индексы на okpd_route_profiles
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_okpd_route_profiles_current_scope
    ON okpd_route_profiles (
        okpd_code,
        match_mode,
        law_scope,
        lifecycle_scope,
        region_scope
    )
    WHERE is_current
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_okpd_route_profiles_rule_version
    ON okpd_route_profiles(rule_key, version)
    """,
    # 4. Аудит-лог настроек ОКПД
    """
    CREATE TABLE IF NOT EXISTS okpd_route_registry_audit (
        id SERIAL PRIMARY KEY,
        rule_key UUID NOT NULL,
        rule_version INTEGER NOT NULL,
        request_id UUID,
        change_reason TEXT,
        server_source TEXT,
        action VARCHAR(20) NOT NULL,
        old_value JSONB,
        new_value JSONB,
        user_username VARCHAR(100),
        client_ip INET,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        CHECK (action IN ('CREATE', 'SUPERSEDE', 'DISABLE', 'ENABLE', 'PROJECT'))
    )
    """,
    # 5. Когортные медианы цен и сроков
    """
    CREATE TABLE IF NOT EXISTS cohort_medians (
        id SERIAL PRIMARY KEY,
        cohort_key VARCHAR(100) NOT NULL,
        cohort_size INT NOT NULL,
        median_price NUMERIC NOT NULL,
        median_duration_days INT,
        version INTEGER NOT NULL DEFAULT 1,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (cohort_size >= 0),
        CHECK (median_price >= 0)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_cohort_medians_current 
    ON cohort_medians (cohort_key) 
    WHERE is_current
    """,
    # 6. Общая информация о запусках shadow runner
    """
    CREATE TABLE IF NOT EXISTS queue_policy_shadow_runs (
        run_id UUID PRIMARY KEY,
        status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
        rules_revision BIGINT NOT NULL,
        rules_snapshot_hash VARCHAR(64) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        total_processed INT DEFAULT 0,
        success_count INT DEFAULT 0,
        failed_count INT DEFAULT 0,
        error_message TEXT,
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED'))
    )
    """,
    # 7. Результаты shadow mode по объектам
    """
    CREATE TABLE IF NOT EXISTS queue_policy_shadow_results (
        id BIGSERIAL PRIMARY KEY,
        policy_run_id UUID NOT NULL REFERENCES queue_policy_shadow_runs(run_id) ON DELETE CASCADE,
        source_table VARCHAR(100) NOT NULL,
        source_id BIGINT NOT NULL,
        law_type VARCHAR(50),
        lifecycle VARCHAR(50),
        current_lane VARCHAR(50),
        current_priority NUMERIC,
        current_queue_position INT,
        prefilter_result VARCHAR(50),
        proposed_route_profile VARCHAR(50),
        proposed_object_type VARCHAR(50),
        proposed_procurement_type VARCHAR(50),
        proposed_categories JSONB,
        proposed_document_plan JSONB,
        candidate_level VARCHAR(50),
        candidate_score NUMERIC,
        proposed_priority NUMERIC,
        proposed_queue_position INT,
        confidence NUMERIC,
        reasons TEXT,
        status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
        error TEXT,
        model_version VARCHAR(50),
        prompt_version VARCHAR(50),
        schema_version VARCHAR(50),
        rules_version INTEGER NOT NULL,
        policy_version VARCHAR(50),
        started_at TIMESTAMPTZ,
        input_snapshot JSONB,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        expertise_status VARCHAR(20),
        expertise_source TEXT,
        expertise_record_id TEXT,
        expertise_match_method TEXT,
        expertise_match_confidence NUMERIC,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
        CHECK (candidate_level IN ('GOLD', 'SILVER', 'BRONZE', 'WOOD', 'UNASSESSED')),
        CHECK (lifecycle IN ('OPEN', 'AWARDED', 'ALL')),
        CHECK (prefilter_result IN ('AUTO_ROUTE', 'AI_REQUIRED', 'MANUAL_REVIEW', 'EXCLUDE', 'DUPLICATE', 'EXPIRED')),
        CHECK (expertise_status IN ('YES', 'NO', 'UNKNOWN')),
        CHECK (confidence BETWEEN 0.0 AND 1.0),
        CHECK (expertise_match_confidence BETWEEN 0.0 AND 1.0),
        CHECK (jsonb_typeof(reason_codes) = 'array')
    )
    """,
    # 8. Уникальный индекс для shadow run
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_policy_shadow_results_run_unique
    ON queue_policy_shadow_results (policy_run_id, source_table, source_id)
    """,
    # 9. Индексы для Shadow Report
    "CREATE INDEX IF NOT EXISTS idx_shadow_run_results_status ON queue_policy_shadow_results (policy_run_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_shadow_run_results_source ON queue_policy_shadow_results (source_table, source_id)",
    # 10. Обучающие примеры (RAG/AI) со статусом PENDING_REVIEW
    """
    CREATE TABLE IF NOT EXISTS training_examples (
        id SERIAL PRIMARY KEY,
        input_snapshot JSONB NOT NULL,
        expected_route_profile VARCHAR(50),
        expected_object_type VARCHAR(50),
        expected_procurement_type VARCHAR(50),
        expected_categories JSONB,
        review_status VARCHAR(50) NOT NULL DEFAULT 'PENDING_REVIEW',
        reviewed_by VARCHAR(100),
        reviewed_at TIMESTAMPTZ,
        version INT DEFAULT 1,
        CHECK (review_status IN ('DRAFT', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED')),
        CHECK (
            review_status <> 'APPROVED'
            OR (
                reviewed_by IS NOT NULL
                AND reviewed_at IS NOT NULL
            )
        )
    )
    """,
    # 11. Версионированная таблица AI-оценок в tender_monitor (authoritative)
    """
    CREATE TABLE IF NOT EXISTS procurement_ai_assessments (
        id BIGSERIAL PRIMARY KEY,
        procurement_id INTEGER NOT NULL,
        assessment_version INTEGER NOT NULL DEFAULT 1,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
        input_fingerprint VARCHAR(64) NOT NULL,
        model_version VARCHAR(50),
        prompt_version VARCHAR(50),
        rules_version INTEGER NOT NULL,
        proposed_route_profile VARCHAR(50),
        proposed_object_type VARCHAR(50),
        proposed_procurement_type VARCHAR(50),
        proposed_categories JSONB,
        proposed_level VARCHAR(50),
        confidence NUMERIC,
        reasons TEXT,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        error_message TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        assessment_stability VARCHAR(30) NOT NULL DEFAULT 'UNSTABLE',
        stability_count INTEGER NOT NULL DEFAULT 1,
        stable_since TIMESTAMPTZ,
        assessment_changed BOOLEAN DEFAULT FALSE,
        previous_assessment_id BIGINT,
        change_fields JSONB DEFAULT '[]'::jsonb,
        normalized_result JSONB DEFAULT '{}'::jsonb,
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
        CHECK (proposed_level IN ('GOLD', 'SILVER', 'BRONZE', 'WOOD', 'UNASSESSED')),
        CHECK (confidence BETWEEN 0.0 AND 1.0),
        CHECK (jsonb_typeof(reason_codes) = 'array')
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_procurement_ai_assessments_active 
    ON procurement_ai_assessments (procurement_id) 
    WHERE is_current
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_procurement_ai_assessments_version 
    ON procurement_ai_assessments (procurement_id, assessment_version)
    """,
    # ALTER TABLE для обновления существующей схемы tender_monitor
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS assessment_stability VARCHAR(30) NOT NULL DEFAULT 'UNSTABLE'",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS stability_count INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS stable_since TIMESTAMPTZ",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS assessment_changed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS previous_assessment_id BIGINT",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS change_fields JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS normalized_result JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE procurement_ai_assessments ALTER COLUMN proposed_route_profile TYPE VARCHAR(255)",
    "ALTER TABLE procurement_ai_assessments ALTER COLUMN proposed_object_type TYPE VARCHAR(255)",
    "ALTER TABLE procurement_ai_assessments ALTER COLUMN proposed_procurement_type TYPE VARCHAR(255)"
]

# DDL для базы crm (сервер 13) - read projection
_CRM_DDL_STEPS = [
    # 0. Расширения и история миграций
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    """
    CREATE TABLE IF NOT EXISTS migration_history (
        id SERIAL PRIMARY KEY,
        migration_name VARCHAR(100) NOT NULL UNIQUE,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # 1. CRM Read-Projection справочника ОКПД
    """
    CREATE TABLE IF NOT EXISTS okpd_route_profiles (
        id BIGSERIAL PRIMARY KEY,
        authoritative_rule_key UUID NOT NULL,
        authoritative_id BIGINT NOT NULL,
        authoritative_version INTEGER NOT NULL,
        okpd_code VARCHAR(50) NOT NULL,
        match_mode VARCHAR(20) NOT NULL DEFAULT 'EXACT',
        okpd_name TEXT,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        route_profile VARCHAR(50) NOT NULL,
        prefilter_action VARCHAR(50) NOT NULL DEFAULT 'AI_REQUIRED',
        priority_weight NUMERIC NOT NULL DEFAULT 1.0,
        category_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
        document_policy VARCHAR(50),
        law_scope VARCHAR(50) NOT NULL DEFAULT 'ALL',
        lifecycle_scope VARCHAR(50) NOT NULL DEFAULT 'ALL',
        region_scope TEXT NOT NULL DEFAULT 'ALL',
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        projection_status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
        CHECK (match_mode IN ('EXACT', 'PREFIX')),
        CHECK (
            prefilter_action IN (
                'AUTO_ROUTE',
                'AI_REQUIRED',
                'MANUAL_REVIEW',
                'EXCLUDE'
            )
        ),
        CHECK (law_scope IN ('44_FZ', '223_FZ', '615_PP', 'ALL')),
        CHECK (lifecycle_scope IN ('OPEN', 'AWARDED', 'ALL')),
        CHECK (priority_weight >= 0),
        CHECK (jsonb_typeof(category_candidates) = 'array'),
        CHECK (projection_status IN ('SUCCESS', 'FAILED', 'STALE'))
    )
    """,
    # 2. Уникальный индекс на пару ключ-версия в проекции
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_okpd_route_profiles_proj_key_version
    ON okpd_route_profiles (authoritative_rule_key, authoritative_version)
    """,
    # 3. Индекс на актуальные текущие правила
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_okpd_route_profiles_proj_active
    ON okpd_route_profiles (
        okpd_code,
        match_mode,
        law_scope,
        lifecycle_scope,
        region_scope
    )
    WHERE is_current
    """,
    # 4. CRM Read-Projection для версионированных AI-оценок
    """
    CREATE TABLE IF NOT EXISTS procurement_ai_assessments (
        id BIGSERIAL PRIMARY KEY,
        authoritative_id BIGINT NOT NULL,
        procurement_id INTEGER NOT NULL,
        assessment_version INTEGER NOT NULL,
        is_current BOOLEAN NOT NULL DEFAULT TRUE,
        status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
        input_fingerprint VARCHAR(64) NOT NULL,
        model_version VARCHAR(50),
        prompt_version VARCHAR(50),
        rules_version INTEGER NOT NULL,
        proposed_route_profile VARCHAR(50),
        proposed_object_type VARCHAR(50),
        proposed_procurement_type VARCHAR(50),
        proposed_categories JSONB,
        proposed_level VARCHAR(50),
        confidence NUMERIC,
        reasons TEXT,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        error_message TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        assessment_stability VARCHAR(30) NOT NULL DEFAULT 'UNSTABLE',
        stability_count INTEGER NOT NULL DEFAULT 1,
        stable_since TIMESTAMPTZ,
        assessment_changed BOOLEAN DEFAULT FALSE,
        previous_assessment_id BIGINT,
        change_fields JSONB DEFAULT '[]'::jsonb,
        normalized_result JSONB DEFAULT '{}'::jsonb,
        CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
        CHECK (proposed_level IN ('GOLD', 'SILVER', 'BRONZE', 'WOOD', 'UNASSESSED')),
        CHECK (confidence BETWEEN 0.0 AND 1.0),
        CHECK (jsonb_typeof(reason_codes) = 'array')
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_ai_assessments_proj_active 
    ON procurement_ai_assessments (procurement_id) 
    WHERE is_current
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_ai_assessments_proj_version 
    ON procurement_ai_assessments (procurement_id, assessment_version)
    """,
    # ALTER TABLE для обновления существующей схемы crm (проекции)
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS assessment_stability VARCHAR(30) NOT NULL DEFAULT 'UNSTABLE'",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS stability_count INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS stable_since TIMESTAMPTZ",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS assessment_changed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS previous_assessment_id BIGINT",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS change_fields JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE procurement_ai_assessments ADD COLUMN IF NOT EXISTS normalized_result JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE procurement_ai_assessments ALTER COLUMN proposed_route_profile TYPE VARCHAR(255)",
    "ALTER TABLE procurement_ai_assessments ALTER COLUMN proposed_object_type TYPE VARCHAR(255)",
    "ALTER TABLE procurement_ai_assessments ALTER COLUMN proposed_procurement_type TYPE VARCHAR(255)",
    # 5. Добавление колонок и CHECK constraints в crm_procurements для статусов карточки
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_assessment_status VARCHAR(30) NOT NULL DEFAULT 'UNASSESSED'",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_assessment_version INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_assessment_fingerprint VARCHAR(64)",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_assessed_at TIMESTAMPTZ",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS manual_override BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_assessment_stability VARCHAR(30) NOT NULL DEFAULT 'UNSTABLE'",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_stability_count INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS ai_stable_since TIMESTAMPTZ",
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS reassessment_requested BOOLEAN NOT NULL DEFAULT FALSE",
    """
    ALTER TABLE crm_procurements DROP CONSTRAINT IF EXISTS chk_crm_procurements_ai_status
    """,
    """
    ALTER TABLE crm_procurements ADD CONSTRAINT chk_crm_procurements_ai_status 
      CHECK (ai_assessment_status IN ('UNASSESSED', 'QUEUED', 'RUNNING', 'COMPLETED', 'NEEDS_REVIEW', 'OUT_OF_PROFILE', 'FAILED', 'STALE'))
    """
]

def run_migration(tender_db, crm_db) -> dict:
    migration_name = "QUEUE-POLICY-V2A-LIVE-ASSESSMENT-FINAL-V2"
    
    def _get_first(row) -> Any:
        if row is None:
            return None
        if isinstance(row, dict):
            return list(row.values())[0]
        return row[0]

    # 1. Применяем миграции к tender_monitor (сервер 7)
    logger.info("Applying migrations to 'tender_monitor'...")
    conn_t = tender_db.get_connection()
    tender_applied = False
    try:
        with conn_t:
            with conn_t.cursor() as cur:
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
                except Exception as ext_err:
                    logger.error(f"Failed to verify/create pgcrypto extension: {ext_err}. Check DB privileges.")
                    raise
                
                # Получаем advisory lock на транзакцию
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
                
                # Проверяем историю миграций
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'public' AND table_name = 'migration_history'
                    )
                """)
                if _get_first(cur.fetchone()):
                    cur.execute("SELECT EXISTS(SELECT 1 FROM migration_history WHERE migration_name = %s)", (migration_name,))
                    if _get_first(cur.fetchone()):
                        logger.info(f"Migration '{migration_name}' already applied to tender_monitor. Skipping DDL.")
                        tender_applied = True
                
                if not tender_applied:
                    # Накатываем DDL
                    for ddl in _TENDER_DDL_STEPS:
                        cur.execute(ddl.strip())
                    # Записываем в историю
                    cur.execute("INSERT INTO migration_history (migration_name) VALUES (%s)", (migration_name,))
        logger.info("tender_monitor migration OK")
    except Exception as exc:
        conn_t.rollback()
        logger.error(f"tender_monitor migration FAILED: {exc}")
        return {"ok": False, "steps": 0, "error": f"tender_monitor: {exc}"}

    # 2. Применяем миграции к crm (сервер 13)
    logger.info("Applying migrations to 'crm'...")
    conn_c = crm_db._connection
    crm_applied = False
    if conn_c:
        try:
            with conn_c:
                with conn_c.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
                    
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_schema = 'public' AND table_name = 'migration_history'
                        )
                    """)
                    if _get_first(cur.fetchone()):
                        cur.execute("SELECT EXISTS(SELECT 1 FROM migration_history WHERE migration_name = %s)", (migration_name,))
                        if _get_first(cur.fetchone()):
                            logger.info(f"Migration '{migration_name}' already applied to crm. Skipping DDL.")
                            crm_applied = True
                    
                    if not crm_applied:
                        for ddl in _CRM_DDL_STEPS:
                            cur.execute(ddl.strip())
                        cur.execute("INSERT INTO migration_history (migration_name) VALUES (%s)", (migration_name,))
            logger.info("crm migration OK")
        except Exception as exc:
            conn_c.rollback()
            logger.error(f"crm migration FAILED: {exc}")
            return {"ok": False, "steps": len(_TENDER_DDL_STEPS), "error": f"crm: {exc}"}
    else:
        try:
            for ddl in _CRM_DDL_STEPS:
                crm_db.execute_update(ddl.strip())
        except Exception as exc:
            logger.error(f"crm fallback migration FAILED: {exc}")
            return {"ok": False, "steps": len(_TENDER_DDL_STEPS), "error": f"crm_fallback: {exc}"}

    return {"ok": True, "steps": len(_TENDER_DDL_STEPS) + len(_CRM_DDL_STEPS), "error": None}

if __name__ == "__main__":
    sys.path.insert(0, "/opt/CRM_Streamlit")
    sys.path.insert(0, "/opt/pythonProject89")
    from dotenv import load_dotenv

    load_dotenv("/opt/CRM_Streamlit/.env")
    from src.services.db_bootstrap import connect_databases

    logging.basicConfig(level=logging.INFO)
    _radar, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning(f"Connection warning: {warn}")
    result = run_migration(tender_db, crm_db)
    print(result)
    sys.exit(0 if result["ok"] else 1)
