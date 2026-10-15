"""Document/structured-fact readers for the commercial portal (read-only).

WIP=COMMERCIAL_SITE_CRM_LINK_V1.  Every connection is opened read-only; this
module never writes to CRM or document_intelligence.

Authority boundaries:
  * ``structured_entities`` / ``structured_attributes`` - material lines,
    technical attributes and documentary provenance
    (trust state ``TRUSTED_PRODUCTION`` only);
  * ``confirmed_category_facts`` - document-confirmed per-category value.
    The CRM runtime role has no SELECT grant on this table today, so the reader
    reports ``NO_SELECT_GRANT`` and the caller exposes ``null`` instead of
    inventing a value.

Missing value is ``None``; zeros are never synthesised.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras

MATERIALS_SAMPLE_SIZE = 12
MAX_EVIDENCE_ROWS = 200

STATUS_OK = "CONFIRMED_CATEGORY_FACTS"
STATUS_NO_ROWS = "NO_CONFIRMED_FACTS"
STATUS_NO_GRANT = "NO_SELECT_GRANT"
STATUS_ERROR = "QUERY_ERROR"


def crm_kwargs() -> Dict[str, Any]:
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    return dict(require_crm_db_connect_kwargs())


def di_kwargs() -> Dict[str, Any]:
    kw = crm_kwargs()
    kw["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kw["connect_timeout"] = int(os.getenv("COMMERCIAL_PORTAL_DB_TIMEOUT", "10"))
    return kw


def connect(kwargs: Dict[str, Any]):
    conn = psycopg2.connect(**kwargs)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "quantize"):  # Decimal
        return float(value)
    return value


def clean_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: jsonable(v) for k, v in row.items()}


def load_materials(procurement_id: int) -> Dict[str, Dict[str, Any]]:
    """Trusted material lines per category: value, counts, samples, attributes."""
    result: Dict[str, Dict[str, Any]] = {}
    try:
        with connect(di_kwargs()) as conn:
            totals = query(conn, _MATERIAL_TOTALS_SQL, (procurement_id,))
            attributes = query(conn, _TECH_ATTRIBUTES_SQL, (procurement_id,))
            samples = query(conn, _MATERIAL_SAMPLE_SQL,
                            (procurement_id, MATERIALS_SAMPLE_SIZE))
    except psycopg2.Error:
        return {}

    for r in totals:
        result[str(r["category_code"])] = {
            "source": "TRUSTED_STRUCTURED_ENTITIES",
            "materials_count": int(r["materials_count"] or 0),
            "material_value": jsonable(r["material_value"]),
            "material_value_status": ("PRESENT" if r["material_value"] is not None
                                      else "NOT_AVAILABLE"),
            "material_lines": int(r["material_lines"] or 0),
            "evidence_count": int(r["source_documents"] or 0),
            "technical_attributes_count": 0,
            "materials_sample": [],
            "manufacturers_sample": [],
            "brands_sample": [],
        }
    for r in attributes:
        result.setdefault(str(r["category_code"]), _empty_entry())[
            "technical_attributes_count"] = int(r["technical_attributes_count"] or 0)
    for s in samples:
        bucket = result.setdefault(str(s["category_code"]), _empty_entry())
        bucket["materials_sample"].append({
            "material_name": s["product_name"],
            "quantity": jsonable(s["quantity_value"]),
            "unit": s["unit"],
            "unit_price": jsonable(s["unit_price_value"]),
            "line_total": jsonable(s["total_price_value"]),
        })
        if s["manufacturer"] and s["manufacturer"] not in bucket["manufacturers_sample"]:
            bucket["manufacturers_sample"].append(s["manufacturer"])
        if s["brand"] and s["brand"] not in bucket["brands_sample"]:
            bucket["brands_sample"].append(s["brand"])
    for bucket in result.values():
        bucket["manufacturers_sample"] = bucket["manufacturers_sample"][:MATERIALS_SAMPLE_SIZE]
        bucket["brands_sample"] = bucket["brands_sample"][:MATERIALS_SAMPLE_SIZE]
    return result


def load_confirmed_values(procurement_id: int) -> Tuple[Dict[str, Dict[str, Any]], str]:
    """Document-confirmed per-category value from ``confirmed_category_facts``.

    Returns ``(values, status)`` so a caller can state *why* a value is missing
    instead of presenting an unexplained ``null``.
    """
    try:
        with connect(di_kwargs()) as conn:
            rows = query(conn, _CONFIRMED_FACTS_SQL, (procurement_id,))
    except psycopg2.errors.InsufficientPrivilege:
        return {}, STATUS_NO_GRANT
    except psycopg2.Error:
        return {}, STATUS_ERROR
    if not rows:
        return {}, STATUS_NO_ROWS
    return {
        str(r["category_code"]): {
            "source": STATUS_OK,
            "facts_count": int(r["facts_count"] or 0),
            "materials_count": int(r["materials_count"] or 0),
            "section_value": jsonable(r["section_value"]),
        }
        for r in rows
    }, STATUS_OK


def load_evidence_rows(procurement_id: int) -> List[Dict[str, Any]]:
    """Documentary provenance: one row per category x source document."""
    try:
        with connect(di_kwargs()) as conn:
            rows = query(conn, _EVIDENCE_ROWS_SQL, (procurement_id, MAX_EVIDENCE_ROWS))
    except psycopg2.Error:
        return []
    return [clean_row(r) for r in rows]


def _empty_entry() -> Dict[str, Any]:
    return {
        "source": "TRUSTED_STRUCTURED_ENTITIES", "materials_count": 0,
        "material_value": None, "material_value_status": "NOT_AVAILABLE",
        "material_lines": 0, "evidence_count": 0,
        "technical_attributes_count": 0, "materials_sample": [],
        "manufacturers_sample": [], "brands_sample": [],
    }


_MATERIAL_TOTALS_SQL = """
SELECT category_code,
       count(DISTINCT product_name)       AS materials_count,
       sum(total_price_value)             AS material_value,
       count(*)                           AS material_lines,
       count(DISTINCT source_document_id) AS source_documents
  FROM (
    SELECT e.category_code, e.id, e.total_price_value, e.source_document_id,
           coalesce(e.product_name_raw, e.product_name_normalized) AS product_name
      FROM structured_entities e
     WHERE e.procurement_id = %s
       AND e.structured_fact_trust_state = 'TRUSTED_PRODUCTION'
  ) t GROUP BY category_code
