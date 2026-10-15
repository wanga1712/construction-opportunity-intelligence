"""Commercial portal read model (read-only).

WIP=COMMERCIAL_SITE_CRM_LINK_V1, phases 2-3.

Single authority for the commercial layer between CRM Streamlit and the
external site.  Nothing here writes: connections are opened read-only and every
statement is SELECT-only.

Authorities (no second medal/ranking logic is introduced):
  * ``crm_procurement_scope_authority`` - live market admission + scope type
  * ``crm_procurement_category_opportunities`` - current commercial medal and
    confirmation state (``current_effective_medal`` / ``confirmed_*``)
  * ``crm_procurements`` - identity, title, region, NMCK, execution window
  * ``crm_product_categories`` / ``crm_product_subcategories`` - naming
  * structured/confirmed document facts - see ``commercial_portal_facts``

The live-market predicate lives in :data:`UNIVERSE_SQL` and is byte-identical
to the PHASE 1 audit (``scripts/commercial_market_audit.sql``) so the API
summary cannot drift from the database audit.

Missing value is always ``null``; project NMCK is never used as a category
value, and zeros are never invented.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services import commercial_portal_facts as facts

MEDAL_RANK_SQL = (
    "CASE current_effective_medal WHEN 'GOLD' THEN 4 WHEN 'SILVER' THEN 3 "
    "WHEN 'BRONZE' THEN 2 WHEN 'WOOD' THEN 1 ELSE 0 END"
)
MEDAL_BY_RANK = {4: "GOLD", 3: "SILVER", 2: "BRONZE", 1: "WOOD", 0: None}
SEGMENTS = ("OPEN", "AWARDED_FOLLOWUP")
MAX_PAGE_SIZE = 200

UNIVERSE_SQL = f"""
WITH opp AS (
    SELECT procurement_id,
           bool_or(opportunity_track = 'DIRECT_SUPPLY')                       AS has_direct_supply,
           bool_or(opportunity_track IN ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT',
                                         'DESIGN_INFLUENCE'))                  AS has_project_embedded,
           bool_or(opportunity_track IN ('DIRECT_SUPPLY','EMBEDDED_MATERIAL',
                                         'DESIGN_REQUIREMENT','DESIGN_INFLUENCE')) AS has_commerce,
           bool_or(opportunity_track = 'NO_COMMERCIAL_ENTRY')                  AS has_no_entry,
           bool_or(commercial_state = 'FOLLOW_UP_AWARDED')                     AS has_followup,
           bool_or(confirmed_at IS NOT NULL)                                   AS has_confirmed,
           max({MEDAL_RANK_SQL})                                               AS best_medal_rank
      FROM crm_procurement_category_opportunities
     WHERE status = 'CURRENT'
     GROUP BY procurement_id
), market AS (
    SELECT sa.procurement_id,
           CASE WHEN sa.source_lifecycle = 'OPEN' THEN 'OPEN'
                ELSE 'AWARDED_FOLLOWUP' END                                    AS segment,
           sa.source_lifecycle,
           sa.procurement_scope_type,
           sa.admission_state,
           coalesce(o.has_direct_supply, false)    AS has_direct_supply,
           coalesce(o.has_project_embedded, false) AS has_project_embedded,
           coalesce(o.has_commerce, false)         AS has_commerce,
           coalesce(o.has_no_entry, false)         AS has_no_entry,
           coalesce(o.has_followup, false)         AS has_followup,
           coalesce(o.has_confirmed, false)        AS has_confirmed,
           coalesce(o.best_medal_rank, 0)          AS best_medal_rank
      FROM crm_procurement_scope_authority sa
      LEFT JOIN opp o ON o.procurement_id = sa.procurement_id
     WHERE sa.source_lifecycle IN ('OPEN','AWARDED')
       AND sa.admission_state = 'ELIGIBLE'
)
"""

_METRICS_SQL = UNIVERSE_SQL + """
SELECT 'COMMERCIAL_UNIVERSE_DISTINCT' AS metric, count(*)::bigint AS value FROM market
UNION ALL SELECT 'OPEN_DISTINCT',             count(*) FROM market WHERE segment = 'OPEN'
UNION ALL SELECT 'AWARDED_FOLLOWUP_DISTINCT', count(*) FROM market WHERE segment = 'AWARDED_FOLLOWUP'
UNION ALL SELECT 'WITH_COMMERCE',             count(*) FROM market WHERE has_commerce
UNION ALL SELECT 'WITHOUT_COMMERCE',          count(*) FROM market WHERE NOT has_commerce
UNION ALL SELECT 'DIRECT_SUPPLY',             count(*) FROM market WHERE has_direct_supply
UNION ALL SELECT 'PROJECT_EMBEDDED',          count(*) FROM market WHERE has_project_embedded
UNION ALL SELECT 'CONFIRMED',                 count(*) FROM market WHERE has_confirmed
UNION ALL SELECT 'PRELIMINARY_ONLY',          count(*) FROM market WHERE NOT has_confirmed
UNION ALL SELECT 'AWARDED_DIRECT_IN_LIVE_MARKET', count(*) FROM market
 WHERE segment = 'AWARDED_FOLLOWUP' AND procurement_scope_type = 'DIRECT_GOODS'
