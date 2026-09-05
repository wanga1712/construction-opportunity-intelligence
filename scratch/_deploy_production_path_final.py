import os, sys

path_feeder = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/factual_feeder.py"
code_feeder = '''"""Factual Procurement Feeder into document_processing_queue.

Ensures that admission to document_processing_queue calculates and persists
current_research_generation_hash derived from canonical document identities.

Defect Correction:
- Compute current_research_generation_hash using resolve_document_links and compute_research_generation_hash.
- Tasks in document_processing_queue persist pipeline_generation and research_generation_hash.
- Task suppression checks: procurement_id + pipeline_generation + research_generation_hash.
- OLD_COMPLETED_GENERATION_BLOCKS_NEW_GENERATION = NO.
"""

from datetime import datetime, timezone
import hashlib, json, os, psycopg2, psycopg2.extras
from typing import Any, Dict, List, Optional

from src.services.commercial_routing_v3.card_research_state import (
    compute_research_generation_hash,
)
from src.services.commercial_routing_v3.document_links import resolve_document_links

PIPELINE_GENERATION = "S13_V2"
LOW_WATERMARK = 50
HIGH_WATERMARK = 200
FEED_BATCH_SIZE = 25


def _get_doc_db_conn():
    from dotenv import load_dotenv
    load_dotenv("/opt/CRM_Streamlit/.env")
    dsn = {
        "host": os.getenv("S13_DOCUMENT_DB_HOST") if os.getenv("S13_DOCUMENT_DB_HOST") not in (None, "", "S7") else "127.0.0.1",
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT") or os.getenv("CRM_DB_PORT") or "5432"),
        "dbname": "document_intelligence",
        "user": os.getenv("CRM_DB_USER") or "crm_app",
        "password": os.getenv("CRM_DB_PASSWORD") or "",
    }
    return psycopg2.connect(**dsn)


def compute_md5(data: Any) -> str:
    s = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


class FactualFeeder:
    """Headless feeder that admits procurements into document_processing_queue based on factual procurement data."""

    def __init__(self, crm_db: Any) -> None:
        self.crm_db = crm_db

    def admit_procurement(
        self,
        procurement_id: int,
        source_table: str,
        source_id: int,
        contract_number: Optional[str] = None,
        queue_lane: str = "crm_active_hot",
        priority_score: int = 50,
    ) -> Optional[int]:
        """Admit single procurement into document_processing_queue with durable research generation hash."""
        doc_res = resolve_document_links(
            source_table=source_table or "",
            source_id=source_id,
            contract_number=contract_number or "",
        )
        links = doc_res.get("links") or []
        gen_hash = compute_research_generation_hash(procurement_id, links, PIPELINE_GENERATION)

        conn = _get_doc_db_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, status, research_generation_hash
                    FROM document_processing_queue
                    WHERE procurement_id = %s
                      AND pipeline_generation = %s
                      AND research_generation_hash = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (procurement_id, PIPELINE_GENERATION, gen_hash),
                )
                existing = cur.fetchone()
                if existing:
                    return existing["id"]

                cur.execute(
                    """
                    INSERT INTO document_processing_queue (
                        procurement_id, source_table, source_id, contract_number,
                        research_action, queue_lane, priority_score, status,
                        pipeline_generation, research_generation_hash, created_at
                    ) VALUES (%s, %s, %s, %s, 'FULL_RESEARCH', %s, %s, 'PENDING', %s, %s, NOW())
                    RETURNING id
                    """,
                    (
                        procurement_id,
                        source_table,
                        source_id,
                        contract_number,
                        queue_lane,
                        priority_score,
                        PIPELINE_GENERATION,
                        gen_hash,
                    ),
                )
                q_id = cur.fetchone()["id"]
                conn.commit()
                return q_id
        finally:
            conn.close()
'''

with open(path_feeder, "w", encoding="utf-8") as f:
    f.write(code_feeder)

print("SUCCESSFULLY DEPLOYED FACTUAL FEEDER TO S13!")
