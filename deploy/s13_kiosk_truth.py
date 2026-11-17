"""Read-only, same-cohort truth model for the S13 physical kiosk.

This module observes existing CRM/document authorities. It does not write
business state or choose/rewrite any admission, commercial, queue, or parsing
decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable


ADMISSION_POLICY = "BUSINESS_RESEARCH_ADMISSION_V2"
TODAY_COHORT_SQL = f"""
WITH cohort AS (
    SELECT p.id,
           upper(coalesce(p.ai_assessment_status, 'UNASSESSED')) AS ai_state,
           lower(coalesce(p.qualification_state, '')) AS qualification_state,
           upper(coalesce(p.ai_routing_error_class, '')) AS routing_error,
           coalesce(a.admission_state, '') AS admission_state,
           coalesce(a.admission_policy_version, '') AS admission_policy,
           coalesce(a.source_lifecycle, '') AS source_lifecycle,
           coalesce(o.current_count, 0) AS current_opportunities,
           coalesce(o.commercial_states, '') AS commercial_states,
           coalesce(o.research_actions, '') AS research_actions,
           coalesce(prior.has_prior, false) AS has_okpd_prior,
           coalesce(p.ai_assessed_at >= current_date, false) AS assessed_today
      FROM crm_procurements p
      LEFT JOIN crm_procurement_scope_authority a
        ON a.procurement_id = p.id
      LEFT JOIN LATERAL (
          SELECT count(*) AS current_count,
                 string_agg(DISTINCT upper(coalesce(commercial_state, '')), ',')
                     AS commercial_states,
                 string_agg(DISTINCT upper(coalesce(research_action, '')), ',')
                     AS research_actions
            FROM crm_procurement_category_opportunities
           WHERE procurement_id = p.id AND status = 'CURRENT'
      ) o ON true
      LEFT JOIN LATERAL (
          SELECT true AS has_prior
            FROM crm_category_okpd_priors op
           WHERE op.active
             AND regexp_replace(coalesce(p.okpd_code, ''), '[[:space:]]+', '', 'g') <> ''
             AND (
                 (upper(coalesce(op.match_type, 'PREFIX')) = 'EXACT'
                  AND regexp_replace(coalesce(p.okpd_code, ''), '[[:space:]]+', '', 'g')
                      = regexp_replace(op.okpd_pattern, '[[:space:]]+', '', 'g'))
                 OR
                 (upper(coalesce(op.match_type, 'PREFIX')) IN ('PREFIX', 'BRANCH')
                  AND (
                      regexp_replace(coalesce(p.okpd_code, ''), '[[:space:]]+', '', 'g')
                          = regexp_replace(op.okpd_pattern, '[[:space:]]+', '', 'g')
                      OR regexp_replace(coalesce(p.okpd_code, ''), '[[:space:]]+', '', 'g')
                          LIKE regexp_replace(op.okpd_pattern, '[[:space:]]+', '', 'g') || '.%'
                  ))
             )
           LIMIT 1
      ) prior ON true
     WHERE p.crm_created_at >= current_date
       AND p.crm_created_at < current_date + interval '1 day'
)
SELECT id, ai_state, qualification_state, routing_error,
       admission_state, admission_policy, source_lifecycle,
       current_opportunities, commercial_states, research_actions,
       has_okpd_prior,
       (admission_state = 'ELIGIBLE' AND admission_policy = '{ADMISSION_POLICY}'
        AND (has_okpd_prior OR current_opportunities > 0 OR assessed_today)),
       (admission_state = 'ELIGIBLE' AND admission_policy = '{ADMISSION_POLICY}'
        AND NOT (has_okpd_prior OR current_opportunities > 0 OR assessed_today)),
       (admission_state = 'ELIGIBLE' AND admission_policy = '{ADMISSION_POLICY}'
        AND assessed_today),
       (admission_state = 'ELIGIBLE' AND admission_policy = '{ADMISSION_POLICY}'
        AND NOT assessed_today AND ai_state IN ('RUNNING', 'QUEUED'))
  FROM cohort
 ORDER BY id