"""

_CATEGORY_ROWS_SQL = UNIVERSE_SQL + """
SELECT o.commercial_category_code AS category_code,
       o.commercial_subcategory_code AS subcategory_code,
       o.opportunity_track, o.commercial_state,
       o.current_effective_medal, o.confirmed_base_medal, o.confirmed_at,
       o.initial_medal_provenance, o.current_effective_score, o.candidate_initial_medal,
       c.category_name, s.subcategory_name
  FROM crm_procurement_category_opportunities o
  JOIN market m ON m.procurement_id = o.procurement_id
  LEFT JOIN crm_product_categories c ON c.category_code = o.commercial_category_code
  LEFT JOIN crm_product_subcategories s ON s.subcategory_code = o.commercial_subcategory_code
 WHERE o.procurement_id = %s AND o.status = 'CURRENT'
 ORDER BY o.current_effective_score DESC NULLS LAST
"""

_HEAD_SQL = UNIVERSE_SQL + """
SELECT m.procurement_id, m.segment, m.source_lifecycle, m.procurement_scope_type,
       m.admission_state, m.has_commerce, m.has_confirmed, m.best_medal_rank,
       p.contract_number, p.auction_name, p.initial_price, p.delivery_region,
       p.crm_stage, p.award_status, p.commercial_window_state, p.tender_link,
       p.source_table, p.source_id, p.end_date, p.execution_start_at, p.execution_end_at
  FROM market m JOIN crm_procurements p ON p.id = m.procurement_id
 WHERE m.procurement_id = %s
"""


class CommercialPortalService:
    """Read-only commercial projections consumed by the external site."""

    # ── market summary ───────────────────────────────────────────────────────

    def get_market_summary(self) -> Dict[str, Any]:
        with facts.connect(facts.crm_kwargs()) as conn:
            metrics = facts.query(conn, _METRICS_SQL)
            by_medal = facts.query(conn, UNIVERSE_SQL + """
SELECT coalesce(best_medal_rank, 0) AS medal_rank, segment, count(*)::bigint AS procurements
  FROM market GROUP BY 1, 2 ORDER BY 1 DESC, 2
""")
            by_scope = facts.query(conn, UNIVERSE_SQL + """
SELECT segment, procurement_scope_type, count(*)::bigint AS procurements
  FROM market GROUP BY 1, 2 ORDER BY 1, 3 DESC
""")
        values = {m["metric"]: int(m["value"]) for m in metrics}
        universe = values.get("COMMERCIAL_UNIVERSE_DISTINCT", 0)
        return {
            "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "unit": "DISTINCT_PROCUREMENT_ID",
            "metrics": values,
            "invariants": {
                "open_plus_awarded_eq_universe": (
                    values.get("OPEN_DISTINCT", 0)
                    + values.get("AWARDED_FOLLOWUP_DISTINCT", 0) == universe),
                "commerce_split_eq_universe": (
                    values.get("WITH_COMMERCE", 0)
                    + values.get("WITHOUT_COMMERCE", 0) == universe),
                "confirmed_split_eq_universe": (
                    values.get("CONFIRMED", 0)
                    + values.get("PRELIMINARY_ONLY", 0) == universe),
                "awarded_direct_zero": values.get("AWARDED_DIRECT_IN_LIVE_MARKET", 0) == 0,
            },
            "by_medal": [
                {"medal": MEDAL_BY_RANK.get(r["medal_rank"]) or "UNASSESSED",
                 "segment": r["segment"], "procurements": int(r["procurements"])}
                for r in by_medal
            ],
            "by_scope": [facts.clean_row(r) for r in by_scope],
        }

    # ── categories ───────────────────────────────────────────────────────────

    def get_categories(self) -> List[Dict[str, Any]]:
        with facts.connect(facts.crm_kwargs()) as conn:
            rows = facts.query(conn, UNIVERSE_SQL + """
