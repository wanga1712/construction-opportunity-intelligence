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

import os
import re
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from src.services.works_vs_goods_service import classify_fact_kind

RESIDUE = "RESIDUE"
#: агрегатные/шапочные строки — не товар
_AGGREGATE_RE = re.compile(r"^\s*(итого|всего|стоимость|ндс|раздел|глава)\b", re.IGNORECASE)

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
    if row.get("total_price_value") is None:
        return "no_total"
    return None


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
              "no_quote": 0, "no_category": 0}
    residue = 0
    for row in rows:
        reason = classify_supply_row(row)
        if reason:
            hidden[reason] = hidden.get(reason, 0) + 1
            continue
        section = str(row.get("section_code") or "").strip()
        if not section or section.upper().startswith(RESIDUE):
            section = RESIDUE
            residue += 1
        row["section_code"] = section
        facts.append(row)

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
