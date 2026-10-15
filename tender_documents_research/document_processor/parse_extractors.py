"""Parse-time extraction: estimates (tables) and project metadata (R4-PD).

Retention deletes raw files after 3 days, so everything we may ever need must be
extracted while the file is still on disk. This hook runs right after a document
is parsed and persists:
  * estimate material rows  -> structured_entities (MANUAL_PROOF_QUARANTINE)
  * project organizations / people -> project_metadata_* (raw + source_quote)
Fail-safe by design: any error is logged and never breaks parsing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("parse_extractors")


def _section_cells(quote: str) -> list:
    """Split a stored cell dump ("A=… | B=…") into bare cell texts.

    SECTION_LEVEL_NORMALIZATION_V1: the section detector must see the cell text
    without its column prefix so "Итого по главе N" / "Итого:" match.
    """
    out = []
    for part in str(quote or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if len(part) > 2 and part[1] == "=" and part[0].isupper():
            part = part[2:].strip()
        out.append(part)
    return out


def _estimate_layout(fact) -> str:
    """Value-provenance for an estimate row (mirrors the embedded contract)."""
    qty = getattr(fact, "quantity_value", None)
    price = getattr(fact, "unit_price_value", None)
    total = getattr(fact, "total_price_value", None)
    if qty is None or price is None or total is None:
        return "UNSUPPORTED_LAYOUT"
    computed = float(qty) * float(price)
    denom = max(abs(float(total)), abs(computed), 1.0)
    if abs(float(total) - computed) / denom > 0.05:
        return "INCONSISTENT_LAYOUT"
    return "CONSISTENT"


_DDL = (
    """CREATE TABLE IF NOT EXISTS project_metadata_organizations (
         id bigserial PRIMARY KEY,
         procurement_id bigint NOT NULL,
         organization_name_raw text NOT NULL,
         organization_role_raw text,
         document_name text,
         page_or_sheet text,
         source_quote text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT NOW()
       )""",
    """CREATE TABLE IF NOT EXISTS project_metadata_people (
         id bigserial PRIMARY KEY,
         procurement_id bigint NOT NULL,
         person_name_raw text NOT NULL,
         role_raw text,
         organization_name_raw text,
         document_name text,
         page_or_sheet text,
         source_quote text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT NOW()
       )""",
)


def _connect():
    from dotenv import load_dotenv

    load_dotenv("/opt/CRM_Streamlit/.env", override=True)
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
    )
    return conn


def _persist_estimate(conn, path: Path, procurement_id: int, document_name: str) -> int:
    from document_processor.smeta_forma_4b import detect_forma_4b, read_estimate, xlsx_sheet_names
    from document_processor.xlsx_table_reader import read_tables
    from document_processor.section_detector import (
        SECTION_RESIDUE,
        SectionTracker,
        is_aggregate_row,
        is_summarizable,
    )

    if detect_forma_4b(xlsx_sheet_names(path)):
        facts = read_estimate(path)
    else:
        facts = read_tables(path)
    if not facts:
        return 0
    # SECTION_LEVEL_NORMALIZATION_V1 (Phase 2): the xlsx estimate path is not
    # covered by embedded_extraction, so derive the deterministic section state
    # here over the reader rows (quote cells carry column A markers).
    _tracker = SectionTracker()
    _fact_section: Dict[int, Any] = {}
    for _fact in facts:
        _quote = str(getattr(_fact, "source_quote", "") or "")
        _sheet = getattr(_fact, "sheet", None) or getattr(_fact, "sheet_name", None)
        _code = _tracker.observe(
            str(_sheet) if _sheet else None, _section_cells(_quote), _quote
        )
        _name = getattr(_fact, "product_name_raw", None)
        _unit = getattr(_fact, "quantity_unit", None)
        _qty = getattr(_fact, "quantity_value", None)
        _tracker.add_child(
            _code,
            getattr(_fact, "total_price_value", None),
            summarizable=is_summarizable(
                layout_status=_estimate_layout(_fact),
                quantity_value=_qty,
                unit_normalized=_unit,
                name=_name,
            ),
            aggregate=is_aggregate_row(
                name=_name, unit_normalized=_unit, quantity_value=_qty
            ),
        )
        _fact_section[id(_fact)] = _code
    _tracker.finalize()
    cur = conn.cursor()
    cur.execute(
        "SELECT MIN(id) FROM document_match_details WHERE procurement_id=%s",
        (procurement_id,),
    )
    detail_id = cur.fetchone()[0]  # nullable; may be None when no match detail exists
    payload = json.dumps([getattr(f, "__dict__", {}) for f in facts], ensure_ascii=False, default=str)
    cur.execute(
        """INSERT INTO structured_extraction_runs
             (detail_id, procurement_id, category_code, document_name, page_or_sheet,
              source_text_snapshot, source_text_sha256, source_validator_name,
              source_validator_version, source_validation_method, extractor_name,
              extractor_version, extraction_method, prompt_version, model_name, status,
              created_at, completed_at, structured_fact_trust_state)
           VALUES (%s,%s,%s,%s,'sheet1',%s,%s,'PROVENANCE_CONTRACT','v1','PARSE_TIME',
                   'PARSE_TIME_READER','v1','DETERMINISTIC_TABLE_MAP','none','none','COMPLETED',
                   NOW(),NOW(),'MANUAL_PROOF_QUARANTINE')
           ON CONFLICT (detail_id, extractor_version) DO UPDATE
             SET source_text_snapshot = EXCLUDED.source_text_snapshot,
                 source_text_sha256 = EXCLUDED.source_text_sha256,
                 completed_at = NOW()
           RETURNING id""",
        (detail_id, procurement_id,
         getattr(facts[0], "category_code", "unknown"), document_name,
         payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()),
    )
    run_id = cur.fetchone()[0]
    saved = 0
    for fact in facts:
        name = getattr(fact, "product_name_raw", None)
        if not name:
            continue
        fingerprint = hashlib.sha256(
            f"{procurement_id}|{name}|{getattr(fact, 'row', '')}".encode("utf-8")
        ).hexdigest()
        _code = _fact_section.get(id(fact)) or SECTION_RESIDUE
        _info = _tracker.section(_code)
        cur.execute(
            """INSERT INTO structured_entities
                 (run_id, detail_id, procurement_id, category_code, entity_fingerprint,
                  entity_type, product_name_raw, product_name_normalized, quantity_value,
                  quantity_raw, quantity_unit_raw, quantity_unit_normalized,
                  unit_price_value, unit_price_raw, total_price_value, total_price_raw,
                  currency_code, source_quote, confidence, product_relation, created_at,
                  structured_fact_trust_state,
                  section_code, section_name, section_total_price_value,
                  section_total_price_raw, section_total_source)
               VALUES (%s,%s,%s,%s,%s,'PRODUCT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUB',%s,0.9,
                       'EMBEDDED',NOW(),'MANUAL_PROOF_QUARANTINE',
                       %s,%s,%s,%s,%s)
               ON CONFLICT ON CONSTRAINT uq_entity_run_fingerprint DO UPDATE SET
                   quantity_value = EXCLUDED.quantity_value,
                   unit_price_value = EXCLUDED.unit_price_value,
                   total_price_value = EXCLUDED.total_price_value,
                   total_price_raw = EXCLUDED.total_price_raw,
                   source_quote = EXCLUDED.source_quote,
                   section_code = EXCLUDED.section_code,
                   section_name = EXCLUDED.section_name,
                   section_total_price_value = EXCLUDED.section_total_price_value,
                   section_total_price_raw = EXCLUDED.section_total_price_raw,
                   section_total_source = EXCLUDED.section_total_source""",
            (run_id, detail_id, procurement_id, getattr(fact, "category_code", "unknown"),
             fingerprint, name, name, getattr(fact, "quantity_value", None),
             str(getattr(fact, "quantity_value", "")), getattr(fact, "quantity_unit", ""),
             getattr(fact, "quantity_unit", ""), getattr(fact, "unit_price_value", None),
             str(getattr(fact, "unit_price_value", "")), getattr(fact, "total_price_value", None),
             str(getattr(fact, "total_price_value", "")), getattr(fact, "source_quote", ""),
             _code, (_info.name if _info else None),
             (_info.total_value if _info else None), (_info.total_raw if _info else None),
             (_info.total_source if _info else None)),
        )
        saved += 1
    return saved


def _persist_metadata(conn, text: str, procurement_id: int, document_name: str) -> int:
    from document_processor.project_metadata_reader import scan_lines

    hits = scan_lines((text or "").splitlines())
    if not hits:
        return 0
    cur = conn.cursor()
    saved = 0
    for hit in hits:
        if hit.kind == "PERSON":
            cur.execute(
                """INSERT INTO project_metadata_people
                     (procurement_id, person_name_raw, role_raw, document_name, source_quote)
                   VALUES (%s,%s,%s,%s,%s)""",
                (procurement_id, hit.raw_value, hit.role_bucket, document_name, hit.source_quote),
            )
        else:
            cur.execute(
                """INSERT INTO project_metadata_organizations
                     (procurement_id, organization_name_raw, organization_role_raw,
                      document_name, source_quote)
                   VALUES (%s,%s,%s,%s,%s)""",
                (procurement_id, hit.raw_value, hit.role_bucket, document_name, hit.source_quote),
            )
        saved += 1
    return saved


def extract_and_persist(
    path: Any,
    text: Optional[str],
    procurement_id: Optional[int],
    document_name: Optional[str] = None,
    *,
    category_code: Optional[str] = None,
    source_document_id: Optional[int] = None,
    physical_key: Optional[str] = None,
    line_meta: Optional[Dict[int, Any]] = None,
    track: Optional[str] = None,
) -> Dict[str, int]:
    """Best-effort parse-time extraction; never raises.

    `category_code` (from the Queue V3 payload) enables EMBEDDED_EXTRACTOR_V1 +
    UNIT_NORMALIZER_V1 while the file is still on disk. Category is never
    re-derived from the text.
    """
    result = {"facts": 0, "metadata": 0, "embedded": 0}
    if procurement_id is None:
        return result
    try:
        path = Path(path)
        name = document_name or path.name
        conn = _connect()
        try:
            conn.cursor().execute("SELECT 1")
            for statement in _DDL:
                conn.cursor().execute(statement)
            conn.commit()
            # Each extractor is isolated: one failing must not block the others.
            # When a Queue V3 category context is present the new extractor
            # supersedes the legacy estimate reader (avoids reading big xlsx twice).
            if path.suffix.lower() in (".xlsx", ".xlsm") and not category_code:
                try:
                    result["facts"] = _persist_estimate(conn, path, int(procurement_id), name)
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    logger.warning("estimate extraction failed for %s: %s", name, exc)
            if text:
                try:
                    result["metadata"] = _persist_metadata(conn, text, int(procurement_id), name)
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    logger.warning("metadata extraction failed for %s: %s", name, exc)
            if category_code:
                result["embedded"] = _persist_embedded(
                    conn, path, text, line_meta, int(procurement_id), name,
                    category_code, source_document_id, physical_key, track,
                )
                try:
                    from document_processor.embedded_persistence import record_outcome

                    record_outcome(
                        conn,
                        source_document_id=source_document_id,
                        procurement_id=int(procurement_id),
                        category_code=category_code,
                        track=track,
                        document_name=name,
                        outcome="FACTS_FOUND" if result.get("embedded") else "NO_FACTS",
                        facts_found=int(result.get("embedded") or 0),
                        reason="parse_time_hook",
                        files_parsed=1,
                    )
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()
        if result["facts"] or result["metadata"] or result.get("embedded"):
            logger.info(
                "parse-time extraction: facts=%d metadata=%d embedded=%d doc=%s",
                result["facts"], result["metadata"], result.get("embedded", 0), name,
            )
    except Exception as exc:
        logger.warning("parse-time extraction failed for %s: %s", document_name, exc)
    return result


def _persist_embedded(
    conn,
    path: Path,
    text: Optional[str],
    line_meta: Optional[Dict[int, Any]],
    procurement_id: int,
    document_name: str,
    category_code: str,
    source_document_id: Optional[int],
    physical_key: Optional[str],
    track: Optional[str] = None,
) -> int:
    """Run the category-bound extractor during parsing (file still on disk)."""
    try:
        from document_processor.embedded_extraction import extract_facts, facts_from_table_rows
        from document_processor.embedded_persistence import persist_facts

        # DIRECT (прямые поставки) uses the previously built template extractor;
        # EMBEDDED (проекты/объекты) uses the table-row extractor.
        if track == "DIRECT":
            from document_processor.direct_runtime import direct_facts

            facts = direct_facts(
                path, procurement_id=procurement_id, category_code=category_code,
                document_name=document_name, source_document_id=source_document_id,
                physical_key=physical_key,
            )
            if not facts:
                return 0
            created, _reused, _stats = persist_facts(
                conn, procurement_id=procurement_id, document_name=document_name,
                category_code=category_code, facts=facts,
            )
            return created

        # Bounded work: one pathological workbook must not stall the batch.
        max_xlsx_bytes = int(os.getenv("EMBEDDED_MAX_XLSX_BYTES", str(8 * 1024 * 1024)))
        if path.suffix.lower() in (".xlsx", ".xlsm") and path.stat().st_size > max_xlsx_bytes:
            logger.warning(
                "embedded extraction skipped (xlsx over %d bytes): %s", max_xlsx_bytes, document_name
            )
            return 0
        if path.suffix.lower() in (".xlsx", ".xlsm"):
            try:
                from document_processor.smeta_forma_4b import (
                    detect_forma_4b,
                    read_estimate,
                    xlsx_sheet_names,
                )
                from document_processor.xlsx_table_reader import read_tables

                rows = read_estimate(path) if detect_forma_4b(xlsx_sheet_names(path)) else read_tables(path)
            except Exception:
                rows = []
            facts = facts_from_table_rows(
                procurement_id=procurement_id, category_code=category_code,
                document_name=document_name, rows=rows,
                source_document_id=source_document_id, physical_key=physical_key,
            )
        else:
            facts = extract_facts(
                procurement_id=procurement_id, category_code=category_code,
                document_name=document_name, text=text, line_meta=line_meta,
                source_document_id=source_document_id, physical_key=physical_key,
            )
        if not facts:
            return 0
        created, _reused, _stats = persist_facts(
            conn, procurement_id=procurement_id, document_name=document_name,
            category_code=category_code, facts=facts,
        )
        return created
    except Exception as exc:  # never break parsing
        logger.warning("embedded extraction failed for %s: %s", document_name, exc)
        return 0
