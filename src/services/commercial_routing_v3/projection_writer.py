"""Production V3 projection writer: S7 READ → S13 crm_procurements UPSERT.

Replaces legacy sync_all_processed as the production admission path.
Does not run AI routing or opportunity generation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.domain.commercial_routing_v3 import SourceContour
from src.services.commercial_routing_v3.projection import (
    FULL_AWARDED_HISTORY_IMPORTED,
    LEGACY_COMMERCIAL_FILTER_BEFORE_V3,
    OPEN_REQUIRES_DOCS_PROCESSED,
    OPEN_REQUIRES_KEYWORD_MATCH,
    OPEN_REQUIRES_USER_OKPD,
    RAW_PROJECTED_PROCUREMENT_IS_ACTIVE_LEAD,
    TARGET_PROJECTION_USES_S7_PROCESSED_DOCUMENTS,
    V3_PROJECTION_PARALLEL_LEGACY_WRITER,
    LifecycleIdentity,
    NotProjectedReason,
    SourceStage,
    admit_source_row,
    normalize_contract_number,
    resolve_lifecycle_identity,
    stage_from_source_table,
)
from src.services.commercial_routing_v3.source_contour import resolve_source_contour
from src.services.commercial_routing_v3.source_lifecycle import (
    lifecycle_crm_stage_status,
    normalize_source_lifecycle_event,
)

logger = logging.getLogger(__name__)

PRODUCTION_PROJECTION_WRITER = "V3"
LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH = False
PARALLEL_LEGACY_PROJECTION_WRITER = V3_PROJECTION_PARALLEL_LEGACY_WRITER
PROJECTED_ROW_ACTIVE_LEAD = RAW_PROJECTED_PROCUREMENT_IS_ACTIVE_LEAD
CROSS_CONTOUR_FALSE_DEDUPE = False

assert PRODUCTION_PROJECTION_WRITER == "V3"
assert LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH is False
assert PARALLEL_LEGACY_PROJECTION_WRITER is False
assert TARGET_PROJECTION_USES_S7_PROCESSED_DOCUMENTS is False
assert OPEN_REQUIRES_DOCS_PROCESSED is False
assert OPEN_REQUIRES_USER_OKPD is False
assert OPEN_REQUIRES_KEYWORD_MATCH is False
assert LEGACY_COMMERCIAL_FILTER_BEFORE_V3 is False
assert FULL_AWARDED_HISTORY_IMPORTED is False
assert PROJECTED_ROW_ACTIVE_LEAD is False

# Canonical S7 OKPD truth: okpd_id → collection_codes_okpd.sub_code (+ name).
# NOT main_code. V3 projection must never drop these fields.
_OKPD_SELECT = """
                    c.okpd_id AS source_okpd_id,
                    o.sub_code AS okpd_code,
                    o.name AS okpd_name
"""
_OKPD_JOIN = "LEFT JOIN collection_codes_okpd o ON o.id = c.okpd_id"
_REGION_SELECT = """
                    c.region_id,
                    COALESCE(NULLIF(btrim(c.delivery_region), ''), r.name) AS delivery_region,
                    c.delivery_address
"""
_REGION_JOIN = "LEFT JOIN region r ON r.id = c.region_id"
_CONTRACTOR_SELECT = """
                    c.contractor_id AS source_contractor_id,
                    COALESCE(ct.short_name, ct.full_name) AS winner_name,
                    ct.inn AS winner_inn,
                    ct.kpp AS winner_kpp