SELECT o.commercial_category_code                             AS category_code,
       coalesce(c.category_name, o.commercial_category_code)   AS category_name,
       count(DISTINCT o.procurement_id)::bigint                AS procurements,
       count(DISTINCT o.procurement_id) FILTER (WHERE o.confirmed_at IS NOT NULL)::bigint
         AS confirmed,
       count(DISTINCT o.procurement_id) FILTER (WHERE o.opportunity_track = 'DIRECT_SUPPLY')::bigint
         AS direct_supply,
       count(DISTINCT o.procurement_id) FILTER (WHERE o.opportunity_track IN
             ('EMBEDDED_MATERIAL','DESIGN_REQUIREMENT','DESIGN_INFLUENCE'))::bigint
         AS project_embedded
  FROM crm_procurement_category_opportunities o
  JOIN market m ON m.procurement_id = o.procurement_id
  LEFT JOIN crm_product_categories c ON c.category_code = o.commercial_category_code
 WHERE o.status = 'CURRENT'
 GROUP BY 1, 2 ORDER BY 3 DESC
""")
        return [facts.clean_row(r) for r in rows]

    # ── ranked list ──────────────────────────────────────────────────────────

    def list_ranked_procurements(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        f = dict(filters or {})
        where: List[str] = []
        params: List[Any] = []
        if f.get("segment"):
            where.append("m.segment = %s")
            params.append(str(f["segment"]).upper())
        if f.get("scope_type"):
            where.append("m.procurement_scope_type = %s")
            params.append(str(f["scope_type"]))
        if f.get("confirmed_only"):
            where.append("m.has_confirmed")
        if f.get("with_commerce"):
            where.append("m.has_commerce")
        if f.get("category_code"):
            where.append(
                "EXISTS (SELECT 1 FROM crm_procurement_category_opportunities co"
                " WHERE co.procurement_id = m.procurement_id AND co.status = 'CURRENT'"
                " AND co.commercial_category_code = %s)")
            params.append(str(f["category_code"]))
        if f.get("medal"):
            rank = {v: k for k, v in MEDAL_BY_RANK.items()}.get(str(f["medal"]).upper(), -1)
            where.append("m.best_medal_rank = %s")
            params.append(rank)
        if f.get("region"):
            where.append("p.delivery_region ILIKE %s")
            params.append(f"%{f['region']}%")
        if f.get("query"):
            where.append("(p.auction_name ILIKE %s OR p.contract_number ILIKE %s)")
            params.extend([f"%{f['query']}%", f"%{f['query']}%"])
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        limit = max(1, min(int(f.get("limit") or 50), MAX_PAGE_SIZE))
        offset = max(0, int(f.get("offset") or 0))
        sql = UNIVERSE_SQL + f"""
, ranked AS (
    SELECT m.procurement_id, m.segment, m.procurement_scope_type, m.procurement_scope_type
             AS scope_type, m.has_commerce, m.has_confirmed, m.best_medal_rank,
           p.contract_number, p.auction_name, p.initial_price, p.delivery_region,
           p.execution_end_at,
           coalesce(max(o.current_effective_score), 0)           AS best_score,
           string_agg(DISTINCT o.commercial_category_code, ',') AS category_codes
      FROM market m
      JOIN crm_procurements p ON p.id = m.procurement_id
      LEFT JOIN crm_procurement_category_opportunities o
             ON o.procurement_id = m.procurement_id AND o.status = 'CURRENT'
      {clause}
     GROUP BY m.procurement_id, m.segment, m.procurement_scope_type, m.has_commerce,
              m.has_confirmed, m.best_medal_rank, p.contract_number, p.auction_name,
              p.initial_price, p.delivery_region, p.execution_end_at
)
SELECT *, count(*) OVER () AS total_count
  FROM ranked
 ORDER BY best_medal_rank DESC, best_score DESC, execution_end_at NULLS LAST,
          procurement_id DESC
 LIMIT %s OFFSET %s
