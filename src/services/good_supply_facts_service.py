"""GOOD_SUPPLY_FACTS_V1 — чистый слой «что можно поставить».

Источник — resolved `structured_estimate_rows`, с `structured_entities` как
fallback для DIRECT/legacy. Сырые `document_match_details` остаются evidence.
Оставляем реальные ТОВАРНЫЕ/материальные факты:

  * `category_code` заполнен (не `unknown`);
  * `classify_fact_kind(...) == GOODS` (работы отсекаются);
  * не агрегатная строка («Итого/Всего/Стоимость/НДС/Раздел/Глава»);
  * `quantity_value` и `quantity_unit_normalized` заполнены;
  * `total_price_value` заполнен;
  * `source_quote` непустой;
  * `section_code` — если есть, иначе `RESIDUE`.

Модуль read-only: никуда не пишет и не трогает scoring/medal/queue.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from src.services.works_vs_goods_service import classify_fact_kind

RESIDUE = "RESIDUE"
COUNT_UNITS = frozenset(
    {"PCS", "UNIT", "SET", "PACK", "ROLL", "BAG", "SHEET", "PAIR"}
)
BULK_TARGET_CATEGORIES = frozenset(
    {
        "composite_structures",
        "structural_reinforcement",
        "drainage_water_management",
        # Floor coverings are legitimately sold in square metres and rolls;
        # M2 must not be treated as an aggregate-material veto.
        "flooring",
    }
)
BULK_UNITS = frozenset({"M", "POG_M", "KG", "T", "M2"})
_UNIT_ALIASES = {
    "М": "M",
    "М2": "M2",
    "М²": "M2",
    "М^2": "M2",
    "КВ.М": "M2",
    "КВ М": "M2",
    "ПОГ.М": "POG_M",
    "ПОГ М": "POG_M",
    "П.М": "POG_M",
    "ПМ": "POG_M",
    "ШТ": "PCS",
    "КОМПЛ": "SET",
    "УПАК": "PACK",
    "КГ": "KG",
    "Т": "T",
}
#: агрегатные/шапочные строки — не товар
_AGGREGATE_RE = re.compile(r"^\s*(итого|всего|стоимость|ндс|раздел|глава|\d+(?:\.\d+)*\s+\S)", re.IGNORECASE)
_BULK_NEGATIVE_RE = re.compile(
    r"(?<!\w)(?:"
    r"бетон\w*|песок|песчан\w*|щебен\w*|щебн\w*|грунт\w*|удобрен\w*|"
    r"стал\w*|стальн\w*|арматурные заготовки|"
    r"каркасы и сетки арматурные|арматура стальная|А400|А500С"
    r")(?!\w)",
    re.IGNORECASE,
)

DEFAULT_LIMIT = 300

#: Estimate rows are the primary object/project source. Entity rows remain as
#: a compatibility fallback for DIRECT supply and pre-universal records.
_GOOD_SUPPLY_ROWS_SQL = """
WITH candidates AS (
    SELECT r.procurement_id, r.source_document_id,
           coalesce(nullif(r.source_identity, ''), '') AS source_identity,
           coalesce(r.row_ref, '') AS row_or_line,
           r.name_raw AS product_name_raw,
           coalesce(r.name_normalized, r.name_raw) AS product_name_normalized,
           NULL::text AS manufacturer_normalized,
           NULL::text AS brand_normalized,
           NULL::text AS model_article_normalized,
           r.quantity_value, r.unit_raw AS quantity_unit_raw,
           r.unit_normalized AS quantity_unit_normalized,
           r.unit_price_value, r.total_value AS total_price_value,
           'EMBEDDED'::text AS product_relation,
           r.source_quote, r.sheet_or_page AS page_or_sheet,
           r.layout_status, 0.9::numeric AS confidence,
           'ESTIMATE_ROW_RESOLVED'::text AS structured_fact_trust_state,
           r.extractor_version, NULL::text AS physical_download_key,
           NULL::text AS section_code, NULL::text AS section_name,
           NULL::numeric AS section_total_price_value,
           NULL::text AS section_total_price_raw,
           NULL::text AS section_total_source,
           'PRODUCT'::text AS entity_type, r.category_code,
           r.subcategory_code,
           COALESCE((
             SELECT jsonb_agg(jsonb_build_object(
                      'name', a->>'attribute_name',
                      'name_normalized', a->>'attribute_name_normalized',
                      'raw_value', a->>'raw_value',
                      'normalized_value', a->>'normalized_value',
                      'numeric_value', (a->>'numeric_value')::numeric,
                      'unit', coalesce(a->>'unit_normalized', a->>'unit_raw'))
                    ORDER BY ordinality)
               FROM jsonb_array_elements(r.technical_attributes)
                    WITH ORDINALITY AS attrs(a, ordinality)
             ), '[]'::jsonb) AS attributes,
           0 AS source_priority, r.id AS source_id
      FROM structured_estimate_rows r
     WHERE r.procurement_id = ANY(%s)
       AND r.category_code IS NOT NULL
       AND coalesce(r.subcategory_code, '') <> ''
       AND r.quantity_value IS NOT NULL
       AND coalesce(r.unit_normalized, '') <> ''
       AND coalesce(r.source_quote, '') <> ''
       AND r.source_quote !~ 'ТЦ_'
    UNION ALL
    SELECT se.procurement_id, se.source_document_id,
           coalesce(
               nullif(se.physical_download_key, ''),
               se.source_document_id::text,
               ''
           ) AS source_identity,
           coalesce(se.row_or_line, ''), se.product_name_raw,
           se.product_name_normalized, se.manufacturer_normalized,
           se.brand_normalized, se.model_article_normalized,
           se.quantity_value, se.quantity_unit_raw,
           se.quantity_unit_normalized, se.unit_price_value,
           se.total_price_value, se.product_relation, se.source_quote,
           se.page_or_sheet, se.layout_status, se.confidence,
           se.structured_fact_trust_state, se.extractor_version,
           se.physical_download_key, se.section_code, se.section_name,
           se.section_total_price_value, se.section_total_price_raw,
           se.section_total_source, se.entity_type, se.category_code,
           se.subcategory_code,
           COALESCE((
             SELECT jsonb_agg(jsonb_build_object(
                      'name', a.attribute_name,
                      'name_normalized', a.attribute_name_normalized,
                      'raw_value', a.raw_value,
                      'normalized_value', a.normalized_value,
                      'numeric_value', a.numeric_value,
                      'unit', a.unit_normalized)
                    ORDER BY a.id)
               FROM structured_attributes a WHERE a.entity_id = se.id
             ), '[]'::jsonb),
           1, se.id
      FROM structured_entities se
     WHERE se.procurement_id = ANY(%s)
       AND se.entity_type = 'PRODUCT'
       AND coalesce(se.category_code, '') NOT IN ('', 'unknown')
       AND coalesce(se.subcategory_code, '') <> ''
       AND se.quantity_value IS NOT NULL
       AND coalesce(se.quantity_unit_normalized, '') <> ''
       AND coalesce(se.source_quote, '') <> ''
),
preferred AS (
    SELECT c.*,
           row_number() OVER (
               PARTITION BY c.procurement_id, c.source_document_id,
                            c.row_or_line, coalesce(c.product_name_raw, '')
               ORDER BY c.source_priority, (c.section_code IS NOT NULL) DESC,
                        c.source_id DESC
           ) AS pref_rn
      FROM candidates c
)
SELECT procurement_id, category_code, subcategory_code, entity_type,
       product_name_raw, product_name_normalized,
       manufacturer_normalized, brand_normalized, model_article_normalized,
       quantity_value, quantity_unit_raw, quantity_unit_normalized,
       unit_price_value, total_price_value, product_relation,
       source_quote, row_or_line, page_or_sheet, layout_status, confidence,
       structured_fact_trust_state, extractor_version, physical_download_key,
       section_code, section_name, section_total_price_value,
       section_total_price_raw, section_total_source, source_document_id,
       source_identity, attributes
  FROM preferred
 WHERE pref_rn = 1
 ORDER BY total_price_value DESC NULLS LAST, source_priority, source_id