"""


def _truth(value: object) -> bool:
    return str(value or "").strip().lower() in {"t", "true", "1", "yes"}


def _number(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_pipe_rows(raw: str | Iterable[Iterable[str]]) -> list[list[str]]:
    if not isinstance(raw, str):
        return [list(row) for row in raw]
    return [line.split("|") for line in raw.splitlines() if "|" in line]


def classify_commercial(row: dict) -> tuple[str, str]:
    """Return an observed outcome; missing terminal outcomes fail closed."""
    state = str(row.get("ai_state") or "").upper()
    qualification = str(row.get("qualification_state") or "").lower()
    if _number(row.get("current_opportunities")) > 0:
        return "accepted", "CURRENT opportunity exists"
    if state == "OUT_OF_PROFILE" or qualification in {"out_of_profile", "rejected"}:
        return "rejected", qualification or state
    if state in {"FAILED", "STALE"} or row.get("routing_error"):
        return "error", str(row.get("routing_error") or state)
    if state in {"UNASSESSED", "QUEUED", "RUNNING"}:
        return "processing", state
    if state in {"COMPLETED", "NEEDS_REVIEW"}:
        return "error", "COMPLETED_WITHOUT_CURRENT_OPPORTUNITY_OR_EXPLICIT_REJECTION"
    return "error", "UNKNOWN_AI_OUTCOME"


def _commercial_states(row: dict) -> set[str]:
    return {x.strip().upper() for x in str(row.get("commercial_states") or "").split(",") if x.strip()}


def classify_lifecycle(row: dict) -> tuple[str, str]:
    if _number(row.get("current_opportunities")) <= 0:
        return "not_accepted", "no CURRENT opportunity"
    if row.get("admission_state") != "ELIGIBLE" or row.get("admission_policy") != ADMISSION_POLICY:
        return "error", "CURRENT opportunity without current admission authority"
    lifecycle = str(row.get("source_lifecycle") or "").upper()
    states = _commercial_states(row)
    if lifecycle in {"OPEN", "AWARDED"} and states and states <= {"ACTIVE", "FOLLOW_UP_AWARDED"}:
        return "actionable", lifecycle
    if lifecycle in {"WAITING_SOURCE_OUTCOME", "TERMINAL_NO_RESULT"} or states and states <= {"CLOSED", "ARCHIVED"}:
        return "closed", lifecycle or ",".join(sorted(states))
    return "error", lifecycle or ",".join(sorted(states)) or "missing lifecycle state"


def _sql_ids(ids: list[int]) -> str:
    return ",".join(str(int(pid)) for pid in sorted(set(ids))) or "0"


def document_query(ids: list[int]) -> str:
    id_sql = _sql_ids(ids)
    return f"""
WITH cohort(procurement_id) AS (
    SELECT unnest(ARRAY[{id_sql}]::bigint[])
), queue AS (
    SELECT procurement_id,
           string_agg(DISTINCT upper(status), ',') AS statuses,
           bool_or(upper(status) = 'PROCESSING') AS processing,
           bool_or(upper(status) IN ('PENDING', 'PRE_RESEARCH_WAITING')) AS waiting,
           bool_or(upper(status) = 'NO_LINKS') AS no_links,
           bool_or(upper(status) = 'FAILED') AS failed,
           max(worker_id) FILTER (WHERE upper(status) = 'PROCESSING') AS worker_id
      FROM document_processing_queue
     WHERE procurement_id = ANY(ARRAY[{id_sql}]::bigint[])
     GROUP BY procurement_id
), results AS (
    SELECT procurement_id,
           bool_or(upper(status) = 'FAILED') AS failed,
           bool_or(upper(status) = 'COMPLETED' AND coalesce(rows_extracted, 0) > 0) AS parsed_result
      FROM document_processing_results
     WHERE procurement_id = ANY(ARRAY[{id_sql}]::bigint[])
     GROUP BY procurement_id
), facts AS (
    SELECT procurement_id,
           bool_or(outcome = 'FACTS_FOUND') AS facts_found
      FROM document_extraction_outcomes
     WHERE procurement_id = ANY(ARRAY[{id_sql}]::bigint[])
     GROUP BY procurement_id
), estimate_rows AS (
    SELECT procurement_id, count(*) AS rows
      FROM structured_estimate_rows
     WHERE procurement_id = ANY(ARRAY[{id_sql}]::bigint[])
     GROUP BY procurement_id
)
SELECT c.procurement_id, coalesce(q.statuses, ''),
       coalesce(q.processing, false), coalesce(q.waiting, false),
       coalesce(q.no_links, false), coalesce(q.failed, false),
       coalesce(q.worker_id::text, ''),
       coalesce(r.failed, false), coalesce(r.parsed_result, false),
       coalesce(f.facts_found, false), coalesce(e.rows, 0)
  FROM cohort c
  LEFT JOIN queue q USING (procurement_id)
  LEFT JOIN results r USING (procurement_id)
  LEFT JOIN facts f USING (procurement_id)
  LEFT JOIN estimate_rows e USING (procurement_id)
 ORDER BY c.procurement_id
