"""CRM-SYNC-1 DDL Migration.

Добавляет поля qualification_state и агрегаты в crm_procurements,
создаёт таблицу crm_category_candidates и индексы.

Идемпотентна: повторный запуск безопасен (IF NOT EXISTS / IF NOT EXISTS).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DDL_STEPS = [
    # 1. Новые поля crm_procurements
    """
    ALTER TABLE crm_procurements
      ADD COLUMN IF NOT EXISTS qualification_state TEXT NOT NULL DEFAULT 'unassessed'
        CHECK (qualification_state IN (
          'unassessed','candidate','confirmed','rejected','out_of_profile','manual_review'
        )),
      ADD COLUMN IF NOT EXISTS object_type TEXT,
      ADD COLUMN IF NOT EXISTS file_count INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS match_count INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS interesting_count INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS evidence_count INTEGER NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS last_daemon_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS product_names TEXT[]
    """,
    # 2. Кандидаты по категориям
    """
    CREATE TABLE IF NOT EXISTS crm_category_candidates (
      id                SERIAL PRIMARY KEY,
      procurement_id    INTEGER NOT NULL REFERENCES crm_procurements(id) ON DELETE CASCADE,
      category          TEXT NOT NULL,
      subcategory       TEXT,
      status            TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate','confirmed','rejected')),
      evidence_count    INTEGER NOT NULL DEFAULT 0,
      interesting_count INTEGER NOT NULL DEFAULT 0,
      confidence        NUMERIC(4,3),
      signal_source     TEXT,
      assessed_at       TIMESTAMPTZ,
      created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (procurement_id, category)
    )
    """,
    # 3. Индексы
    "CREATE INDEX IF NOT EXISTS idx_crm_proc_qualification ON crm_procurements(qualification_state)",
    "CREATE INDEX IF NOT EXISTS idx_crm_proc_source ON crm_procurements(source_table, source_id)",
    "CREATE INDEX IF NOT EXISTS idx_crm_catcand_proc ON crm_category_candidates(procurement_id)",
]


def run_migration(crm_db) -> dict:
    """Применяет DDL миграцию к crm DB.

    Args:
        crm_db: объект CRM-базы из connect_databases()

    Returns:
        dict с ключами ok=True/False, steps=N, error=str|None
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