"""


def _di_conn():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kwargs = dict(require_crm_db_connect_kwargs())
    kwargs["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kwargs.setdefault("connect_timeout", 8)
    return psycopg2.connect(**kwargs)


def _is_aggregate(name: Any) -> bool:
    return bool(_AGGREGATE_RE.match(str(name or "")))


def _fractional_count_quantity(row: Dict[str, Any]) -> bool:
    unit = str(row.get("quantity_unit_normalized") or "").upper()
    if unit not in COUNT_UNITS or row.get("quantity_value") is None:
        return False
    try:
        quantity = float(row["quantity_value"])
    except (TypeError, ValueError):
        return True
    return not math.isclose(quantity, round(quantity), rel_tol=0.0, abs_tol=1e-9)


def _bulk_material_reason(row: Dict[str, Any], name: Any) -> Optional[str]:
    unit = str(row.get("quantity_unit_normalized") or "").upper()
    category = str(row.get("category_code") or "").strip()
    if unit in COUNT_UNITS:
        return None
    if category not in BULK_TARGET_CATEGORIES or unit not in BULK_UNITS:
        return "bulk_material"
    if _BULK_NEGATIVE_RE.search(str(name or "")):
        return "bulk_material"
    try:
        if float(row.get("quantity_value")) <= 0:
            return "no_quantity"
    except (TypeError, ValueError):
        return "no_quantity"
    return None


def canonical_unit(*values: Any) -> str:
    """Canonicalize persisted RU/OCR unit tokens."""
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip().upper()
        if not text:
            continue
        normalized = _UNIT_ALIASES.get(text)
        if normalized:
            return normalized
        if text.rstrip(".") in {"ШТ", "ШТУК", "ШТУКА"}:
            return "PCS"
        if text.rstrip(".") in {"ЕД", "ЕДИНИЦА"}:
            return "UNIT"
        if text in BULK_UNITS or text in COUNT_UNITS:
            return text
    return ""


_QUOTE_ROW_REF_RE = re.compile(
    r"^\s*(A\s*=\s*[^|]+(?:\|\s*B\s*=\s*[^|]+)?)",
    re.IGNORECASE,
)


def _canonical_row_ref(row: Dict[str, Any]) -> str:
    quoted = _QUOTE_ROW_REF_RE.match(
        str(row.get("source_quote") or "")
    )
    if quoted:
        return re.sub(r"\s+", " ", quoted.group(1)).strip().lower()
    explicit = re.sub(
        r"\s+",
        " ",
        str(row.get("row_or_line") or "").strip(),
    )
    if explicit:
        return explicit.lower()
    return ""


def _dedupe_supply_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Canonicalize units and collapse exact repeated source-coordinate rows.

    Companion estimate workbooks often repeat the same row coordinate and
    verbatim quote. Keep those copies once for counts and sums, while retaining
    the source-document IDs for provenance. Similar-looking rows without an
    exact coordinate/quote/value match remain separate.
    """
    out: List[Dict[str, Any]] = []
    seen: dict[tuple, int] = {}
    for source_row in rows:
        row = dict(source_row)
        canonical = canonical_unit(
            row.get("quantity_unit_raw"),
            row.get("quantity_unit_normalized"),
        )
        row["quantity_unit_normalized"] = canonical or str(
            row.get("quantity_unit_normalized")
            or row.get("quantity_unit_raw")
            or ""
        ).strip()
        name = re.sub(
            r"\s+",
            " ",
            str(
                row.get("product_name_normalized")
                or row.get("product_name_raw")
                or ""
            ).strip().lower(),
        )
        identity = str(
            row.get("source_identity")
            or row.get("source_document_id")
            or ""
        ).strip().lower()
        row_ref = _canonical_row_ref(row)
        try:
            quantity: Any = round(float(row.get("quantity_value")), 12)
        except (TypeError, ValueError):
            quantity = row.get("quantity_value")
        quote = re.sub(r"\s+", " ", str(row.get("source_quote") or "")).strip()
        unit = str(row.get("quantity_unit_normalized") or "").strip().upper()
        try:
            unit_price: Any = round(float(row.get("unit_price_value")), 8)
        except (TypeError, ValueError):
            unit_price = row.get("unit_price_value")
        try:
            total: Any = round(float(row.get("total_price_value")), 2)
        except (TypeError, ValueError):
            total = row.get("total_price_value")
        # Coordinates are local to a document. Cross-document collapse is
        # allowed only when the full quote and all commercial fields match.
        # Without a reliable row coordinate, retain the source identity.
        if row_ref and quote:
            identity_key = (
                "COORD", row_ref, quote, name, quantity, unit,
                unit_price, total, row.get("category_code"),
                row.get("subcategory_code"),
            )
        elif name and quantity is not None and unit and total is not None:
            # Companion estimate workbooks often repeat the same position under
            # different files/source identities. Exact commercial identity wins
            # over the document identity for counts and sums.
            identity_key = (
                "VALUE", name, quantity, unit, unit_price, total,
                row.get("category_code"), row.get("subcategory_code"),
            )
        else:
            identity_key = ("DOC", identity, row_ref, name, quantity)
        key = (int(row.get("procurement_id") or 0), *identity_key)
        if key in seen:
            existing_index = seen[key]
            existing = out[existing_index]
            source_ids = set(existing.get("duplicate_source_document_ids") or [])
            if existing.get("source_document_id") is not None:
                source_ids.add(existing["source_document_id"])
            if row.get("source_document_id") is not None:
                source_ids.add(row["source_document_id"])
            existing["duplicate_source_document_ids"] = sorted(
                source_ids, key=str
            )
            existing["duplicate_source_count"] = len(source_ids)
            if (
                not str(existing.get("quantity_unit_normalized") or "")
                and str(row.get("quantity_unit_normalized") or "")
            ):
                out[existing_index] = row
            continue
        seen[key] = len(out)
        out.append(row)
    return out


