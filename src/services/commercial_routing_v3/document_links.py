"""Read-only S7 document link resolution for canonical cards.

ZERO_LINK_ROOT_CAUSE (Wave-1): producer counted links by contract_id, but
links_documentation_44_fz predominantly has contract_id NULL and
contract_number populated. 223 often has contract_id.

Canonical resolution order:
  1) contract_number match when available
  2) else contract_id = source_id
Never download. Never invent URLs.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from src.services.commercial_routing_v3.research_queue_lifecycle import links_table_for_source

logger = logging.getLogger("commercial_routing_v3.document_links")

ZERO_LINK_ROOT_CAUSE = (
    "Wave-1 used COUNT WHERE contract_id=source_id; on 44-FZ "
    "links_documentation_44_fz.contract_id is mostly NULL while contract_number is set. "
    "Resolver must prefer contract_number, fallback contract_id."
)


def _s7_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST") or os.getenv("TENDER_DB_HOST") or os.getenv("TENDER_MONITOR_DB_HOST") or "10.8.0.7",
        "port": int(os.getenv("DB_PORT") or os.getenv("TENDER_DB_PORT") or os.getenv("TENDER_MONITOR_DB_PORT") or 5432),
        "dbname": os.getenv("DB_NAME") or os.getenv("TENDER_DB_DATABASE") or os.getenv("TENDER_MONITOR_DB_DATABASE") or "tender_monitor",
        "user": os.getenv("DB_USER") or os.getenv("TENDER_DB_USER") or os.getenv("TENDER_MONITOR_DB_USER") or "postgres",
        "password": os.getenv("DB_PASSWORD") or os.getenv("TENDER_DB_PASSWORD") or os.getenv("TENDER_MONITOR_DB_PASSWORD") or "oTIg3EqK85pux8SfZTuCbS-bEcObXiGfV3P2hU2m5uJ_pYMbRtRmP8jnMA-hvyhR",
        "connect_timeout": int(os.getenv("S7_LINK_CONNECT_TIMEOUT", "8")),
    }


def resolve_document_links(
    *,
    source_table: str,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    table = links_table_for_source(source_table)
    links: List[Dict[str, Any]] = []
    method = None
    error = None
    try:
        conn = psycopg2.connect(**_s7_dsn())
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cn = (contract_number or "").strip()
                if cn:
                    cur.execute(
                        f"""
                        SELECT id, contract_id, contract_number, document_links, file_name
                        FROM {table}
                        WHERE contract_number = %s
                        ORDER BY id
                        LIMIT %s
                        """,
                        (cn, limit),
                    )
                    rows = cur.fetchall() or []
                    if rows:
                        method = "contract_number"
                        links = [dict(r) for r in rows]
                if not links and source_id is not None:
                    cur.execute(
                        f"""
                        SELECT id, contract_id, contract_number, document_links, file_name
                        FROM {table}
                        WHERE contract_id = %s
                        ORDER BY id
                        LIMIT %s
                        """,
                        (int(source_id), limit),
                    )
                    rows = cur.fetchall() or []
                    if rows:
                        method = "contract_id"
                        links = [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        error = str(exc)
        logger.warning("document link resolve failed: %s", exc)

    normalized = []
    physical_rows: Dict[str, Dict[str, Any]] = {}
    urls = set()
    physical_keys = set()
    source_ids = set()
    dup_physical = 0
    for r in links:
        url = r.get("document_links")
        sid = r.get("id")
        if sid is not None:
            source_ids.add(sid)
        phys = _physical_download_key(url)
        if url:
            urls.add(str(url))
        if phys:
            if phys in physical_keys:
                dup_physical += 1
                grouped = physical_rows[phys]
                grouped["source_row_count"] += 1
                if sid is not None:
                    grouped["source_document_ids"].append(sid)
                continue
            physical_keys.add(phys)
        item = {
                "source_document_id": sid,
                "source_document_ids": [sid] if sid is not None else [],
                "source_row_count": 1,
                "document_url": url,
                "document_name": r.get("file_name"),
                "document_type": None,
                "link_source": table,
                "resolution_method": method,
                "physical_download_key": phys,
            }
        normalized.append(item)
        if phys:
            physical_rows[phys] = item
    return {
        "links": normalized,
        "link_count": len(links),
        "raw_document_link_count": len(links),
        "unique_url_count": len(urls),
        "unique_document_url_count": len(urls),
        "unique_source_document_id_count": len(source_ids),
        "unique_physical_download_target_count": len(physical_keys),
        "duplicate_physical_download_targets": dup_physical,
        "document_version_count": len(source_ids),
        "resolution_method": method,
        "link_table": table,
        "error": error,
        "ZERO_LINK_ROOT_CAUSE": ZERO_LINK_ROOT_CAUSE,
    }


def _physical_download_key(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    s = str(url).strip()
    # EIS uid is the stable file identity across version rows
    for marker in ("uid=", "UID="):
        if marker in s:
            return s.split(marker, 1)[1].split("&", 1)[0].strip()
    return s


# Aligned with document_processor.file_skip_list (worker researchable gate).
_SKIP_EXACT_NAMES = {
    "информация о контракте",
    "извещение о проведении электронного аукциона",
    "автоматический контроль",
    "!! в_помощь_участникам_закупок",
    "подписи заключивших контракт",
}
_SKIP_PREFIXES = (
    "печатная форма контракта",
    "печатная форма доп. соглашения",
    "печатная форма электронного контракта",
    "контракт с учетом доп. соглашений",
    "доп. соглашение",
    "электронный контракт",
    "результат контроля",
    "положительный результат контроля",
    "control99",
)
_SKIP_EXTENSIONS = {".xml", ".sig", ".p7s"}


def _should_skip_document_name(file_name: Optional[str]) -> bool:
    if not file_name:
        return False
    low = str(file_name).strip().lower()
    stem = low.rsplit(".", 1)[0] if "." in low else low
    if stem in _SKIP_EXACT_NAMES:
        return True
    if any(stem.startswith(p) for p in _SKIP_PREFIXES):
        return True
    return any(low.endswith(ext) for ext in _SKIP_EXTENSIONS)


def count_document_links(
    *,
    source_table: str,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
) -> int:
    """Count researchable physical download targets (worker skip-list applied)."""
    resolved = resolve_document_links(
        source_table=source_table,
        source_id=source_id,
        contract_number=contract_number,
        limit=10000,
    )
    links = resolved.get("links") or []
    keys = set()
    for row in links:
        if _should_skip_document_name(row.get("document_name")):
            continue
        phys = row.get("physical_download_key") or row.get("document_url")
        if phys:
            keys.add(str(phys))
    return len(keys)


def batch_count_document_links(
    rows: List[Dict[str, Any]]
) -> Dict[int, int]:
    """Batch count researchable physical download targets for a list of procurements."""
    by_table = {}
    for r in rows:
        tbl = links_table_for_source(r.get("source_table"))
        by_table.setdefault(tbl, []).append(r)

    results = {}
    try:
        conn = psycopg2.connect(**_s7_dsn())
        try:
            for tbl, tbl_rows in by_table.items():
                cns = [str(r["contract_number"]).strip() for r in tbl_rows if r.get("contract_number")]
                cids = [int(r["source_id"]) for r in tbl_rows if r.get("source_id") is not None]

                links = []
                if cns or cids:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        query = f"""
                            SELECT contract_id, contract_number, document_links, file_name
                            FROM {tbl}
                            WHERE (
                        """
                        clauses = []
                        params = []
                        if cns:
                            clauses.append("contract_number IN %s")
                            params.append(tuple(cns))
                        if cids:
                            clauses.append("contract_id IN %s")
                            params.append(tuple(cids))
                        query += " OR ".join(clauses)
                        query += """
                            )
                            AND (file_name IS NULL OR (
                                LOWER(TRIM(file_name)) NOT IN (
                                    'информация о контракте',
                                    'извещение о проведении электронного аукциона',
                                    'автоматический контроль',
                                    '!! в_помощь_участникам_закупок',
                                    'подписи заключивших контракт'
                                )
                                AND NOT (
                                    LOWER(TRIM(file_name)) LIKE 'печатная форма контракта%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'печатная форма доп. соглашения%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'печатная форма электронного контракта%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'контракт с учетом доп. соглашений%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'доп. соглашение%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'электронный контракт%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'результат контроля%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'положительный результат контроля%%'
                                    OR LOWER(TRIM(file_name)) LIKE 'control99%%'
                                )
                                AND NOT (
                                    LOWER(TRIM(file_name)) LIKE '%%.xml'
                                    OR LOWER(TRIM(file_name)) LIKE '%%.sig'
                                    OR LOWER(TRIM(file_name)) LIKE '%%.p7s'
                                )
                            ))
                        """
                        cur.execute(query, tuple(params))
                        links = cur.fetchall() or []

                links_by_cn = {}
                links_by_cid = {}
                for l in links:
                    cn = (l.get("contract_number") or "").strip()
                    cid = l.get("contract_id")
                    if cn:
                        links_by_cn.setdefault(cn, []).append(l)
                    if cid is not None:
                        links_by_cid.setdefault(int(cid), []).append(l)

                for r in tbl_rows:
                    pid = r["id"]
                    cn = (r.get("contract_number") or "").strip()
                    cid = r.get("source_id")

                    matched_links = []
                    if cn and cn in links_by_cn:
                        matched_links = links_by_cn[cn]
                    elif cid is not None and int(cid) in links_by_cid:
                        matched_links = links_by_cid[int(cid)]

                    keys = set()
                    for l in matched_links:
                        if _should_skip_document_name(l.get("file_name")):
                            continue
                        url = l.get("document_links")
                        phys = _physical_download_key(url) or url
                        if phys:
                            keys.add(str(phys))
                    results[pid] = len(keys)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("batch_count_document_links failed: %s", exc)
        for r in rows:
            results[r["id"]] = 0

    return results
