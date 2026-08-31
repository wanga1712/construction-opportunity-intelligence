"""CRM V3 Dataset Builder Daemon

Responsibilities:
- Build daily dataset manifest from valid producer_version='v2_corrected' artifacts
- Computes TRAIN / VALIDATION / HOLDOUT split counts
- Computes AUTO_FACT vs HUMAN label counts
- Tracks excluded invalid count from 7cdc
- Producer version: v2_corrected
"""

import os
import sys
import json
import time
import psycopg2
import psycopg2.extras

PRODUCER_VERSION = "v2_corrected"

def get_crm_db():
    user = os.environ.get("CRM_DB_USER", "crm_app")
    password = os.environ.get("CRM_DB_PASSWORD")
    if not password:
        raise RuntimeError("Missing required environment variable CRM_DB_PASSWORD")
    host = os.environ.get("CRM_DB_HOST", "127.0.0.1")
    port = os.environ.get("CRM_DB_PORT", "5432")
    return psycopg2.connect(dbname="crm", user=user, password=password, host=host, port=port)

def build_daily_manifest() -> dict:
    crm_conn = get_crm_db()
    try:
        with crm_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Valid split counts
            cur.execute("""
                SELECT dataset_split, COUNT(1) as cnt
                FROM crm_v3_learning_examples
                WHERE producer_version = %s AND (temporal_class = 'ONLINE_CLEAN' OR label_source = 'HUMAN')
                GROUP BY dataset_split
            """, (PRODUCER_VERSION,))
            splits = {r["dataset_split"]: r["cnt"] for r in cur.fetchall()}

            # Label source counts
            cur.execute("""
                SELECT label_source, COUNT(1) as cnt
                FROM crm_v3_learning_examples
                WHERE producer_version = %s AND (temporal_class = 'ONLINE_CLEAN' OR label_source = 'HUMAN')
                GROUP BY label_source
            """, (PRODUCER_VERSION,))
            labels = {r["label_source"]: r["cnt"] for r in cur.fetchall()}

            # Excluded invalid 7cdc count
            cur.execute("""
                SELECT COUNT(1) as cnt
                FROM crm_v3_learning_examples
                WHERE producer_version = 'v1_invalid_7cdc'
            """)
            invalid_cnt = cur.fetchone()["cnt"]

            manifest = {
                "dataset_version": "v2_daily_corrected",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "train_count": splits.get("TRAIN", 0),
                "validation_count": splits.get("VALIDATION", 0),
                "holdout_count": splits.get("HOLDOUT", 0),
                "auto_fact_count": labels.get("AUTO_FACT", 0),
                "human_count": labels.get("HUMAN", 0),
                "invalid_excluded_count": invalid_cnt
            }

            print(json.dumps(manifest, indent=2))
            return manifest
    finally:
        crm_conn.close()

if __name__ == "__main__":
    build_daily_manifest()