def classify_supply_row(row: Dict[str, Any]) -> Optional[str]:
    """Почему строка НЕ идёт в «что можно поставить» (или None, если годится)."""
    row = dict(row)
    row["quantity_unit_normalized"] = canonical_unit(
        row.get("quantity_unit_raw"),
        row.get("quantity_unit_normalized"),
    )
    if not str(row.get("source_quote") or "").strip():
        return "no_quote"
    category = str(row.get("category_code") or "").strip()
    if not category or category == "unknown":
        return "no_category"
    name = row.get("product_name_normalized") or row.get("product_name_raw")
    if classify_fact_kind(entity_type=row.get("entity_type"), name=name) != "GOODS":
        return "work"
    if _is_aggregate(name):
        return "aggregate"
    if row.get("quantity_value") is None or not str(row.get("quantity_unit_normalized") or "").strip():
        return "no_quantity"
    bulk_reason = _bulk_material_reason(row, name)
    if bulk_reason:
        return bulk_reason
    if (
        str(row.get("quantity_unit_normalized") or "").upper() in COUNT_UNITS
        and _fractional_count_quantity(row)
    ):
        return "no_quantity"
    if row.get("total_price_value") is None:
        return "no_total"
    return None


def load_good_supply_rows(conn: Any, procurement_ids: List[int] | tuple[int, ...] | set[int]) -> List[Dict[str, Any]]:
    """Load unified estimate-row/entity candidates from document DB."""
    ids = sorted({int(pid) for pid in procurement_ids if pid})
    if not ids:
        return []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(_GOOD_SUPPLY_ROWS_SQL, (ids, ids))
        return _dedupe_supply_rows(
            [dict(row) for row in cur.fetchall()]
        )


