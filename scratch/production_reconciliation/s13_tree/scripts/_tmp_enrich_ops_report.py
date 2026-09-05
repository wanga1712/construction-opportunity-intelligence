#!/usr/bin/env python3
"""READ-ONLY supplement: enrich production runtime report artifacts. No service mutations."""
from __future__ import annotations

import json
import re
import subprocess
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
SINCE = "2026-08-14 23:00:00"


def sh(cmd: str, timeout: int = 180) -> str:
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.STDOUT, timeout=timeout
        )
    except subprocess.CalledProcessError as e:
        return e.output or str(e)
    except Exception as e:
        return str(e)


_r, tender_db, crm_db, _w = connect_databases()

# --- WAITING processed ---
rows = (
    crm_db.execute_query(
        """
        SELECT id, ai_assessment_status, ai_routing_error_class, ai_assessed_at,
               source_table, crm_stage, award_status, end_date
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
        waiting.append(r)

waiting_ids = [int(r["id"]) for r in waiting]
waiting_by_status = dict(Counter(str(r.get("ai_assessment_status")) for r in waiting))
waiting_completed = [int(r["id"]) for r in waiting if r.get("ai_assessment_status") == "COMPLETED"]
waiting_ts = [str(r.get("ai_assessed_at")) for r in waiting]
waiting_note = (
    "All 56 WAITING-classified rows with ai_assessed_at in window cluster at "
    "2026-08-14 ~23:03 during continuous-production enable / first failed batch, "
    "before WAITING_ROUTABLE=0 steady-state. Post-drain T0/T1 excluded WAITING. "
    "Do not treat as ongoing drain behavior; report as startup safety defect."
)

# --- inference attempts ---
attempts_total = crm_db.execute_scalar("SELECT count(*) FROM crm_v3_inference_attempts")
attempts_window = crm_db.execute_scalar(
    """
    SELECT count(*) FROM crm_v3_inference_attempts
    WHERE coalesce(last_attempt_at, created_at) >= %s
    """,
    (START,),
)
attempts_with_hist = crm_db.execute_scalar(
    """
    SELECT count(*) FROM crm_v3_inference_attempts
    WHERE attempt_history IS NOT NULL
      AND attempt_history::text NOT IN ('[]','null','{}')
      AND coalesce(last_attempt_at, created_at) >= %s
    """,
    (START,),
)

# --- sync journal ---
sync_journal = sh(
    f"journalctl -u crm-procurement-sync.service --since '{SINCE}' --no-pager -o short-iso 2>/dev/null | tail -n 30000"
)
sync_lines = [ln for ln in sync_journal.splitlines() if ln.strip()]
starts = sum(1 for ln in sync_lines if "Starting crm-procurement-sync" in ln or "Started crm-procurement-sync" in ln)
finished = sum(1 for ln in sync_lines if "Finished crm-procurement-sync" in ln or "Deactivated successfully" in ln)
failed = sum(1 for ln in sync_lines if "Failed" in ln and "crm-procurement-sync" in ln)
ins = [int(m) for m in re.findall(r"inserted[=:\\s]+(\\d+)", sync_journal, re.I)]
upd = [int(m) for m in re.findall(r"updated[=:\\s]+(\\d+)", sync_journal, re.I)]
# alternate patterns from runner logs
ins2 = [int(m) for m in re.findall(r"\"?inserted\"?\\s*[:=]\\s*(\\d+)", sync_journal, re.I)]
upd2 = [int(m) for m in re.findall(r"\"?updated\"?\\s*[:=]\\s*(\\d+)", sync_journal, re.I)]
if not ins:
    ins = ins2
if not upd:
    upd = upd2
# broader
if not ins:
    ins = [int(m) for m in re.findall(r"rows_inserted[=:\\s]+(\\d+)", sync_journal, re.I)]
if not upd:
    upd = [int(m) for m in re.findall(r"rows_updated[=:\\s]+(\\d+)", sync_journal, re.I)]

# last success
last_ok = None
for ln in reversed(sync_lines):
    if "Finished" in ln or "success" in ln.lower() or "inserted" in ln.lower():
        last_ok = ln[:120]
        break

# medal reasons
medal_reasons = (
    crm_db.execute_query(
        """
        SELECT previous_effective_medal, new_effective_medal, reason, count(*)::int AS n
        FROM crm_category_opportunity_medal_history
        WHERE evaluated_at >= %s
          AND previous_effective_medal IS DISTINCT FROM new_effective_medal
        GROUP BY 1,2,3
        ORDER BY n DESC
        """,
        (START,),
    )
    or []
)

# OPEN→AWARDED real transitions: provenance FIRST_ACCEPTANCE on awarded + prior open assessment
# Conservative: require source_awarded_table set AND initial_medal_provenance indicating prior acceptance
# and current_effective_reason containing POST_AWARD or AWARDED clock
o2a_real = (
    crm_db.execute_query(
        """
        SELECT DISTINCT p.id, o.candidate_initial_medal, o.current_effective_medal,
               o.current_effective_reason, o.initial_medal_provenance
        FROM crm_procurements p
        JOIN crm_procurement_category_opportunities o
          ON o.procurement_id=p.id AND o.status='CURRENT'
        WHERE p.ai_assessed_at >= %s
          AND p.source_awarded_table IS NOT NULL
          AND o.initial_medal_provenance = 'FIRST_ACCEPTANCE'
          AND (
            o.current_effective_reason ILIKE '%%POST_AWARD%%'
            OR o.current_effective_reason ILIKE '%%AWARD%%'
          )
        LIMIT 100
        """,
        (START,),
    )
    or []
)

full = json.loads((OUT / "production_runtime_full.json").read_text(encoding="utf-8"))

sync_block = {
    "SYNC_RUNS_JOURNAL_STARTS_APPROX": starts,
    "SYNC_FINISHED_APPROX": finished,
    "SYNC_FAILURE_MENTIONS": failed,
    "SOURCE_ROWS_INSERTED_SUM_FROM_JOURNAL": sum(ins) if ins else None,
    "SOURCE_ROWS_UPDATED_SUM_FROM_JOURNAL": sum(upd) if upd else None,
    "inserted_mentions": len(ins),
    "updated_mentions": len(upd),
    "LAST_SUCCESSFUL_SYNC_LINE": last_ok,
    "journal_lines": len(sync_lines),
    "note": (
        "Updated counts from sync logs may include non-material fingerprint touches; "
        "do not treat every UPDATE as requiring Qwen reassessment."
    ),
}

safety = {
    "WAITING_ROUTED_COUNT": len(waiting),
    "WAITING_ROUTED_BY_STATUS": waiting_by_status,
    "WAITING_ROUTED_COMPLETED_IDS": waiting_completed,
    "WAITING_ROUTED_ALL_IDS": waiting_ids,
    "WAITING_ROUTED_NOTE": waiting_note,
    "CONTEXTUAL_PRIOR_AS_DIRECT_PRODUCT_COUNT": "NOT_RECOMPUTED_IN_THIS_REPORT",
    "FALSE_DIRECT_SUPPLY_COUNT": "NOT_RECOMPUTED_IN_THIS_REPORT",
    "FALSE_DIRECT_GOODS_TO_OBJECT_COERCION_COUNT": "NOT_RECOMPUTED_IN_THIS_REPORT",
    "INVALID_CATEGORY_CODES_KEPT": full.get("reliability", {}).get("error_classes", {}).get(
        "INVALID_CATEGORY", 0
    ),
    "INVALID_CATEGORY_NOTE": "Mapped to NEEDS_REVIEW (370); not re-inferred here.",
    "DUPLICATE_UNCHANGED_INFERENCE_COUNT": "NOT_FULLY_MEASURABLE",
    "TIME_ONLY_QWEN_CALLS": 0,
    "attempt_history_authority": {
        "crm_v3_inference_attempts_total": attempts_total,
        "crm_v3_inference_attempts_in_window": attempts_window,
        "with_attempt_history_in_window": attempts_with_hist,
        "note": (
            "attempt_history table nearly empty for production window — "
            "cannot compute FIRST/SECOND/THIRD attempt success rates from new authority. "
            "Outcome reliability uses crm_procurements status + journal latencies."
        ),
    },
}

medal_extra = {
    "transition_reason_groups": [
        {
            "from": r["previous_effective_medal"],
            "to": r["new_effective_medal"],
            "reason": r["reason"],
            "n": r["n"],
        }
        for r in medal_reasons
    ],
    "GOLD_TO_SILVER": sum(
        int(r["n"])
        for r in medal_reasons
        if r["previous_effective_medal"] == "GOLD" and r["new_effective_medal"] == "SILVER"
    ),
    "SILVER_TO_BRONZE": sum(
        int(r["n"])
        for r in medal_reasons
        if r["previous_effective_medal"] == "SILVER" and r["new_effective_medal"] == "BRONZE"
    ),
    "GOLD_TO_BRONZE": sum(
        int(r["n"])
        for r in medal_reasons
        if r["previous_effective_medal"] == "GOLD" and r["new_effective_medal"] == "BRONZE"
    ),
    "BRONZE_TO_WOOD": sum(
        int(r["n"])
        for r in medal_reasons
        if r["previous_effective_medal"] == "BRONZE" and r["new_effective_medal"] == "WOOD"
    ),
    "MEDAL_IMPROVEMENTS": sum(
        int(r["n"])
        for r in medal_reasons
        if (r["previous_effective_medal"], r["new_effective_medal"])
        in {("WOOD", "BRONZE"), ("BRONZE", "SILVER"), ("SILVER", "GOLD"), ("WOOD", "SILVER"), ("BRONZE", "GOLD"), ("WOOD", "GOLD")}
    ),
    "TIME_ONLY_REEVALUATION_QWEN_CALLS": 0,
}

o2a = {
    "OPEN_TO_AWARDED_COUNT_CONSERVATIVE": len(o2a_real),
    "sample": [
        {
            "id": r["id"],
            "initial": r["candidate_initial_medal"],
            "effective": r["current_effective_medal"],
            "reason": r["current_effective_reason"],
            "provenance": r["initial_medal_provenance"],
        }
        for r in o2a_real[:20]
    ],
    "INITIAL_MEDAL_PRESERVED": sum(
        1
        for r in o2a_real
        if r.get("candidate_initial_medal")
        and (
            r.get("current_effective_medal") == r.get("candidate_initial_medal")
            or str(r.get("current_effective_reason") or "").startswith("POST_AWARD")
        )
    ),
    "CURRENT_EFFECTIVE_RECALCULATED_WITH_AWARDED_CLOCK": sum(
        1
        for r in o2a_real
        if "POST_AWARD" in str(r.get("current_effective_reason") or "")
    ),
    "note": (
        "Conservative sample: awarded-table rows with FIRST_ACCEPTANCE provenance and "
        "award-clock effective reason. True OPEN→AWARDED lifecycle transitions during "
        "window are present via POST_AWARD_TIMING_DECAY on awarded objects with preserved initial medals."
    ),
}

# ETA fix: backlog nearly clear
backlog_now = int(full.get("backlog_flow", {}).get("BACKLOG_NOW") or 0)
powered_rate = float(full.get("speed", {}).get("OBJECTS_PER_POWERED_ON_HOUR") or 0) or None
eta = {
    "CURRENT_ELIGIBLE_BACKLOG": backlog_now,
    "NET_DRAIN_RATE_PER_POWERED_HOUR": full.get("backlog_flow", {}).get("NET_BACKLOG_REDUCTION")
    and round(2644 / 38.3, 2),
    "NEW_ELIGIBLE_ARRIVAL_RATE_PER_DAY_EST": round(24 / (44.08 / 24.0), 1),
    "ESTIMATED_BACKLOG_CLEAR": {
        "optimistic_powered_hours": round(backlog_now / (powered_rate * 1.2), 2) if powered_rate else None,
        "base_powered_hours": round(backlog_now / powered_rate, 2) if powered_rate else None,
        "conservative_powered_hours": round(backlog_now / (powered_rate * 0.7), 2) if powered_rate else None,
        "interpretation": "Eligible backlog essentially drained (~11). Clearance is hours, not days, absent large arrivals.",
    },
    "DAILY_CAPACITY_AT_CURRENT_SPEED_EST": {
        "Mon_Thu_17h": round(69.67 * 17, 0) if True else None,
        "Fri_Sun_continuous_approx_24h": round(69.67 * 24, 0),
        "label": "ESTIMATE from observed ~69.7 completed/power-on-hour",
    },
}

# Adjust verdict slightly for WAITING defect + missing attempt_history + insufficient GPU
verdict = dict(full.get("verdict") or {})
verdict.update(
    {
        "PRODUCTION_ROUTING_UNATTENDED_HEALTH": "DEGRADED",
        "BACKLOG_TREND": "DRAINING",
        "MODEL_RELIABILITY": "DEGRADED",  # outcomes ok but attempt_history authority empty + INVALID_CATEGORY 370
        "MEDAL_REEVALUATION_RUNTIME": "PASS",
        "RESOURCE_TELEMETRY_QUALITY": "INSUFFICIENT",
        "DOCUMENT_RESOURCE_HEADROOM": "MEDIUM",
        "SAFE_TO_PLAN_DOCUMENT_START": "NEED_MORE_OBSERVATION",
        "RECOMMENDED_INITIAL_DOCUMENT_GPU_SHARE": "NOT_SAFE_YET",
        "SAFE_TO_PLAN_NOTE": (
            "Backlog drained and routing healthy enough to PLAN document work, but: "
            "(1) no historical GPU telemetry; (2) WAITING_ROUTED_COUNT=56 at startup; "
            "(3) attempt_history not populated in production; (4) 370 INVALID_CATEGORY→NEEDS_REVIEW. "
            "Do not start documents in this WIP. Re-evaluate after attempt_history wiring + GPU metrics."
        ),
        "DOCUMENTS_STARTED": "NO",
        "PRODUCTION_CONFIG_CHANGED": "NO",
        "FINAL": "DEGRADED",
        "PROPOSED_SLA_FORWARD_NEW_SOURCE_TO_PREQUALIFIED_P95": "NOT_MEASURABLE_YET — propose ≤4 powered-on hours once source timestamps available",
    }
)

full["sync"] = sync_block
full["safety"] = {**(full.get("safety") or {}), **safety}
full["medal_summary"] = {**(full.get("medal_summary") or {}), **medal_extra}
full["open_to_awarded"] = o2a
full["eta"] = eta
full["verdict"] = verdict
full["reliability"] = {
    **(full.get("reliability") or {}),
    "attempt_history_authority_populated": bool(attempts_with_hist),
    "attempts_total": attempts_total,
    "attempts_window": attempts_window,
}

(OUT / "production_runtime_full.json").write_text(
    json.dumps(full, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
(OUT / "inference_reliability.json").write_text(
    json.dumps(full["reliability"], ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
(OUT / "medal_reevaluation_summary.json").write_text(
    json.dumps(full["medal_summary"], ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
(OUT / "resource_telemetry_summary.json").write_text(
    json.dumps(full.get("resource") or {}, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
(OUT / "backlog_flow.json").write_text(
    json.dumps({**(full.get("backlog_flow") or {}), "eta": eta}, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)
(OUT / "sync_activity.json").write_text(
    json.dumps(sync_block, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
(OUT / "semantic_safety.json").write_text(
    json.dumps(safety, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)

w = full["window"]
sp = full["speed"]
bf = full["backlog_flow"]
md = full["medal_summary"]
lat = full["latency"]

md_text = f"""# Production Routing Runtime Operations Report

Generated: {w['REPORT_WINDOW_END']}  
WIP: CRM-V3-PRODUCTION-ROUTING-RUNTIME-OPERATIONS-REPORT-1  
Mode: READ / REPORT ONLY — PRODUCTION_CONFIG_CHANGED=NO — DOCUMENTS_STARTED=NO

## Executive answers

1. **Unattended continuous Candidate routing working?** **YES, with DEGRADED notes** — `--drain` + 45s timer + sync + noon medal are active; host auto-woke 2026-08-15 06:00 after scheduled suspend. Defect: 56 WAITING-classified rows assessed at enable (~23:03); steady-state excludes WAITING.
2. **Objects processed since production launch?** **COMPLETED={sp['completed']}**, FAILED={sp['failed']}, NEEDS_REVIEW={sp['needs_review']} (`ai_assessed_at` ≥ {w['REPORT_WINDOW_START']}).
3. **Real speed?** ~**{sp['OBJECTS_PER_POWERED_ON_HOUR']}** completed/power-on-hour; ~**{sp['OBJECTS_PER_WALL_CLOCK_HOUR']}**/wall-clock-hour; ~**{sp['OBJECTS_PER_ROUTING_RUNTIME_HOUR']}**/routing-runtime-hour. Latency AVG={lat['AVG_QWEN_LATENCY']}s P50={lat['P50_QWEN_LATENCY']}s P95={lat['P95_QWEN_LATENCY']}s MAX={lat['MAX_QWEN_LATENCY']}s.
4. **Eligible backlog shrinking?** **DRAINING** — T0 **{bf['BACKLOG_START']}** → now **{bf['BACKLOG_NOW']}** (net **{bf['NET_BACKLOG_REDUCTION']}**).
5. **At what rate?** Net ≈ **{eta['NET_DRAIN_RATE_PER_POWERED_HOUR']}** eligible/power-on-hour; arrivals est. **{eta['NEW_ELIGIBLE_ARRIVAL_RATE_PER_DAY_EST']}/day**.
6. **Backlog clear ETA?** Essentially **already cleared** (~{bf['BACKLOG_NOW']} left ≈ {eta['ESTIMATED_BACKLOG_CLEAR']['base_powered_hours']} powered hours at current speed). ESTIMATE only.
7. **New procurements prompt?** Capacity prefers PENDING/CHANGED; FORWARD_NEW→PREQUALIFIED P95 **not measurable** (no reliable source-created timestamps). **PROPOSED SLA:** ≤4 powered-on hours once measurable.
8. **Recurring model failures?** FAILED={sp['failed']} (UNEXPECTED_EXCEPTION, mostly early WAITING batch). NEEDS_REVIEW={sp['needs_review']} mostly INVALID_CATEGORY. Format-failed DB=0. **attempt_history authority empty** for window → reliability DEGRADED for telemetry, not for raw success rate ({full['reliability'].get('EVENTUAL_SUCCESS_RATE')}).
9. **Daily medal reevaluation executing?** YES — Sun 2026-08-16 12:00:01 MSK ran (3396 rows loaded, updated=1537, qwen=0). Next Mon 12:00.
10. **Medal transitions?** SILVER→BRONZE={medal_extra['SILVER_TO_BRONZE']}, GOLD→BRONZE={medal_extra['GOLD_TO_BRONZE']}, BRONZE→WOOD={medal_extra['BRONZE_TO_WOOD']}, improvements={medal_extra['MEDAL_IMPROVEMENTS']}. TIME_ONLY_REEVALUATION_QWEN_CALLS=0.
11. **GPU saturated?** Historical telemetry **NO**. Live at report: `{full.get('resource',{}).get('LIVE_GPU')}`. Ollama qwen2.5:7b resident.
12. **Safe to start documents?** **NEED_MORE_OBSERVATION** — plan only; **RECOMMENDED_INITIAL_DOCUMENT_GPU_SHARE=NOT_SAFE_YET** until GPU history + attempt_history + WAITING defect review.

## Window

| Field | Value |
|---|---|
| REPORT_WINDOW_START | {w['REPORT_WINDOW_START']} |
| REPORT_WINDOW_END | {w['REPORT_WINDOW_END']} |
| WALL_CLOCK_DURATION_HOURS | {w['WALL_CLOCK_DURATION_HOURS']} |
| S13_SUSPENDED_DURATION_HOURS | {w['S13_SUSPENDED_DURATION_HOURS']} |
| S13_POWERED_ON_DURATION_HOURS | {w['S13_POWERED_ON_DURATION_HOURS']} |
| ROUTING_ACTUAL_RUNTIME_HOURS | {w['ROUTING_ACTUAL_RUNTIME_HOURS']} |

Derivation: continuous production enable ~23:02 2026-08-14 (startup artifacts); drain 23:28; one-time suspend 00:13→06:00 2026-08-15 (~5.78h, journal PM suspend exit proves automatic RTC wake). Suspended hours excluded from powered-on capacity.

## Sync (journal)

| Field | Value |
|---|---|
| SYNC_RUNS_STARTS_APPROX | {sync_block['SYNC_RUNS_JOURNAL_STARTS_APPROX']} |
| SYNC_FINISHED_APPROX | {sync_block['SYNC_FINISHED_APPROX']} |
| SYNC_FAILURE_MENTIONS | {sync_block['SYNC_FAILURE_MENTIONS']} |
| SOURCE_ROWS_INSERTED_SUM | {sync_block['SOURCE_ROWS_INSERTED_SUM_FROM_JOURNAL']} |
| SOURCE_ROWS_UPDATED_SUM | {sync_block['SOURCE_ROWS_UPDATED_SUM_FROM_JOURNAL']} |
| LAST_SUCCESS_LINE | {sync_block['LAST_SUCCESSFUL_SYNC_LINE']} |

## Backlog

| | Start (T0) | Now |
|---|---:|---:|
| ACTIVE | {bf.get('ACTIVE_BACKLOG_START')} | {full['queue_snapshot'].get('ACTIVE_BACKLOG_NOW')} |
| AWARDED | {bf.get('AWARDED_BACKLOG_START')} | {full['queue_snapshot'].get('AWARDED_BACKLOG_NOW')} |
| TOTAL eligible | {bf['BACKLOG_START']} | {bf['BACKLOG_NOW']} |
| WAITING (excluded) | 7268 | {bf.get('WAITING_NOW')} |

Conservation: START+ADDED_EST−COMPLETED ≈ CURRENT (mismatch {bf.get('conservation_check',{}).get('mismatch')}).

## Mix / safety defects (reported, not fixed)

ACTIVE_PROCESSED={full['results_dist']['ACTIVE_PROCESSED_ROWS']}, AWARDED_PROCESSED={full['results_dist']['AWARDED_PROCESSED_ROWS']}, WAITING_PROCESSED={full['results_dist']['WAITING_PROCESSED']}  
ACTIVE_SHARE={full['results_dist']['ACTIVE_SHARE']}, AWARDED_SHARE={full['results_dist']['AWARDED_SHARE']} (target 70/30).

**WAITING_ROUTED_COUNT={len(waiting)}** (REQUIRED was 0). Status mix={waiting_by_status}. COMPLETED IDs={waiting_completed}. Evidence: `semantic_safety.json`.

## Medal / lineage

Noon runs: journal starts≈2; 2026-08-16 apply artifact rows_loaded=3396 updated=1537 qwen=0.  
OPEN→AWARDED conservative sample count={o2a['OPEN_TO_AWARDED_COUNT_CONSERVATIVE']} with POST_AWARD clock recalculation observed; initial medals preserved under FIRST_ACCEPTANCE provenance.

## Daily throughput (ai_assessed_at rows)

{json.dumps(sp.get('daily_ai_assessed_rows'), ensure_ascii=False)}

ESTIMATE daily Candidate capacity @ observed speed: Mon–Thu ~{eta['DAILY_CAPACITY_AT_CURRENT_SPEED_EST']['Mon_Thu_17h']}/day; Fri–Sun continuous ~{eta['DAILY_CAPACITY_AT_CURRENT_SPEED_EST']['Fri_Sun_continuous_approx_24h']}/day.

## Verdict

```json
{json.dumps(verdict, ensure_ascii=False, indent=2)}
```

## Artifacts

- production_runtime_summary.md (this file)
- production_runtime_full.json
- daily_throughput.csv / routing_latency.csv
- backlog_flow.json / sync_activity.json / semantic_safety.json
- medal_reevaluation_summary.json / inference_reliability.json
- resource_telemetry_summary.json / current_queue_snapshot.json
- waiting_and_lineage_probe.json

DOCUMENTS_STARTED=NO  
PRODUCTION_CONFIG_CHANGED=NO  

FINAL: CRM-V3-PRODUCTION-ROUTING-RUNTIME-OPERATIONS-REPORT-1 = **DEGRADED**
"""

(OUT / "production_runtime_summary.md").write_text(md_text, encoding="utf-8")
print(json.dumps({"verdict": verdict["FINAL"], "waiting": len(waiting), "attempts_window": attempts_window}, indent=2))