"""
_CONTRACTOR_JOIN = "LEFT JOIN contractor ct ON ct.id = c.contractor_id"

# (table, customer_expr, stage label for CRM storage)
_SOURCE_PULLS: Tuple[Tuple[str, str, SourceStage], ...] = (
    ("reestr_contract_44_fz", "customer", SourceStage.OPEN),
    ("reestr_contract_223_fz", "placer", SourceStage.OPEN),
    ("reestr_contract_44_fz_commission_work", "customer", SourceStage.WAITING_SOURCE_OUTCOME),
    ("reestr_contract_223_fz_commission_work", "placer", SourceStage.WAITING_SOURCE_OUTCOME),
    ("reestr_contract_44_fz_awarded", "customer", SourceStage.AWARDED),
    ("reestr_contract_223_fz_awarded", "placer", SourceStage.AWARDED),
    ("reestr_contract_44_fz_completed", "customer", SourceStage.TERMINAL),
    ("reestr_contract_44_fz_unclear", "customer", SourceStage.TERMINAL),
    ("reestr_contract_44_fz_unknown", "customer", SourceStage.TERMINAL),
    ("reestr_contract_223_fz_completed", "placer", SourceStage.TERMINAL),
    ("reestr_contract_223_fz_unclear", "placer", SourceStage.TERMINAL),
)

_STAGE_CRM = {
    SourceStage.OPEN: ("torgi", "submission_open"),
    SourceStage.WAITING_SOURCE_OUTCOME: ("commission", "commission"),
    SourceStage.AWARDED: ("razygranye", "awarded"),
    SourceStage.TERMINAL: ("commission", "terminal_no_result"),
}


@dataclass
class ProjectionSyncResult:
    dry_run: bool = False
    source_open_44: int = 0
    source_open_223: int = 0
    source_waiting_44: int = 0
    source_waiting_223: int = 0
    awarded_relevant: int = 0
    awarded_full_ignored: int = 0
    v3_eligible_unique: int = 0
    s13_crm_before: int = 0
    s13_crm_after: int = 0
    to_insert: int = 0
    to_update: int = 0
    to_reconcile: int = 0
    to_preserve_legacy: int = 0
    inserted: int = 0
    updated: int = 0
    stage_reconciled: int = 0
    duplicates_suppressed: int = 0
    legacy_preserved: int = 0
    full_awarded_ignored: int = 0
    errors: int = 0
    pending_routing_count: int = 0
    skipped_lock: int = 0
    local_expired: int = 0
    local_deadline_unknown: int = 0
    runtime_seconds: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "writer": PRODUCTION_PROJECTION_WRITER,
            "dry_run": self.dry_run,
            "source_open_44": self.source_open_44,
            "source_open_223": self.source_open_223,
            "source_waiting_44": self.source_waiting_44,
            "source_waiting_223": self.source_waiting_223,
            "awarded_relevant": self.awarded_relevant,
            "awarded_full_ignored": self.awarded_full_ignored,
            "v3_eligible_unique": self.v3_eligible_unique,
            "s13_crm_before": self.s13_crm_before,
            "s13_crm_after": self.s13_crm_after,
            "to_insert": self.to_insert,
            "to_update": self.to_update,
            "to_reconcile": self.to_reconcile,
            "to_preserve_legacy": self.to_preserve_legacy,
            "inserted": self.inserted,
            "updated": self.updated,
            "stage_reconciled": self.stage_reconciled,
            "duplicates_suppressed": self.duplicates_suppressed,
            "legacy_preserved": self.legacy_preserved,
            "full_awarded_ignored": self.full_awarded_ignored,
            "errors": self.errors,
            "pending_routing_count": self.pending_routing_count,
            "skipped_lock": self.skipped_lock,
            "local_expired": self.local_expired,
            "local_deadline_unknown": self.local_deadline_unknown,
            "runtime_seconds": self.runtime_seconds,
            "PROJECTED_ROW_ACTIVE_LEAD": PROJECTED_ROW_ACTIVE_LEAD,
            "LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH": LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH,
        }


def _tender_dicts(tender_db, sql: str, params: Optional[dict] = None) -> List[Dict[str, Any]]:
    import psycopg2.extras

    conn = tender_db.get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _crm_scalar(crm_db, sql: str, params: Optional[dict] = None) -> int:
    rows = crm_db.execute_query(sql, params) if params is not None else crm_db.execute_query(sql)
    if not rows:
        return 0
    row = rows[0]
    if isinstance(row, dict):
        return int(next(iter(row.values())))
    return int(row[0])


def _crm_stage_for(source_table: str, end_date: Any, stage: Optional[SourceStage] = None) -> Tuple[str, str]:
    """ONE canonical temporal lifecycle → crm_stage/award_status."""
    table = str(source_table or "")
    # Physical awarded/commission still win via normalizer; end_date drives open→waiting.
    if stage == SourceStage.AWARDED or "awarded" in table.lower():
        seed_stage, seed_status = "razygranye", "awarded"
    elif stage == SourceStage.WAITING_SOURCE_OUTCOME or "commission" in table.lower():
        seed_stage, seed_status = "commission", "commission"
    else:
        seed_stage, seed_status = "torgi", "submission_open"
    event = normalize_source_lifecycle_event(
        source_table=table,
        crm_stage=seed_stage,
        award_status=seed_status,
        end_date=end_date,
    )
    crm_stage, award_status = lifecycle_crm_stage_status(event, source_table=table)
    # WIP=S7-S13-LIFECYCLE-SYNC-1 section 3: a missing deadline is recorded
    # explicitly instead of masquerading as an open/waiting submission.
    if crm_stage == "torgi" and (
        end_date is None or (isinstance(end_date, str) and not end_date.strip())
    ):
        award_status = "deadline_unknown"
    return crm_stage, award_status


def _contour_match_sql(contour: SourceContour) -> str:
    # Escape %% for psycopg2 pyformat (ILIKE wildcards).
    if contour == SourceContour.CORPORATE_223FZ:
        return "source_table ILIKE '%%223_fz%%'"
    return "(source_table ILIKE '%%44_fz%%' OR source_table ILIKE '%%615%%')"


# --- lifecycle bookkeeping + bounded temporal reconciliation -----------------

V3_SYNC_JOB_TYPE = "v3_projection_sync"
OPEN_PULL_WATERMARK_OVERLAP = timedelta(minutes=10)
RUNNING_SYNC_STALE_AFTER = timedelta(minutes=30)


def _resolve_open_watermark(crm_db, now: datetime) -> Optional[datetime]:
    """Start of the previous successful V3 run (minus overlap), or None (bootstrap).

    Used to pull only source rows changed since the last completed cycle instead
    of re-reading the whole open surface (301k + 124k rows) every 5 minutes.
    """
    rows = crm_db.execute_query(
        "SELECT started_at FROM crm_sync_jobs "
        "WHERE job_type = %s AND status = 'ok' ORDER BY id DESC LIMIT 1",
        (V3_SYNC_JOB_TYPE,),
    )
    if not rows:
        return None
    value = rows[0]["started_at"] if isinstance(rows[0], dict) else rows[0][0]
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value - OPEN_PULL_WATERMARK_OVERLAP


def _start_sync_job(crm_db, started_at: datetime) -> Optional[int]:
    try:
        crm_db.execute_update(
            "INSERT INTO crm_sync_jobs "
            "(job_type, trigger_type, requested_by, status, started_at, created_at) "
            "VALUES (%s, 'scheduled', 'run_crm_sync', 'running', %s, now())",
            (V3_SYNC_JOB_TYPE, started_at),
        )
        return int(_crm_scalar(
            crm_db,
            "SELECT id FROM crm_sync_jobs WHERE job_type = %s ORDER BY id DESC LIMIT 1",
            (V3_SYNC_JOB_TYPE,),
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("v3 sync job start failed: %s", exc)
        return None


def _finish_sync_job(crm_db, job_id: Optional[int], payload: Dict[str, Any], error: Optional[str] = None) -> None:
    if job_id is None:
        return
    try:
        crm_db.execute_update(
            "UPDATE crm_sync_jobs SET status = %s, finished_at = now(), "
            "processed_count = %s, updated_count = %s, awarded_count = %s, "
            "not_found_count = 0, error_count = %s, error_message = %s WHERE id = %s",
            (
                "error" if error else "ok",
                int(payload.get("v3_eligible_unique") or 0),
                int(payload.get("updated") or 0),
                int(payload.get("stage_reconciled") or 0) + int(payload.get("local_expired") or 0),
                int(payload.get("errors") or 0),
                error,
                job_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("v3 sync job finish failed: %s", exc)


def _rederive_local_lifecycle(crm_db, dry_run: bool) -> Dict[str, int]:
    """Bounded temporal re-derivation of S13 lifecycle state without reading S7.

    Only physical 'torgi' rows are touched; awarded/commission/manual_hold rows
    are never modified, so no state regression is possible here.
    """
    counts = {
        "expired": int(_crm_scalar(
            crm_db,
            "SELECT count(*) FROM crm_procurements WHERE crm_stage = 'torgi' "
            "AND end_date IS NOT NULL AND end_date < current_date "
            "AND award_status = 'submission_open'",
        )),
        "deadline_unknown": int(_crm_scalar(
            crm_db,
            "SELECT count(*) FROM crm_procurements WHERE crm_stage = 'torgi' "
            "AND end_date IS NULL AND award_status IS DISTINCT FROM 'deadline_unknown'",
        )),
    }
    if dry_run:
        return counts
    if counts["expired"]:
        crm_db.execute_update(
            "UPDATE crm_procurements SET award_status = 'submission_closed_waiting_award', "
            "crm_updated_at = now() WHERE crm_stage = 'torgi' AND end_date IS NOT NULL "
            "AND end_date < current_date AND award_status = 'submission_open'"
        )
    if counts["deadline_unknown"]:
        crm_db.execute_update(
            "UPDATE crm_procurements SET award_status = 'deadline_unknown', "
            "crm_updated_at = now() WHERE crm_stage = 'torgi' AND end_date IS NULL "
            "AND award_status IS DISTINCT FROM 'deadline_unknown'"
        )
    return counts


def _build_crm_index(crm_db) -> Dict[str, Any]:
    """In-memory lifecycle index to avoid N+1 lookups."""
    rows = crm_db.execute_query(
        "SELECT id, source_table, source_id, contract_number, crm_stage, "
        "source_awarded_table, source_awarded_id, ai_assessment_status "
        "FROM crm_procurements"
    ) or []
    by_stable: Dict[Tuple, Dict[str, Any]] = {}
    by_prov: Dict[Tuple, Dict[str, Any]] = {}
    by_awarded: Dict[Tuple, Dict[str, Any]] = {}
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        st = str(d.get("source_table") or "")
        contour = resolve_source_contour(source_table=st)
        cn = normalize_contract_number(d.get("contract_number"))
        if cn and contour != SourceContour.UNKNOWN:
            key = ("stable", contour.value, cn)
            by_stable.setdefault(key, d)
        if d.get("source_id") is not None:
            by_prov[(st, int(d["source_id"]))] = d
        if d.get("source_awarded_table") and d.get("source_awarded_id") is not None:
            by_awarded[(str(d["source_awarded_table"]), int(d["source_awarded_id"]))] = d
    return {"by_stable": by_stable, "by_prov": by_prov, "by_awarded": by_awarded, "rows": rows}


def _find_existing_indexed(index: Dict[str, Any], ident: LifecycleIdentity) -> Optional[Dict[str, Any]]:
    if ident.source_table and ident.source_id is not None:
        hit = index["by_prov"].get((ident.source_table, int(ident.source_id)))
        if hit:
            return hit
        hit = index["by_awarded"].get((ident.source_table, int(ident.source_id)))
        if hit:
            return hit
    if ident.contract_number:
        hit = index["by_stable"].get(ident.key())
        if hit:
            return hit
    return None


def _find_existing(crm_db, ident: LifecycleIdentity) -> Optional[Dict[str, Any]]:
    if ident.source_table and ident.source_id is not None:
        rows = crm_db.execute_query(
            """
            SELECT * FROM crm_procurements
            WHERE source_table = %(st)s AND source_id = %(sid)s
            LIMIT 1
            """,
            {"st": ident.source_table, "sid": int(ident.source_id)},
        )
        if rows:
            return dict(rows[0]) if not isinstance(rows[0], dict) else rows[0]
        rows = crm_db.execute_query(
            """
            SELECT * FROM crm_procurements
            WHERE source_awarded_table = %(st)s AND source_awarded_id = %(sid)s
            LIMIT 1
            """,
            {"st": ident.source_table, "sid": int(ident.source_id)},
        )
        if rows:
            return dict(rows[0]) if not isinstance(rows[0], dict) else rows[0]
    if ident.contract_number:
        rows = crm_db.execute_query(
            f"""
            SELECT * FROM crm_procurements
            WHERE btrim(contract_number) = %(cn)s
              AND {_contour_match_sql(ident.source_contour)}
            ORDER BY id ASC
            LIMIT 2
            """,
            {"cn": ident.contract_number},
        )
        if rows:
            return dict(rows[0]) if not isinstance(rows[0], dict) else rows[0]
    return None


def _load_crm_identity_sets(crm_db) -> Tuple[set, set, set]:
    """Return (source_ids, cn_44, cn_223) for awarded admission."""
    rows = crm_db.execute_query(
        "SELECT source_id, source_table, contract_number, source_awarded_id FROM crm_procurements"
    ) or []
    ids: set = set()
    cn44: set = set()
    cn223: set = set()
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        if d.get("source_id") is not None:
            ids.add(int(d["source_id"]))
        if d.get("source_awarded_id") is not None:
            ids.add(int(d["source_awarded_id"]))
        cn = normalize_contract_number(d.get("contract_number"))
        if not cn:
            continue
        st = str(d.get("source_table") or "")
        if "223" in st:
            cn223.add(cn)
        else:
            cn44.add(cn)
    return ids, cn44, cn223


def _pull_source_rows(
    tender_db,
    crm_db,
    *,
    awarded_watermark: datetime,
    open_watermark: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], ProjectionSyncResult]:
    result = ProjectionSyncResult()
    crm_ids, cn44, cn223 = _load_crm_identity_sets(crm_db)
    out: List[Dict[str, Any]] = []

    _cols_cache: Dict[str, set] = {}

    def _table_columns(tbl: str) -> set:
        if tbl not in _cols_cache:
            rows = _tender_dicts(
                tender_db,
                "SELECT column_name FROM information_schema.columns WHERE table_name = %(t)s",
                {"t": tbl},
            ) or []
            _cols_cache[tbl] = {str(r.get("column_name") or "") for r in rows}
        return _cols_cache[tbl]

    for table, cust_col, stage in _SOURCE_PULLS:
        if stage not in (SourceStage.AWARDED, SourceStage.TERMINAL):
            # Incremental open pull: only rows changed since the previous
            # successful cycle (WIP=S7-S13-LIFECYCLE-SYNC-1 section 5).
            wm_clause = "WHERE c.updated_at > %(owm)s" if open_watermark is not None else ""
            sql = f"""
                SELECT
                    c.id AS source_id,
                    c.contract_number,
                    c.auction_name,
                    c.initial_price,
                    c.final_price,
                    c.{cust_col} AS customer,
                    c.start_date,
                    c.end_date,
                    c.delivery_start_date,
                    c.delivery_end_date,
                    c.tender_link,
                    c.updated_at AS source_updated_at,
                    c.created_at AS source_created_at,
                    c.customer_id AS source_customer_id,
                    {_REGION_SELECT},
                    {_OKPD_SELECT}
                FROM {table} c
                {_OKPD_JOIN}
                {_REGION_JOIN}
                {wm_clause}
            """
            rows = _tender_dicts(
                tender_db, sql,
                {"owm": open_watermark} if open_watermark is not None else None,
            )
            for row in rows:
                row["source_table"] = table
                out.append(row)
            n = len(rows)
            if table.endswith("44_fz") and "commission" not in table and "awarded" not in table:
                result.source_open_44 = n
            elif table.endswith("223_fz") and "commission" not in table and "awarded" not in table:
                result.source_open_223 = n
            elif "44_fz_commission" in table:
                result.source_waiting_44 = n
            elif "223_fz_commission" in table:
                result.source_waiting_223 = n
            continue

        # AWARDED / TERMINAL: existing identity OR incremental watermark only
        is_223 = "223" in table
        cn_list = list(cn223 if is_223 else cn44) or ["__none__"]
        id_list = list(crm_ids) or [-1]
        # terminal physical tables (e.g. *_completed) may lack created/updated_at
        _cols = _table_columns(table)
        upd_expr = "c.updated_at" if "updated_at" in _cols else "NULL::timestamptz"
        cre_expr = "c.created_at" if "created_at" in _cols else "NULL::timestamptz"
        if stage == SourceStage.TERMINAL:
            # Cheap incremental terminal pull: only recently changed terminal rows
            # (historical terminal transitions were reconciled by identity).
            sql = f"""
                SELECT
                    c.id AS source_id, c.contract_number, c.auction_name,
                    c.initial_price, c.final_price, c.{cust_col} AS customer,
                    c.start_date, c.end_date, c.delivery_start_date, c.delivery_end_date,
                    c.tender_link, {upd_expr} AS source_updated_at,
                    {cre_expr} AS source_created_at, c.customer_id AS source_customer_id,
                    {_REGION_SELECT}, {_OKPD_SELECT}
                FROM {table} c {_OKPD_JOIN} {_REGION_JOIN}
                WHERE {upd_expr} > %(wm)s
            """
            rows = _tender_dicts(tender_db, sql, {"wm": awarded_watermark}) or []
            for row in rows:
                row["source_table"] = table
                out.append(row)
            continue
        sql = f"""
            SELECT
                c.id AS source_id,
                c.contract_number,
                c.auction_name,
                c.initial_price,
                c.final_price,
                c.{cust_col} AS customer,
                c.start_date,
                c.end_date,
                c.delivery_start_date,
                c.delivery_end_date,
                c.tender_link,
                {upd_expr} AS source_updated_at,
                {cre_expr} AS source_created_at,
                c.customer_id AS source_customer_id,
                {_REGION_SELECT},
                {_OKPD_SELECT},
                {_CONTRACTOR_SELECT},
                CASE
                  WHEN NULLIF(btrim(c.contract_number),'') = ANY(%(cns)s)
                    OR c.id = ANY(%(ids)s) THEN 'EXISTING'
                  WHEN {upd_expr} > %(wm)s THEN 'INCREMENTAL'
                  ELSE 'HISTORY'
                END AS award_bucket
            FROM {table} c
            {_OKPD_JOIN}
            {_REGION_JOIN}
            {_CONTRACTOR_JOIN}
        """
        rows = _tender_dicts(
            tender_db,
            sql,
            {"cns": cn_list, "ids": id_list, "wm": awarded_watermark},
        )
        for row in rows:
            row["source_table"] = table
            bucket = row.pop("award_bucket", "HISTORY")
            if bucket == "HISTORY":
                result.awarded_full_ignored += 1
                continue
            result.awarded_relevant += 1
            out.append(row)

    result.full_awarded_ignored = result.awarded_full_ignored
    return out, result


def _factual_completeness(row: Dict[str, Any]) -> Tuple:
    """Deterministic 'most complete factual row' score (no synthetic merge)."""
    try:
        price = float(row.get("initial_price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return (
        1 if str(row.get("contract_number") or "").strip() else 0,
        1 if row.get("start_date") else 0,
        1 if row.get("end_date") else 0,
        1 if price > 0 else 0,
        1 if str(row.get("auction_name") or "").strip() else 0,
        1 if str(row.get("okpd_code") or "").strip() else 0,
        1 if (row.get("customer") or row.get("source_customer_id")) else 0,
    )


def _dedupe_by_lifecycle(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep highest stage per lifecycle key (TERMINAL > AWARDED > WAITING > OPEN).

    Same-stage duplicates are resolved deterministically: the most complete
    factual row wins; ties break on source_id (descending). Values are NOT
    merged across physical rows here.
    """
    rank = {
        SourceStage.OPEN: 1,
        SourceStage.WAITING_SOURCE_OUTCOME: 2,
        SourceStage.AWARDED: 3,
        SourceStage.TERMINAL: 4,
    }
    best: Dict[Tuple, Dict[str, Any]] = {}
    for row in rows:
        ident = resolve_lifecycle_identity(
            source_table=str(row.get("source_table") or ""),
            source_id=row.get("source_id"),
            contract_number=row.get("contract_number"),
        )
        stage = stage_from_source_table(str(row.get("source_table") or ""))
        prev = best.get(ident.key())
        if prev is None:
            best[ident.key()] = row
            continue
        prev_stage = stage_from_source_table(str(prev.get("source_table") or ""))
        if rank[stage] > rank[prev_stage]:
            best[ident.key()] = row
        elif rank[stage] == rank[prev_stage]:
            if _factual_completeness(row) > _factual_completeness(prev):
                best[ident.key()] = row
            elif _factual_completeness(row) == _factual_completeness(prev) and (
                int(row.get("source_id") or 0) > int(prev.get("source_id") or 0)
            ):
                best[ident.key()] = row
    return list(best.values())