def count_material_facts_by_category(
    procurement_ids: List[int] | tuple[int, ...] | set[int],
    *,
    conn: Any,
) -> Dict[tuple[int, str], int]:
    """Count factual goods materials by ``(procurement_id, category_code)``.

    Raw matcher rows are intentionally excluded. A material is counted only when
    it is a preferred ``structured_entities`` PRODUCT with quantity, unit and
    source quote, and is classified as GOODS rather than WORK/aggregate.
    """
    ids = sorted({int(pid) for pid in procurement_ids if pid})
    if not ids:
        return {}
    counts: Dict[tuple[int, str], int] = {}
    for row in load_good_supply_rows(conn, ids):
        category = str(row.get("category_code") or "").strip()
        name = row.get("product_name_normalized") or row.get("product_name_raw")
        if not category or category == "unknown":
            continue
        if classify_fact_kind(entity_type=row.get("entity_type"), name=name) != "GOODS":
            continue
        if _bulk_material_reason(row, name):
            continue
        if _is_aggregate(name) or _fractional_count_quantity(row):
            continue
        key = (int(row["procurement_id"]), category)
        counts[key] = counts.get(key, 0) + 1
    return counts


def to_flat_fact(row: Dict[str, Any]) -> Dict[str, Any]:
    """Плоский материалоцентричный факт (GOOD_SUPPLY_FACTS_V1, приоритет вывода).

    Главное — материал и его атрибуты; раздел (`section_name`) идёт лёгкой пометкой
    «найдено в разделе» и НЕ блокирует вывод (в т.ч. при отсутствии/ненадёжности
    section total). Старые ключи сохраняются для совместимости рендера экранов.
    """
    section = str(row.get("section_code") or "").strip()
    section_name = row.get("section_name")
    if not section or section.upper().startswith(RESIDUE):
        section, section_name = RESIDUE, None
    material = row.get("product_name_normalized") or row.get("product_name_raw")
    unit = row.get("quantity_unit_normalized") or row.get("quantity_unit_raw")
    return {
        # — плоский набор карточки —
        "material": material,
        "quantity": row.get("quantity_value"),
        "unit": unit,
        "unit_price": row.get("unit_price_value"),
        "total": row.get("total_price_value"),
        "attributes": row.get("attributes"),
        "source_quote": row.get("source_quote"),
        "section_code": section,
        "section_name": section_name,
        # — провенанс/аудит —
        "row_or_line": row.get("row_or_line"),
        "page_or_sheet": row.get("page_or_sheet"),
        "source_document_id": row.get("source_document_id"),
        "duplicate_source_count": row.get("duplicate_source_count", 1),
        "category_code": row.get("category_code"),
        "subcategory_code": row.get("subcategory_code"),
        "trust_state": row.get("structured_fact_trust_state"),
        # — совместимость с существующим рендером —
        "product_name_raw": row.get("product_name_raw"),
        "product_name_normalized": row.get("product_name_normalized"),
        "quantity_value": row.get("quantity_value"),
        "quantity_unit_raw": row.get("quantity_unit_raw"),
        "quantity_unit_normalized": row.get("quantity_unit_normalized"),
        "unit_price_value": row.get("unit_price_value"),
        "total_price_value": row.get("total_price_value"),
        "entity_type": row.get("entity_type"),
        "product_relation": row.get("product_relation"),
    }


