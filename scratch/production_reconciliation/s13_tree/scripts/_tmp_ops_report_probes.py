#!/usr/bin/env python3
"""READ-ONLY supplements for ops report: WAITING processed IDs, sync events, safety counters."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")
from src.services.commercial_routing_v3.source_lifecycle import (
    normalize_source_lifecycle_event,
)
from src.services.db_bootstrap import connect_databases

OUT = Path("/var/lib/crm-v3-canary/production_runtime_report_20260816")
MSK = timezone(timedelta(hours=3))
START = datetime(2026, 8, 14, 23, 2, 0, tzinfo=MSK)

_r, tender_db, crm_db, _w = connect_databases()

rows = (
    crm_db.execute_query(
        """
        SELECT id, ai_assessment_status, ai_routing_error_class, ai_assessed_at,
               source_table, crm_stage, award_status, end_date, commercial_window_state,
               ai_routing_attempt_count
        FROM crm_procurements
        WHERE ai_assessed_at >= %s
        """,
        (START,),
    )
    or []
)

waiting = []
for r in rows:
    lc = normalize_source_lifecycle_event(
        source_table=str(r.get("source_table") or ""),
        crm_stage=str(r.get("crm_stage") or ""),
        award_status=str(r.get("award_status") or ""),
        end_date=r.get("end_date"),
    ).value
    if lc == "WAITING_SOURCE_OUTCOME":
        waiting.append(
            {
                "id": r["id"],
                "status": r.get("ai_assessment_status"),
                "error_class": r.get("ai_routing_error_class"),
                "source_table": r.get("source_table"),
                "crm_stage": r.get("crm_stage"),
                "award_status": r.get("award_status"),
                "end_date": str(r.get("end_date")),
                "commercial_window_state": r.get("commercial_window_state"),
                "ai_assessed_at": str(r.get("ai_assessed_at")),
                "attempts": r.get("ai_routing_attempt_count"),
            }
        )

# Sync events in window
sync = {"err": None, "rows": [], "counts": {}}
try:
    sync_rows = (
        crm_db.execute_query(
            """
            SELECT *
            FROM crm_sync_events
            WHERE coalesce(created_at, finished_at, started_at) >= %s
            ORDER BY 1
            LIMIT 5000
            """,
            (START,),
        )
        or []
    )
except Exception as e:
    try:
        cols = (
            crm_db.execute_query(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name='crm_sync_events' ORDER BY ordinal_position
                """
            )
            or []
        )
        sync["columns"] = [c["column_name"] for c in cols]
        sync_rows = crm_db.execute_query("SELECT * FROM crm_sync_events ORDER BY 1 DESC LIMIT 50") or []
        sync["sample"] = [
            {k: (str(v) if not isinstance(v, (int, float, bool, type(None))) else v) for k, v in r.items()}
            for r in sync_rows[:5]
        ]
        sync["err"] = str(e)
    except Exception as e2:
        sync["err"] = f"{e} | {e2}"
        sync_rows = []

# Jobs table
jobs = {"err": None}
try:
    jcols = (
        crm_db.execute_query(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name='crm_sync_jobs' ORDER BY ordinal_position
            """
        )
        or []
    )
    jobs["columns"] = [c["column_name"] for c in jcols]
    jrows = (
        crm_db.execute_query(
            f"""
            SELECT * FROM crm_sync_jobs
            WHERE coalesce({','.join(['created_at','started_at','finished_at','updated_at'][:1])}) IS NOT NULL
            ORDER BY 1 DESC LIMIT 20
            """
        )
        or []
    )
except Exception as e:
    jobs["err"] = str(e)
    jrows = []

# Prefer journal-derived sync already in report; also pull insert/update from sync events if schema known
out = {
    "WAITING_PROCESSED_COUNT": len(waiting),
    "WAITING_PROCESSED_BY_STATUS": dict(Counter(w["status"] for w in waiting)),
    "WAITING_PROCESSED_IDS": waiting[:100],
    "WAITING_NOTE": (
        "These are rows with ai_assessed_at in window whose CURRENT lifecycle classifies as WAITING. "
        "May include: routed while OPEN then became WAITING; or incorrectly routed while WAITING; "
        "or lifecycle classifier edge cases. Investigate IDs before treating as safety violation."
    ),
    "sync_probe": sync,
    "jobs_probe": {**jobs, "sample_n": len(jrows) if "jrows" in dir() else 0},
}

# Medal history sample for GOLD->BRONZE / SILVER->BRONZE with reasons
medal = (
    crm_db.execute_query(
        """
        SELECT previous_effective_medal, new_effective_medal, reason, count(*) AS n
        FROM crm_category_opportunity_medal_history
        WHERE evaluated_at >= %s
          AND previous_effective_medal IS DISTINCT FROM new_effective_medal
        GROUP BY 1,2,3
        ORDER BY n DESC
        LIMIT 40
        """,
        (START,),
    )
    or []
)
out["medal_transition_reasons"] = [
    {
        "from": r["previous_effective_medal"],
        "to": r["new_effective_medal"],
        "reason": r["reason"],
        "n": r["n"],
    }
    for r in medal
]

# Open→awarded: look for initial_medal_provenance / current_effective_reason mentioning awarded
o2a = (
    crm_db.execute_query(
        """
        SELECT p.id, p.source_table, p.source_awarded_table, o.candidate_initial_medal,
               o.current_effective_medal, o.current_effective_reason, o.initial_medal_provenance,
               o.opportunity_track, o.procurement_form, o.created_at, o.updated_at
        FROM crm_procurements p
        JOIN crm_procurement_category_opportunities o
          ON o.procurement_id=p.id AND o.status='CURRENT'
        WHERE p.ai_assessed_at >= %s
          AND (
            p.source_awarded_table IS NOT NULL
            OR o.current_effective_reason ILIKE '%%award%%'
            OR o.initial_medal_provenance ILIKE '%%open%%'
            OR o.initial_medal_provenance ILIKE '%%lineage%%'
          )
        LIMIT 200
        """,
        (START,),
    )
    or []
)
out["OPEN_TO_AWARDED_CANDIDATES"] = len(o2a)
out["OPEN_TO_AWARDED_SAMPLE"] = [
    {
        "id": r["id"],
        "source_table": r["source_table"],
        "source_awarded_table": r["source_awarded_table"],
        "initial": r["candidate_initial_medal"],
        "effective": r["current_effective_medal"],
        "reason": r["current_effective_reason"],
        "provenance": r["initial_medal_provenance"],
        "form": r["procurement_form"],
        "track": r["opportunity_track"],
    }
    for r in o2a[:30]
]

(OUT / "waiting_and_lineage_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
print(json.dumps({"WAITING_PROCESSED_COUNT": len(waiting), "medal_reason_groups": len(medal), "o2a": len(o2a)}, indent=2))
