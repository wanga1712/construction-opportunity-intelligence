"""CRM-SYNC-2 DDL Migration.

Adds deadline_trust column to crm_procurements and applies a CHECK constraint.

Idempotent: safe to run multiple times.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DDL_STEPS = [
    # 1. Add column if not exists
    "ALTER TABLE crm_procurements ADD COLUMN IF NOT EXISTS deadline_trust TEXT",
    # 2. Drop constraint if exists to ensure idempotency
    "ALTER TABLE crm_procurements DROP CONSTRAINT IF EXISTS chk_deadline_trust",
    # 3. Add constraint
    "ALTER TABLE crm_procurements ADD CONSTRAINT chk_deadline_trust CHECK (deadline_trust IN ('TRUSTED', 'RECOVERED', 'UNRECOVERABLE_LEGACY'))",
]


def run_migration(crm_db) -> dict:
    """Applies DDL migration to crm DB.

    Args:
        crm_db: CRM database object from connect_databases()

    Returns:
        dict with keys ok=True/False, steps=N, error=str|None
    """
    ok_count = 0
    for i, ddl in enumerate(_DDL_STEPS, 1):
        try:
            crm_db.execute_update(ddl.strip())
            logger.info(f"migration step {i}/{len(_DDL_STEPS)} OK")
            ok_count += 1
        except Exception as exc:
            logger.error(f"migration step {i} FAILED: {exc}")
            return {"ok": False, "steps": ok_count, "error": str(exc)}

    logger.info(f"migration complete: {ok_count}/{len(_DDL_STEPS)} steps")
    return {"ok": True, "steps": ok_count, "error": None}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/opt/CRM_Streamlit")
    sys.path.insert(0, "/opt/pythonProject89")
    from dotenv import load_dotenv

    load_dotenv("/opt/CRM_Streamlit/.env")
    from src.services.db_bootstrap import connect_databases

    logging.basicConfig(level=logging.INFO)
    _, _, crm_db, _ = connect_databases()
    result = run_migration(crm_db)
    print(result)
    sys.exit(0 if result["ok"] else 1)
