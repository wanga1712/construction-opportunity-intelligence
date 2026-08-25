"""Read-only production audit for expert review counters and TORGI deadlines."""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from src.bootstrap import setup_source_path

setup_source_path()

from config.settings import Settings  # noqa: E402
from modules.crm.crm_database import CrmDatabaseManager  # noqa: E402

WORKSET = """
SELECT cp.id,cp.end_date,cp.initial_price
FROM crm_procurements cp
WHERE cp.crm_stage='torgi'
  AND cp.award_status='submission_open'
  AND cp.end_date >= CURRENT_DATE + INTERVAL '2 days'
"""
NOT_INTERESTING = """
(
  ea.payload->>'expert_commercial_verdict'='NO_COMMERCIAL_ENTRY'
  OR ea.payload->>'expert_scope_verdict'='OUT_OF_PROFILE'
  OR ea.payload->>'expert_medal'='NCE'
  OR COALESCE(ea.payload->'error_reasons','[]'::jsonb) ? 'OUT_OF_PROFILE'
)
"""


def main() -> None:
    db = CrmDatabaseManager(Settings().crm_database)
    db.connect()
    counts = db.execute_query(f"""
        WITH workset AS ({WORKSET})
        SELECT
          count(*)::int AS current_workset_total,
          count(ea.id)::int AS current_annotation_rows,
          count(DISTINCT ea.procurement_id)::int AS current_reviewed_procurements,
          count(DISTINCT ea.procurement_id) FILTER (WHERE {NOT_INTERESTING})::int
            AS current_not_interesting_procurements,
          count(DISTINCT ea.procurement_id) FILTER (WHERE ea.id IS NOT NULL AND NOT {NOT_INTERESTING})::int
            AS current_profiled_procurements
        FROM workset w
        LEFT JOIN crm_v3_expert_annotations ea
          ON ea.procurement_id=w.id AND ea.is_current=TRUE
    """)[0]
    global_counts = db.execute_query("""
        SELECT count(*)::int AS all_annotation_rows,
               count(*) FILTER (WHERE is_current)::int AS current_rows,
               count(DISTINCT procurement_id)::int AS distinct_procurements,
               count(*) FILTER (WHERE NOT is_current)::int AS historical_versions
        FROM crm_v3_expert_annotations
    """)[0]
    recent = db.execute_query("""
        SELECT id AS annotation_id, procurement_id, annotation_version, is_current,
               created_at, created_by,
               payload->>'expert_scope_verdict' AS expert_scope_verdict,
               payload->>'expert_commercial_verdict' AS expert_commercial_verdict,
               payload->>'expert_medal' AS expert_medal,
               payload->>'expert_out_of_profile_reason' AS rejection_reason
        FROM crm_v3_expert_annotations
        ORDER BY created_at DESC,id DESC LIMIT 50
    """) or []
    outside = db.execute_query(f"""
        WITH workset AS ({WORKSET})
        SELECT count(DISTINCT ea.procurement_id)::int AS current_annotations_outside_workset
        FROM crm_v3_expert_annotations ea
        LEFT JOIN workset w ON w.id=ea.procurement_id
        WHERE ea.is_current=TRUE AND w.id IS NULL
    """)[0]
    far = db.execute_query(f"""
        WITH workset AS ({WORKSET})
        SELECT id,end_date,initial_price FROM workset
        ORDER BY end_date DESC NULLS LAST,initial_price DESC NULLS LAST,id DESC LIMIT 25
    """) or []
    near = db.execute_query(f"""
        WITH workset AS ({WORKSET})
        SELECT id,end_date,initial_price FROM workset
        ORDER BY end_date ASC NULLS LAST,initial_price DESC NULLS LAST,id DESC LIMIT 25
    """) or []
    print(json.dumps({
        "counts": counts,
        "global_counts": global_counts,
        "outside": outside,
        "recent_annotations": recent,
        "farthest_first_page": far,
        "nearest_first_page": near,
    }, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
