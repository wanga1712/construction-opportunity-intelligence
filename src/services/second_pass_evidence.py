"""Second Pass evidence selector (MEDAL SEMANTICS V2).

Extracts and normalizes the top document evidence snippets used as Second Pass
model input. Moved verbatim out of ``second_pass_service`` to keep that module
within the project size budget; behaviour is unchanged. Evidence is read from
the existing ``document_files`` / ``document_matches`` / ``document_match_details``
tables вЂ” nothing is re-downloaded or re-parsed.

Part of ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1 (PHASE 6.4).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_EVIDENCE_SNIPPETS = 15
MAX_EVIDENCE_CHARS_PER_SNIPPET = 250


def _format_row_data(row_data: Any) -> Tuple[str, Optional[Any], Optional[Any], Optional[Any]]:
    """Cleanly extract human-readable text, qty, unit, price from row_data."""
    if not isinstance(row_data, dict):
        return str(row_data)[:MAX_EVIDENCE_CHARS_PER_SNIPPET].strip(), None, None, None

    val = row_data.get("values") or {}
    name = val.get("name") or val.get("raw_text") or val.get("text")
    qty = val.get("qty")
    unit = val.get("unit")
    price = val.get("price")

    if not name:
        raw_cells = row_data.get("raw_cells") or []
        texts = [c.get("text") for c in raw_cells if isinstance(c, dict) and c.get("text")]
        name = " ".join(texts) if texts else (str(val)[:120] if val else str(row_data)[:120])

    parts = [f"Name: {name}"]
    if qty:
        parts.append(f"Qty: {qty} {unit or ''}".strip())
    if price:
        parts.append(f"Price: {price}")
    return " | ".join(parts)[:MAX_EVIDENCE_CHARS_PER_SNIPPET], qty, unit, price


def extract_evidence_snippets(di_conn, procurement_id: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Extract and normalize top evidence snippets for Second Pass LLM analysis."""
    # Lazy import: ``normalize_category_code`` lives in second_pass_service, which
    # imports this module, so a module-level import would be circular.
    from src.services.second_pass_service import normalize_category_code
    doc_stats = {"document_count": 0, "processed_document_count": 0, "evidence_count": 0, "document_types": ""}
    with di_conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                COUNT(DISTINCT f.id) as document_count,
                COUNT(DISTINCT CASE WHEN f.download_status = 'COMPLETED' THEN f.id END) as processed_document_count,
                COUNT(d.id) as evidence_count,
                STRING_AGG(DISTINCT f.content_type, ', ') as document_types
            FROM document_files f
            LEFT JOIN document_matches m ON m.file_id = f.id
            LEFT JOIN document_match_details d ON d.match_id = m.id
            WHERE f.procurement_id = %s
            """,
            (procurement_id,),
        )
        row = cur.fetchone()
        if row:
            doc_stats = {
                "document_count": row[0] or 0,
                "processed_document_count": row[1] or 0,
                "evidence_count": row[2] or 0,
                "document_types": row[3] or "",
            }

        cur.execute(
            """
            SELECT 
                d.id as detail_id,
                d.category_code,
                d.subcategory_code,
                d.matched_term,
                d.score,
                COALESCE(d.page_or_sheet || ':' || d.row_number, d.page_or_sheet, 'text') as location,
                d.row_data,
                f.file_name
            FROM document_match_details d
            JOIN document_matches m ON m.id = d.match_id
            JOIN document_files f ON f.id = m.file_id
            WHERE m.procurement_id = %s
            ORDER BY d.score DESC, d.id ASC
            LIMIT 50
            """,
            (procurement_id,),
        )
        detail_rows = cur.fetchall()

    seen_signatures = set()
    snippets = []
    for r in detail_rows:
        text, qty, unit, price = _format_row_data(r[6])
        term = r[3] or ""
        doc_name = r[7] or "Unknown_doc"
        sig = f"{term.lower()}|{text[:60].lower()}"
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        snippets.append({
            "detail_id": r[0],
            "category_code": normalize_category_code(r[1] or "other_unmapped"),
            "subcategory_code": r[2],
            "matched_term": term,
            "score": float(r[4] or 0.0),
            "location": r[5] or "text",
            "document_name": doc_name,
            "text": text,
            "qty": qty,
            "unit": unit,
            "price": price,
        })
        if len(snippets) >= MAX_EVIDENCE_SNIPPETS:
            break

    return snippets, doc_stats