"""

_TECH_ATTRIBUTES_SQL = """
SELECT e.category_code, count(DISTINCT a.id) AS technical_attributes_count
  FROM structured_entities e
  JOIN structured_attributes a ON a.entity_id = e.id
 WHERE e.procurement_id = %s
   AND e.structured_fact_trust_state = 'TRUSTED_PRODUCTION'
 GROUP BY e.category_code
"""

_MATERIAL_SAMPLE_SQL = """
SELECT category_code, product_name, quantity_value, unit, unit_price_value,
       total_price_value, manufacturer, brand
  FROM (
    SELECT e.category_code,
           coalesce(e.product_name_raw, e.product_name_normalized) AS product_name,
           e.quantity_value, e.quantity_unit_normalized AS unit,
           e.unit_price_value, e.total_price_value,
           e.manufacturer_normalized AS manufacturer,
           e.brand_normalized AS brand,
           row_number() OVER (PARTITION BY e.category_code
                              ORDER BY e.total_price_value DESC NULLS LAST, e.id) AS rn
      FROM structured_entities e
     WHERE e.procurement_id = %s
       AND e.structured_fact_trust_state = 'TRUSTED_PRODUCTION'
       AND coalesce(e.product_name_raw, e.product_name_normalized) IS NOT NULL
  ) s
 WHERE rn <= %s
 ORDER BY category_code, rn
"""

_CONFIRMED_FACTS_SQL = """
SELECT category_code,
       count(*)::bigint                    AS facts_count,
       count(DISTINCT material_normalized) AS materials_count,
       sum(line_total_value)               AS section_value
  FROM confirmed_category_facts
 WHERE procurement_id = %s
 GROUP BY category_code
"""

_EVIDENCE_ROWS_SQL = """
SELECT e.category_code,
       e.source_document_id,
       e.physical_download_key,
       count(*)                        AS material_lines,
       min(e.page_or_sheet)            AS page_sample,
       min(e.quantity_unit_normalized) AS unit_sample
  FROM structured_entities e
 WHERE e.procurement_id = %s
   AND e.structured_fact_trust_state = 'TRUSTED_PRODUCTION'
 GROUP BY 1, 2, 3
 ORDER BY 1, 2
 LIMIT %s
"""