def build_good_supply_facts(
    procurement_id: int, *, limit: int = DEFAULT_LIMIT, conn: Any = None
) -> Dict[str, Any]:
    """Собрать чистые товарные факты закупки (read-only).

    Возвращает `{facts, hidden_works, hidden_aggregates, hidden_other, residue, audit}`.
    """
    own_conn = conn is None
    di = conn or _di_conn()
    try:
        rows = load_good_supply_rows(di, [int(procurement_id)])[: int(limit)]
    finally:
        if own_conn:
            di.close()

    facts: List[Dict[str, Any]] = []
    hidden = {"work": 0, "aggregate": 0, "no_quantity": 0, "no_total": 0,
              "bulk_material": 0,
              "no_quote": 0, "no_category": 0}
    residue = 0
    for row in rows:
        reason = classify_supply_row(row)
        if reason:
            hidden[reason] = hidden.get(reason, 0) + 1
            continue
        flat = to_flat_fact(row)
        if flat["section_code"] == RESIDUE:
            residue += 1
        facts.append(flat)

    return {
        "facts": facts,
        "hidden_works": hidden["work"],
        "hidden_aggregates": hidden["aggregate"],
        "hidden_other": sum(v for k, v in hidden.items() if k not in ("work", "aggregate")),
        "hidden_detail": hidden,
        "residue": residue,
        "audit": {"procurement_id": int(procurement_id), "scanned": len(rows),
                  "kept": len(facts)},
    }
