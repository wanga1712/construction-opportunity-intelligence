#!/usr/bin/env python3
"""Read-only production audit for AI/expert review queue authority."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

ROOT = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit"))
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(1, os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89"))
load_dotenv(ROOT / ".env", override=True)

from src.services.commercial_routing_v3.okpd_priors import load_okpd_priors_from_db  # noqa: E402
from src.services.commercial_routing_v3.routing_eligibility import evaluate_routing_eligibility  # noqa: E402
from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402


class ReadOnlyDb:
    def __init__(self):
        self.conn = psycopg2.connect(**require_crm_db_connect_kwargs())
        self.conn.set_session(readonly=True, autocommit=True)

    def execute_query(self, sql, params=None):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(row) for row in (cur.fetchall() or [])]

    def execute_scalar(self, sql, params=None):
        result = self.execute_query(sql, params)
        return next(iter(result[0].values())) if result else None


def main() -> None:
    db = ReadOnlyDb()
    rows = db.execute_query(
        """SELECT id, source_table, source_id, auction_name, okpd_code, okpd_name,
                  initial_price, delivery_region, customer, crm_stage, award_status,
                  end_date, start_date, award_date, manual_override,
                  ai_assessment_status, ai_assessment_version,
                  ai_assessment_fingerprint, reassessment_requested,
                  coalesce(ai_routing_attempt_count,0) ai_routing_attempt_count,
                  ai_routing_error_class, ai_assessed_at
             FROM crm_procurements WHERE crm_stage='torgi'"""
    ) or []
    priors = load_okpd_priors_from_db(db)
    expected = []
    not_expected_reasons: dict[str, int] = {}
    for raw in rows:
        item = dict(raw)
        item["title"] = item.get("auction_name")
        item["price"] = float(item.get("initial_price") or 0)
        item["region"] = item.get("delivery_region")
        st = item.get("source_table") or ""
        item["law_type"] = "615_PP" if "615" in st else ("223_FZ" if "223" in st else "44_FZ")
        decision = evaluate_routing_eligibility(item, priors=priors, force_reassess=False)
        if decision.selectable:
            expected.append(item)
        else:
            not_expected_reasons[decision.reason] = not_expected_reasons.get(decision.reason, 0) + 1
    ids = [x["id"] for x in expected]
    ai = db.execute_query(
        """SELECT status, count(*) n FROM procurement_ai_assessments
             WHERE is_current AND procurement_id=ANY(%s) GROUP BY status ORDER BY status""",
        (ids,),
    ) if ids else []
    queue = {}
    for item in expected:
        status = str(item.get("ai_assessment_status") or "UNASSESSED").upper()
        queue[status] = queue.get(status, 0) + 1
    tables = db.execute_query(
        """SELECT table_name FROM information_schema.tables
             WHERE table_schema='public' AND (table_name ILIKE '%%ai%%queue%%' OR table_name ILIKE '%%inference%%queue%%')
             ORDER BY table_name"""
    ) or []
    versions = db.execute_query(
        """SELECT model_version, prompt_version, run_kind, run_status, count(*) n
             FROM crm_v3_model_inference_runs GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT 20"""
    ) or []
    expert = db.execute_query(
        """SELECT count(*) n FROM crm_v3_expert_annotations
             WHERE is_current AND procurement_id=ANY(%s)""",
        (ids,),
    ) if ids else [{"n": 0}]
    out = {
        "torgi_rows": len(rows), "model_expected": len(expected),
        "model_not_expected": len(rows)-len(expected),
        "not_expected_reasons": not_expected_reasons,
        "crm_ai_statuses": queue, "current_assessment_statuses": ai,
        "dedicated_ai_queue_tables": tables,
        "inference_run_versions": versions,
        "current_expert_annotations": expert[0]["n"] if expert else 0,
    }
    print(json.dumps(out, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
