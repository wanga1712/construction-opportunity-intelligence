#!/usr/bin/env python3
"""Add same-cohort document PROCESSING count to the S13 kiosk payload."""
from __future__ import annotations

import argparse
from pathlib import Path


ANCHOR = '''            out["today"]["in_progress_from_received"]=i(cohort[0][5])

        doc_sql=f"""
'''

REPLACEMENT = '''            out["today"]["in_progress_from_received"]=i(cohort[0][5])
        cohort_state_sql=f"""
        SELECT p.id,
               EXISTS (
                 SELECT 1 FROM crm_procurement_scope_authority a
                  WHERE a.procurement_id=p.id
                    AND a.admission_state='ELIGIBLE'
                    AND a.admission_policy_version='{ADMISSION_POLICY}'
               ),
               coalesce(p.ai_assessed_at>=current_date,false)
          FROM crm_procurements p
         WHERE p.crm_created_at>=current_date
        """
        unprocessed_ids=[
            i(r[0]) for r in rows(pq("crm",cohort_state_sql,30))
            if len(r)>=3 and r[1]=="t" and r[2]!="t" and i(r[0]) is not None
        ]
        if unprocessed_ids:
            pid_array="ARRAY["+",".join(str(pid) for pid in unprocessed_ids)+"]::bigint[]"
            queue_processing_sql=f"""
            SELECT 'PROCESSING',count(*)
              FROM document_processing_queue
             WHERE pipeline_generation='S13_V4_EXHAUSTIVE_CONTEXT'
               AND status='PROCESSING'
               AND procurement_id=ANY({pid_array})
            """
            qp=rows(pq("document_intelligence",queue_processing_sql,30))
            if qp:
                out["today"]["in_progress_from_received"]=(
                    i(out["today"].get("in_progress_from_received")) or 0
                )+(i(qp[0][1]) or 0)

        doc_sql=f"""
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    text = Path(args.source).read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    count = text.count(ANCHOR)
    if count != 1:
        raise RuntimeError(f"expected one anchor, found {count}")
    text = text.replace(ANCHOR, REPLACEMENT, 1)
    Path(args.output).write_text(text, encoding="utf-8", newline="\n")
    print(f"patched={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