"""
        with facts.connect(facts.crm_kwargs()) as conn:
            rows = facts.query(conn, sql, params + [limit, offset])
        items = [{
            "procurement_id": r["procurement_id"],
            "segment": r["segment"],
            "scope_type": r["procurement_scope_type"],
            "title": r["auction_name"],
            "contract_number": r["contract_number"],
            "region": r["delivery_region"],
            "nmck": facts.jsonable(r["initial_price"]),
            "best_medal": MEDAL_BY_RANK.get(r["best_medal_rank"]),
            "has_commerce": r["has_commerce"],
            "confirmed": r["has_confirmed"],
            "commercial_score": facts.jsonable(r["best_score"]),
            "execution_end_at": facts.jsonable(r["execution_end_at"]),
            "categories": (r["category_codes"] or "").split(",") if r["category_codes"] else [],
        } for r in rows]
        return {
            "total": int(rows[0]["total_count"]) if rows else 0,
            "limit": limit, "offset": offset, "items": items,
        }

    # ── preview / commercial card ────────────────────────────────────────────

    def get_procurement_preview(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        ctx = self._load_procurement(procurement_id)
        if ctx is None:
            return None
        return {
            "identity": {
                "procurement_id": ctx["procurement_id"],
                "contract_number": ctx["contract_number"],
                "source_table": ctx["source_table"],
                "source_id": ctx["source_id"],
            },
            "title": ctx["auction_name"],
            "status": {
                "source_lifecycle": ctx["source_lifecycle"],
                "segment": ctx["segment"],
                "crm_stage": ctx["crm_stage"],
                "award_status": ctx["award_status"],
                "admission_state": ctx["admission_state"],
                "commercial_window_state": ctx["commercial_window_state"],
            },
            "region": ctx["delivery_region"],
            "nmck": {"value": facts.jsonable(ctx["initial_price"]), "currency": "RUB"},
            "execution_window": {
                "tender_end_date": facts.jsonable(ctx["end_date"]),
                "execution_start_at": facts.jsonable(ctx["execution_start_at"]),
                "execution_end_at": facts.jsonable(ctx["execution_end_at"]),
            },
            "commercial_modes": ctx["commercial_modes"],
            "best_medal": ctx["best_medal"],
            "categories": ctx["categories"],
        }

    def get_procurement_commercial_card(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        preview = self.get_procurement_preview(procurement_id)
        if preview is None:
            return None
        preview["commercial"] = {
            "with_commerce": preview["categories"] != [],
            "confirmed": any(c["confirmed"] for c in preview["categories"]),
            "value_basis": "CATEGORY_DOCUMENT_FACTS_AND_MATERIAL_LINES",
            "project_nmck_used_as_category_value": False,
            "category_value_sum": _sum_or_none([c["material_value"] for c in preview["categories"]]),
            "evidence": self._evidence(procurement_id),
        }
        return preview

    # ── internals ────────────────────────────────────────────────────────────

    def _load_procurement(self, procurement_id: int) -> Optional[Dict[str, Any]]:
        with facts.connect(facts.crm_kwargs()) as conn:
            head = facts.query(conn, _HEAD_SQL, (procurement_id,))
            if not head:
                return None
            row = dict(head[0])
            rows = facts.query(conn, _CATEGORY_ROWS_SQL, (procurement_id,))
        materials = facts.load_materials(procurement_id)
        confirmed, confirmed_status = facts.load_confirmed_values(procurement_id)

        categories = [
            _category(c, materials.get(c["category_code"], {}),
                      confirmed.get(c["category_code"], {}), confirmed_status)
            for c in rows
        ]
        row["categories"] = categories
        row["commercial_modes"] = sorted(
            {c["commercial_mode"] for c in categories if c["commercial_mode"]})
        row["best_medal"] = MEDAL_BY_RANK.get(row.pop("best_medal_rank", 0) or 0)
        return row

    def _evidence(self, procurement_id: int) -> List[Dict[str, Any]]:
        return facts.load_evidence_rows(procurement_id)


def _category(row: Dict[str, Any], material: Dict[str, Any],
              confirmed: Dict[str, Any], confirmed_status: str) -> Dict[str, Any]:
    """One category of the preview contract. Never invents zeros or values."""
    materials_count = confirmed.get("materials_count") or material.get("materials_count")
    return {
        "category_code": row["category_code"],
        "category_name": row["category_name"] or row["category_code"],
        "subcategory_code": row["subcategory_code"],
        "subcategory_name": row["subcategory_name"],
        "medal": row["current_effective_medal"],
        "confirmed_medal": row["confirmed_base_medal"],
        "confirmed": row["confirmed_at"] is not None,
        "confirmed_at": facts.jsonable(row["confirmed_at"]),
        "medal_authority": row["initial_medal_provenance"],
        "commercial_state": row["commercial_state"],
        "commercial_mode": row["opportunity_track"],
        "commercial_score": facts.jsonable(row["current_effective_score"]),
        "section_value": confirmed.get("section_value"),
        "section_value_source": confirmed.get("source", confirmed_status),
        "material_value": material.get("material_value"),
        "material_value_status": material.get("material_value_status", "NO_TRUSTED_FACTS"),
        "material_value_source": material.get("source", "NO_TRUSTED_FACTS"),
        "materials_count": materials_count if materials_count is not None else None,
        "materials_sample": material.get("materials_sample", []),
        "manufacturers_sample": material.get("manufacturers_sample", []),
        "brands_sample": material.get("brands_sample", []),
        "technical_attributes_count": material.get("technical_attributes_count"),
        "evidence_count": material.get("evidence_count"),
    }


def _sum_or_none(values: List[Any]) -> Optional[float]:
    present = [float(v) for v in values if v is not None]
    return round(sum(present), 2) if present else None
