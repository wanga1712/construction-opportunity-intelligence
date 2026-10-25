"""GOOD_SUPPLY_FACTS_V1 — чистый слой «что можно поставить».

Источник — `structured_entities` (НЕ `document_match_details`: сырые матчи остаются
только evidence). Оставляем реальные ТОВАРНЫЕ/материальные факты:

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
#: агрегатные/шапочные строки — не товар
_AGGREGATE_RE = re.compile(r"^\s*(итого|всего|стоимость|ндс|раздел|глава|\d+(?:\.\d+)*\s+\S)", re.IGNORECASE)

DEFAULT_LIMIT = 300

#: Одна и та же позиция может иметь старую строку без section и новую с ним:
#: берём предпочтительную (section_code IS NOT NULL, затем больший id).
_GOOD_SUPPLY_SQL = """
WITH preferred AS (
    SELECT se.*,
           row_number() OVER (
               PARTITION BY se.procurement_id, se.source_document_id,
                            coalesce(se.row_or_line, ''), coalesce(se.product_name_raw, '')
               ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
           ) AS pref_rn
      FROM structured_entities se
     WHERE se.procurement_id = %s
)
SELECT se.id, se.category_code, se.entity_type, se.product_name_raw, se.product_name_normalized,
       se.manufacturer_normalized, se.brand_normalized, se.model_article_normalized,
       se.quantity_value, se.quantity_unit_raw, se.quantity_unit_normalized,
       se.unit_price_value, se.total_price_value, se.product_relation,
       se.source_quote, se.row_or_line, se.page_or_sheet, se.layout_status, se.confidence,
       se.structured_fact_trust_state, se.extractor_version, se.physical_download_key,
       se.section_code, se.section_name, se.section_total_price_value,
       se.section_total_price_raw, se.section_total_source, se.source_document_id,
       COALESCE((
         SELECT jsonb_agg(jsonb_build_object(
                  'name', a.attribute_name,
                  'name_normalized', a.attribute_name_normalized,
                  'raw_value', a.raw_value,
                  'normalized_value', a.normalized_value,
                  'numeric_value', a.numeric_value,
                  'unit', a.unit_normalized)
                ORDER BY a.id)
         FROM structured_attributes a WHERE a.entity_id = se.id), '[]'::jsonb) AS attributes
  FROM preferred se
 WHERE se.pref_rn = 1
 ORDER BY se.total_price_value DESC NULLS LAST, se.id
 LIMIT %s
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


def classify_supply_row(row: Dict[str, Any]) -> Optional[str]:
    """Почему строка НЕ идёт в «что можно поставить» (или None, если годится)."""
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
    if str(row.get("quantity_unit_normalized") or "").upper() not in COUNT_UNITS:
        return "bulk_material"
    if _fractional_count_quantity(row):
        return "no_quantity"
    if row.get("total_price_value") is None:
        return "no_total"
    return None


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
    sql = """
        WITH preferred AS (
            SELECT se.*,
                   row_number() OVER (
                       PARTITION BY se.procurement_id, se.source_document_id,
                                    coalesce(se.row_or_line, ''),
                                    coalesce(se.product_name_raw, '')
                       ORDER BY (se.section_code IS NOT NULL) DESC, se.id DESC
                   ) AS pref_rn
              FROM structured_entities se
             WHERE se.procurement_id = ANY(%s)
               AND coalesce(se.category_code, '') NOT IN ('', 'unknown')
               AND se.entity_type = 'PRODUCT'
               AND se.quantity_value IS NOT NULL
               AND coalesce(se.quantity_unit_normalized, '') <> ''
               AND coalesce(se.source_quote, '') <> ''
        )
        SELECT procurement_id, category_code, product_name_raw,
               product_name_normalized, quantity_value,
               quantity_unit_normalized, source_quote
          FROM preferred
         WHERE pref_rn = 1
    """
    counts: Dict[tuple[int, str], int] = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (ids,))
        rows = cur.fetchall()
    for raw in rows:
        row = dict(raw)
        category = str(row.get("category_code") or "").strip()
        name = row.get("product_name_normalized") or row.get("product_name_raw")
        if not category or category == "unknown":
            continue
        if classify_fact_kind(entity_type=row.get("entity_type"), name=name) != "GOODS":
            continue
        if str(row.get("quantity_unit_normalized") or "").upper() not in COUNT_UNITS:
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
        "category_code": row.get("category_code"),
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
        with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_GOOD_SUPPLY_SQL, (int(procurement_id), int(limit)))
            rows = [dict(r) for r in cur.fetchall()]
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