"""


def normalization_query(ids: list[int]) -> str:
    id_sql = _sql_ids(ids)
    return f"""
WITH cohort(procurement_id) AS (
    SELECT unnest(ARRAY[{id_sql}]::bigint[])
), latest AS (
    SELECT DISTINCT ON (procurement_id)
           procurement_id, upper(status) AS status, coalesce(coverage_complete, false) AS complete
      FROM estimate_row_normalization_procurements
     WHERE procurement_id = ANY(ARRAY[{id_sql}]::bigint[])
     ORDER BY procurement_id, updated_at DESC, run_id DESC
), parsed AS (
    SELECT procurement_id, count(*) AS rows
      FROM structured_estimate_rows
     WHERE procurement_id = ANY(ARRAY[{id_sql}]::bigint[])
     GROUP BY procurement_id
)
SELECT c.procurement_id, coalesce(p.rows, 0), coalesce(l.status, ''), coalesce(l.complete, false)
  FROM cohort c LEFT JOIN latest l USING (procurement_id)
  LEFT JOIN parsed p USING (procurement_id)
 ORDER BY c.procurement_id
"""


def _document_state(row: dict, research_actions: set[str], live_workers: int) -> str:
    if research_actions and research_actions <= {"NO_DOCUMENT_RESEARCH", "NO_OPPORTUNITY"}:
        return "no_document_research_required"
    if row.get("facts_found") or _number(row.get("estimate_rows")) > 0:
        return "already_researched"
    if row.get("processing"):
        return "in_progress" if live_workers > 0 else "failed"
    if row.get("failed") or row.get("result_failed"):
        return "failed"
    if row.get("no_links"):
        return "no_supported_documents"
    return "needs_research"


def collect_today_truth(
    query: Callable[[str, str, int], str],
    *,
    parse_rows_fn: Callable[[str], list[list[str]]] = parse_pipe_rows,
    live_document_workers: int = 0,
    captured_at: str | None = None,
) -> dict:
    """Read a same-day procurement cohort and its downstream authorities."""
    crm_rows = parse_rows_fn(query("crm", TODAY_COHORT_SQL, 25))
    cohort = []
    for fields in crm_rows:
        if len(fields) < 15:
            continue
        row = {
            "id": _number(fields[0]), "ai_state": fields[1],
            "qualification_state": fields[2], "routing_error": fields[3],
            "admission_state": fields[4], "admission_policy": fields[5],
            "source_lifecycle": fields[6], "current_opportunities": _number(fields[7]),
            "commercial_states": fields[8], "research_actions": fields[9],
            "has_okpd_prior": _truth(fields[10]), "old_initial_signal": _truth(fields[11]),
            "old_no_initial_signal": _truth(fields[12]), "old_classified": _truth(fields[13]),
            "old_in_progress": _truth(fields[14]),
        }
        row["commercial_decision"], row["commercial_reason"] = classify_commercial(row)
        row["lifecycle_decision"], row["lifecycle_reason"] = classify_lifecycle(row)
        cohort.append(row)

    ids = [r["id"] for r in cohort]
    doc_rows = parse_rows_fn(query("document_intelligence", document_query(ids), 15)) if ids else []
    doc_by_id = {}
    for f in doc_rows:
        if len(f) < 11:
            continue
        doc_by_id[_number(f[0])] = {
            "statuses": f[1], "processing": _truth(f[2]), "waiting": _truth(f[3]),
            "no_links": _truth(f[4]), "failed": _truth(f[5]), "worker_id": f[6],
            "result_failed": _truth(f[7]), "parsed_result": _truth(f[8]),
            "facts_found": _truth(f[9]), "estimate_rows": _number(f[10]),
        }
    norm_rows = parse_rows_fn(query("document_intelligence", normalization_query(ids), 15)) if ids else []
    norm_by_id = {}
    for f in norm_rows:
        if len(f) < 4:
            continue
        norm_by_id[_number(f[0])] = {"parsed_rows": _number(f[1]), "status": f[2].upper(), "complete": _truth(f[3])}

    buckets = {k: 0 for k in ("accepted", "rejected", "processing", "error")}
    for row in cohort:
        buckets[row["commercial_decision"]] += 1
    lifecycle = {k: 0 for k in ("actionable", "closed", "error")}
    actionable = []
    for row in cohort:
        decision = row["lifecycle_decision"]
        if decision == "not_accepted":
            continue
        lifecycle[decision] += 1
        if decision == "actionable":
            actionable.append(row)

    docs = {k: 0 for k in ("already_researched", "needs_research", "in_progress", "no_supported_documents", "no_document_research_required", "failed")}
    stale_processing = 0
    parsed_ids = set()
    normalized_ids = set()
    normalization_failed_ids = set()
    ready = 0
    for row in actionable:
        pid = row["id"]
        dr = doc_by_id.get(pid, {})
        actions = {x.strip().upper() for x in row["research_actions"].split(",") if x.strip()}
        doc_state = _document_state(dr, actions, live_document_workers)
        docs[doc_state] += 1
        if dr.get("processing") and live_document_workers <= 0:
            stale_processing += 1
        nr = norm_by_id.get(pid, {})
        parsed = nr.get("parsed_rows", 0) > 0 or dr.get("parsed_result")
        if parsed:
            parsed_ids.add(pid)
            if nr.get("status") == "COMPLETED" and nr.get("complete"):
                normalized_ids.add(pid)
            elif nr.get("status") in {"FAILED", "PARTIAL"}:
                normalization_failed_ids.add(pid)
        doc_ready = doc_state in {"already_researched", "no_document_research_required"}
        normalization_ready = not parsed or pid in normalized_ids
        if doc_ready and normalization_ready:
            ready += 1

    old = {
        "initial_signal": sum(r["old_initial_signal"] for r in cohort),
        "no_initial_signal": sum(r["old_no_initial_signal"] for r in cohort),
        "classified": sum(r["old_classified"] for r in cohort),
        "in_progress": sum(r["old_in_progress"] for r in cohort),
    }
    old["remaining"] = max(0, sum(r["admission_state"] == "ELIGIBLE" and r["admission_policy"] == ADMISSION_POLICY for r in cohort) - old["classified"])
    return {
        "available": True,
        "captured_at": captured_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "received": len(cohort),
        "cohort_ids": ids,
        "admission_eligible": sum(r["admission_state"] == "ELIGIBLE" and r["admission_policy"] == ADMISSION_POLICY for r in cohort),
        "commercial": {**buckets, "denominator": len(cohort)},
        "lifecycle": {**lifecycle, "denominator": buckets["accepted"]},
        "documents": {**docs, "stale_processing": stale_processing, "denominator": lifecycle["actionable"]},
        "normalization": {
            "parsed": len(parsed_ids), "normalized": len(normalized_ids),
            "pending": len(parsed_ids - normalized_ids - normalization_failed_ids),
            "failed": len(normalization_failed_ids), "denominator": len(parsed_ids),
        },
        "ready_cards": {"count": ready, "denominator": len(cohort)},
        "legacy": {**old, "denominator": sum(r["admission_state"] == "ELIGIBLE" and r["admission_policy"] == ADMISSION_POLICY for r in cohort)},
        "definitions": {
            "received": "crm_procurements.crm_created_at in [current_date, current_date + 1 day); denominator=that distinct procurement cohort",
            "commercial_accepted": "cohort procurement with >=1 crm_procurement_category_opportunities row where status=CURRENT",
            "commercial_rejected": "cohort procurement with no CURRENT opportunity and explicit ai_state=OUT_OF_PROFILE or qualification_state=out_of_profile",
            "commercial_processing": "cohort procurement with no CURRENT opportunity and ai_state in UNASSESSED, QUEUED, RUNNING",
            "commercial_error": "FAILED/STALE/routing error or terminal AI state without explicit commercial outcome",
            "actionable": "accepted cohort procurement; current admission policy ELIGIBLE; source_lifecycle OPEN/AWARDED; CURRENT opportunity state ACTIVE/FOLLOW_UP_AWARDED",
            "documents": "procurement-level disposition among actionable IDs; facts_found or structured_estimate_rows required for ALREADY_RESEARCHED; queue COMPLETED alone is insufficient",
            "normalization": "procurements with structured_estimate_rows; complete only when latest normalization row status=COMPLETED and coverage_complete=true",
            "ready_cards": "actionable cohort procurement with saved research facts or NO_DOCUMENT_RESEARCH action, and complete normalization when estimate rows exist",
        },
        "review_required_ids": [r["id"] for r in cohort if r["commercial_decision"] == "error" and r["commercial_reason"] == "COMPLETED_WITHOUT_CURRENT_OPPORTUNITY_OR_EXPLICIT_REJECTION"],
        "current_opportunity_count": sum(r["current_opportunities"] for r in cohort),
        "ai_states": _count_values(r["ai_state"] for r in cohort),
    }


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "UNKNOWN").upper()
        counts[key] = counts.get(key, 0) + 1
    return counts