def _upsert_one(crm_db, row: Dict[str, Any], existing: Optional[Dict[str, Any]], dry_run: bool) -> str:
    """Return action: insert|update|reconcile|duplicate|error."""
    effective_start = row.get("start_date")
    effective_end = row.get("end_date")
    deadline_trust = "TRUSTED"

    is_223 = str(row.get("source_table") or "").startswith("reestr_contract_223_fz")
    if is_223:
        source_created = row.get("source_created_at")
        if isinstance(source_created, str):
            try:
                if " " in source_created:
                    source_created = datetime.strptime(source_created.split(".")[0], "%Y-%m-%d %H:%M:%S")
                else:
                    source_created = datetime.fromisoformat(source_created.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                source_created = None
        elif isinstance(source_created, datetime):
            source_created = source_created.replace(tzinfo=None)

        is_stale_source = False
        if source_created:
            if source_created < datetime(2026, 8, 16):
                is_stale_source = True

        if is_stale_source:
            source_updated = row.get("source_updated_at")
            if isinstance(source_updated, str):
                try:
                    if " " in source_updated:
                        source_updated = datetime.strptime(source_updated.split(".")[0], "%Y-%m-%d %H:%M:%S")
                    else:
                        source_updated = datetime.fromisoformat(source_updated.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    source_updated = None
            elif isinstance(source_updated, datetime):
                source_updated = source_updated.replace(tzinfo=None)

            is_repaired = False
            if source_updated and source_updated >= datetime(2026, 8, 16):
                is_repaired = True

            if is_repaired:
                effective_end = row.get("end_date")
                deadline_trust = "RECOVERED"
            else:
                effective_end = None
                deadline_trust = "UNRECOVERABLE_LEGACY"

    stage = stage_from_source_table(str(row.get("source_table") or ""))
    crm_stage, award_status = _crm_stage_for(str(row.get("source_table") or ""), effective_end, stage)
    cn = normalize_contract_number(row.get("contract_number")) or ""
    title = (str(row.get("auction_name")).strip() if row.get("auction_name") is not None else "") or ""
    okpd_code = row.get("okpd_code")
    if okpd_code is not None:
        okpd_code = str(okpd_code).strip() or None
    okpd_name = row.get("okpd_name")
    if okpd_name is not None:
        okpd_name = str(okpd_name).strip() or None
    from src.services.procurement_identity import canonical_tender_link_for_storage

    tender_link = canonical_tender_link_for_storage(
        source_table=row.get("source_table"),
        contract_number=cn,
        tender_link=row.get("tender_link"),
    )

    if is_223 and is_stale_source and not is_repaired:
        crm_stage = "torgi"
        # Deadline is untrustworthy -> explicit unknown state, never open.
        award_status = "deadline_unknown"

    payload = {
        "source_table": row.get("source_table"),
        "source_id": int(row["source_id"]),
        "contract_number": cn or f"MISSING-{row.get('source_table')}-{row.get('source_id')}",
        "auction_name": title or "(без названия)",
        "initial_price": row.get("initial_price"),
        "final_price": row.get("final_price"),
        "customer": row.get("customer"),
        "delivery_region": row.get("delivery_region"),
        "region_id": row.get("region_id"),
        "okpd_code": okpd_code,
        "okpd_name": okpd_name,
        "start_date": effective_start,
        "end_date": effective_end,
        "delivery_start_date": row.get("delivery_start_date"),
        "delivery_end_date": row.get("delivery_end_date"),
        "tender_link": tender_link,
        "source_updated_at": row.get("source_updated_at"),
        "crm_stage": crm_stage,
        "award_status": award_status,
        "ai_assessment_status": "UNASSESSED",
        "winner_name": row.get("winner_name"),
        "winner_inn": row.get("winner_inn"),
        "final_contract_price": row.get("final_price") if stage == SourceStage.AWARDED else None,
        "deadline_trust": deadline_trust,
    }
    if stage == SourceStage.AWARDED:
        payload["source_awarded_table"] = row.get("source_table")
        payload["source_awarded_id"] = int(row["source_id"])

    if dry_run:
        if existing is None:
            return "insert"
        old_stage = existing.get("crm_stage")
        if old_stage != crm_stage or existing.get("source_table") != payload["source_table"]:
            return "reconcile"
        return "update"

    try:
        if existing is None:
            crm_db.execute_update(
                """
                INSERT INTO crm_procurements (
                    source_table, source_id, contract_number, auction_name,
                    initial_price, final_price, customer, delivery_region, region_id,
                    okpd_code, okpd_name,
                    start_date, end_date, delivery_start_date, delivery_end_date,
                    tender_link, source_updated_at,
                    crm_stage, award_status, qualification_state, ai_assessment_status,
                    source_awarded_table, source_awarded_id,
                    winner_name, winner_inn, final_contract_price,
                    deadline_trust
                ) VALUES (
                    %(source_table)s, %(source_id)s, %(contract_number)s, %(auction_name)s,
                    %(initial_price)s, %(final_price)s, %(customer)s, %(delivery_region)s, %(region_id)s,
                    %(okpd_code)s, %(okpd_name)s,
                    %(start_date)s, %(end_date)s, %(delivery_start_date)s, %(delivery_end_date)s,
                    %(tender_link)s, %(source_updated_at)s,
                    %(crm_stage)s, %(award_status)s, 'unassessed', %(ai_assessment_status)s,
                    %(source_awarded_table)s, %(source_awarded_id)s,
                    %(winner_name)s, %(winner_inn)s, %(final_contract_price)s,
                    %(deadline_trust)s
                )
                """,
                {
                    **payload,
                    "source_awarded_table": payload.get("source_awarded_table"),
                    "source_awarded_id": payload.get("source_awarded_id"),
                },
            )
            return "insert"

        old_stage = existing.get("crm_stage")
        crm_db.execute_update(
            """
            UPDATE crm_procurements SET
                source_table = %(source_table)s,
                source_id = %(source_id)s,
                contract_number = CASE
                    WHEN btrim(coalesce(contract_number,'')) = '' THEN %(contract_number)s
                    ELSE contract_number
                END,
                auction_name = COALESCE(NULLIF(%(auction_name)s,''), auction_name),
                initial_price = COALESCE(%(initial_price)s, initial_price),
                final_price = COALESCE(%(final_price)s, final_price),
                customer = COALESCE(%(customer)s, customer),
                delivery_region = COALESCE(%(delivery_region)s, delivery_region),
                region_id = COALESCE(%(region_id)s, region_id),
                okpd_code = COALESCE(%(okpd_code)s, okpd_code),
                okpd_name = COALESCE(%(okpd_name)s, okpd_name),
                start_date = COALESCE(%(start_date)s, start_date),
                end_date = CASE
                    WHEN %(source_updated_at)s IS NOT NULL
                         AND source_updated_at IS NOT NULL
                         AND %(source_updated_at)s < source_updated_at THEN end_date
                    ELSE %(end_date)s
                END,
                delivery_start_date = COALESCE(%(delivery_start_date)s, delivery_start_date),
                delivery_end_date = COALESCE(%(delivery_end_date)s, delivery_end_date),
                tender_link = COALESCE(%(tender_link)s, tender_link),
                source_updated_at = COALESCE(%(source_updated_at)s, source_updated_at),
                winner_name = COALESCE(%(winner_name)s, winner_name),
                winner_inn = COALESCE(%(winner_inn)s, winner_inn),
                final_contract_price = COALESCE(%(final_contract_price)s, final_contract_price),
                crm_stage = CASE
                    WHEN crm_stage = 'manual_hold' THEN crm_stage
                    -- never downgrade a physically awarded lifecycle row
                    WHEN crm_stage = 'razygranye' AND %(crm_stage)s <> 'razygranye' THEN crm_stage
                    -- never apply lifecycle from a stale/older source row
                    WHEN %(source_updated_at)s IS NOT NULL
                         AND source_updated_at IS NOT NULL
                         AND %(source_updated_at)s < source_updated_at THEN crm_stage
                    ELSE %(crm_stage)s
                END,
                award_status = CASE
                    WHEN crm_stage = 'manual_hold' THEN award_status
                    WHEN crm_stage = 'razygranye' AND %(crm_stage)s <> 'razygranye' THEN award_status
                    WHEN %(source_updated_at)s IS NOT NULL
                         AND source_updated_at IS NOT NULL
                         AND %(source_updated_at)s < source_updated_at THEN award_status
                    ELSE %(award_status)s
                END,
                source_awarded_table = COALESCE(%(source_awarded_table)s, source_awarded_table),
                source_awarded_id = COALESCE(%(source_awarded_id)s, source_awarded_id),
                deadline_trust = %(deadline_trust)s,
                crm_updated_at = now()
            WHERE id = %(id)s
            """,
            {
                **payload,
                "id": int(existing["id"]),
                "source_awarded_table": payload.get("source_awarded_table"),
                "source_awarded_id": payload.get("source_awarded_id"),
            },
        )
        if old_stage != crm_stage or existing.get("source_table") != payload["source_table"]:
            return "reconcile"
        return "update"
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" in msg or "duplicate" in msg:
            return "duplicate"
        logger.exception("projection upsert failed: %s", exc)
        return "error"


def _run_v3_projection_sync_body(
    tender_db,
    crm_db,
    *,
    dry_run: bool = False,
    awarded_watermark: Optional[datetime] = None,
    open_watermark: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Inner V3 projection pass (no job bookkeeping). S7 read-only."""
    assert PRODUCTION_PROJECTION_WRITER == "V3"
    assert LEGACY_SYNC_ALL_PROCESSED_PRODUCTION_PATH is False
    run_started = datetime.now(timezone.utc)
    wm = awarded_watermark or datetime.now(timezone.utc)
    before = _crm_scalar(crm_db, "SELECT count(*) FROM crm_procurements")

    raw_rows, result = _pull_source_rows(
        tender_db, crm_db, awarded_watermark=wm, open_watermark=open_watermark
    )
    result.dry_run = dry_run
    result.s13_crm_before = before
    crm_index = _build_crm_index(crm_db)

    # Admission + lifecycle unique set
    eligible: List[Dict[str, Any]] = []
    lifecycle_keys: set = set()
    for row in raw_rows:
        ident = resolve_lifecycle_identity(
            source_table=str(row.get("source_table") or ""),
            source_id=row.get("source_id"),
            contract_number=row.get("contract_number"),
        )
        existing = _find_existing_indexed(crm_index, ident)
        decision = admit_source_row(
            source_table=str(row.get("source_table") or ""),
            source_id=row.get("source_id"),
            contract_number=row.get("contract_number"),
            auction_name=row.get("auction_name"),
            source_updated_at=row.get("source_updated_at"),
            awarded_watermark=wm,
            crm_has_lifecycle_identity=existing is not None,
            enabled=True,  # production writer always enabled
        )
        if not decision.admit:
            if decision.reason == NotProjectedReason.FULL_AWARDED_HISTORY_EXCLUDED:
                result.full_awarded_ignored += 1
            continue
        eligible.append(row)
        lifecycle_keys.add(ident.key())

    deduped = _dedupe_by_lifecycle(eligible)
    result.v3_eligible_unique = len(deduped)
    result.duplicates_suppressed += max(0, len(eligible) - len(deduped))

    touched_ids: set = set()
    for row in deduped:
        ident = resolve_lifecycle_identity(
            source_table=str(row.get("source_table") or ""),
            source_id=row.get("source_id"),
            contract_number=row.get("contract_number"),
        )
        existing = _find_existing_indexed(crm_index, ident)
        action = _upsert_one(crm_db, row, existing, dry_run=dry_run)
        if existing is not None:
            touched_ids.add(int(existing["id"]))
        if action == "insert":
            result.to_insert += 1
            if not dry_run:
                result.inserted += 1
                # keep index coherent for later rows in same run
                new_row = {
                    "id": -1,
                    "source_table": row.get("source_table"),
                    "source_id": row.get("source_id"),
                    "contract_number": normalize_contract_number(row.get("contract_number")),
                    "crm_stage": _crm_stage_for(str(row.get("source_table") or ""), row.get("end_date"))[0],
                }
                if new_row["contract_number"]:
                    crm_index["by_stable"][ident.key()] = new_row
                if row.get("source_id") is not None:
                    crm_index["by_prov"][(str(row.get("source_table")), int(row["source_id"]))] = new_row
        elif action == "update":
            result.to_update += 1
            if not dry_run:
                result.updated += 1
        elif action == "reconcile":
            result.to_reconcile += 1
            if not dry_run:
                result.stage_reconciled += 1
                result.updated += 1
                if existing is not None:
                    existing["source_table"] = row.get("source_table")
                    existing["source_id"] = row.get("source_id")
                    existing["crm_stage"] = _crm_stage_for(
                        str(row.get("source_table") or ""),
                        row.get("end_date"),
                    )[0]
        elif action == "duplicate":
            result.duplicates_suppressed += 1
        elif action == "error":
            result.errors += 1

    # Legacy preserve: existing CRM rows not matched by this projection pass
    after_plan_touched = result.to_insert + result.to_update + result.to_reconcile
    result.to_preserve_legacy = max(0, before - (result.to_update + result.to_reconcile))
    result.legacy_preserved = result.to_preserve_legacy

    if dry_run:
        result.s13_crm_after = before
    else:
        result.s13_crm_after = _crm_scalar(crm_db, "SELECT count(*) FROM crm_procurements")

    result.pending_routing_count = _crm_scalar(
        crm_db,
        """
        SELECT count(*) FROM crm_procurements
        WHERE coalesce(ai_assessment_status,'UNASSESSED') IN ('UNASSESSED','RUNNING','')
        """,
    )
    result.details = {
        "awarded_watermark": wm.isoformat(),
        "eligible_raw": len(eligible),
        "open_pull_incremental": open_watermark is not None,
        "open_watermark": open_watermark.isoformat() if open_watermark is not None else None,
        "OPEN_REQUIRES_DOCS_PROCESSED": OPEN_REQUIRES_DOCS_PROCESSED,
        "OPEN_REQUIRES_USER_OKPD": OPEN_REQUIRES_USER_OKPD,
        "FULL_AWARDED_HISTORY_IMPORTED": FULL_AWARDED_HISTORY_IMPORTED,
        "after_plan_touched": after_plan_touched,
    }
    # Bounded temporal re-derivation: no S7 read, physical 'torgi' rows only.
    local = _rederive_local_lifecycle(crm_db, dry_run)
    result.local_expired = local["expired"]
    result.local_deadline_unknown = local["deadline_unknown"]
    if not dry_run:
        result.s13_crm_after = _crm_scalar(crm_db, "SELECT count(*) FROM crm_procurements")
    result.runtime_seconds = round((datetime.now(timezone.utc) - run_started).total_seconds(), 2)
    logger.info("V3 projection sync result: %s", result.as_dict())
    return result.as_dict()


def run_v3_projection_sync(
    tender_db,
    crm_db,
    *,
    dry_run: bool = False,
    awarded_watermark: Optional[datetime] = None,
    open_watermark: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Production V3 projection sync entrypoint with lifecycle bookkeeping.

    S7 read-only; S13 writes when dry_run=False. The awarded reconciliation and
    the bounded local temporal pass run every cycle; the open source pull is
    incremental via the watermark of the previous successful cycle.
    """
    started = datetime.now(timezone.utc)

    running = crm_db.execute_query(
        "SELECT id FROM crm_sync_jobs WHERE job_type = %s AND status = 'running' "
        "AND started_at > %s LIMIT 1",
        (V3_SYNC_JOB_TYPE, started - RUNNING_SYNC_STALE_AFTER),
    )
    if running:
        logger.warning("run_v3_projection_sync: previous run still running; skipping cycle")
        return ProjectionSyncResult(dry_run=dry_run, skipped_lock=1).as_dict()

    job_id = None if dry_run else _start_sync_job(crm_db, started)
    if open_watermark is None:
        open_watermark = _resolve_open_watermark(crm_db, started)

    try:
        payload = _run_v3_projection_sync_body(
            tender_db,
            crm_db,
            dry_run=dry_run,
            awarded_watermark=awarded_watermark,
            open_watermark=open_watermark,
        )
    except Exception as exc:  # noqa: BLE001
        _finish_sync_job(crm_db, job_id, {}, error=str(exc))
        raise

    _finish_sync_job(crm_db, job_id, payload)
    return payload
