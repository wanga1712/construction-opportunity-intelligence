"""SQL-backed category-first analytics read model.

The active runtime already has canonical V3 category opportunities in
``crm_procurement_category_opportunities``.  This service reads that existing
authority together with ``crm_product_categories``; it does not depend on the
new classifier tables and does not download or mutate anything.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


_MEDALS = ("GOLD", "SILVER", "BRONZE", "WOOD")


def _empty_medals() -> Dict[str, int]:
    return {medal.lower(): 0 for medal in _MEDALS}


def _opp_cte() -> str:
    """Shared CTE over the canonical V3 opportunity table."""
    return """
        WITH opp AS (
            SELECT
                o.commercial_category_code AS category_code,
                o.procurement_id,
                p.initial_price AS amount,
                o.opportunity_track,
                o.commercial_subcategory_code AS subcategory_code,
                s.subcategory_name,
                o.candidate_initial_medal AS initial_medal,
                o.current_effective_medal AS current_medal
            FROM crm_procurement_category_opportunities o
            JOIN crm_procurements p ON p.id = o.procurement_id
            LEFT JOIN crm_product_subcategories s
              ON s.subcategory_code = o.commercial_subcategory_code
             AND s.category_id = (
                    SELECT c.id
                    FROM crm_product_categories c
                    WHERE c.category_code = o.commercial_category_code
                    ORDER BY c.id
                    LIMIT 1
                )
            WHERE o.status = 'CURRENT'
        )
    """


def get_category_overview(crm_db: Any) -> Dict[str, Any]:
    category_rows = crm_db.execute_query(
        """
        SELECT category_code, category_name, sort_order
        FROM crm_product_categories
        WHERE is_active = TRUE
        ORDER BY sort_order, category_name, category_code
        """
    ) or []

    agg_rows = crm_db.execute_query(
        _opp_cte()
        + """,
        cat_proc AS (
            SELECT DISTINCT category_code, procurement_id, amount
            FROM opp
        ),
        cat_form AS (
            SELECT DISTINCT category_code, procurement_id, opportunity_track
            FROM opp
        ),
        cat_medal AS (
            SELECT
                category_code,
                procurement_id,
                MAX(initial_medal) AS initial_medal,
                MAX(current_medal) AS current_medal
            FROM opp
            GROUP BY category_code, procurement_id
        ),
        cat_proc_agg AS (
            SELECT
                category_code,
                COUNT(DISTINCT procurement_id) AS procurement_count,
                COALESCE(SUM(amount), 0) AS total_amount
            FROM cat_proc
            GROUP BY category_code
        ),
        cat_form_agg AS (
            SELECT
                category_code,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE opportunity_track = 'DIRECT_SUPPLY')
                    AS direct_supply_count,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE opportunity_track = 'EMBEDDED_MATERIAL')
                    AS works_with_products_count
            FROM cat_form
            GROUP BY category_code
        ),
        cat_medal_agg AS (
            SELECT
                category_code,
                COUNT(*) FILTER (WHERE initial_medal = 'GOLD') AS initial_gold,
                COUNT(*) FILTER (WHERE initial_medal = 'SILVER') AS initial_silver,
                COUNT(*) FILTER (WHERE initial_medal = 'BRONZE') AS initial_bronze,
                COUNT(*) FILTER (WHERE initial_medal = 'WOOD') AS initial_wood,
                COUNT(*) FILTER (WHERE current_medal = 'GOLD') AS current_gold,
                COUNT(*) FILTER (WHERE current_medal = 'SILVER') AS current_silver,
                COUNT(*) FILTER (WHERE current_medal = 'BRONZE') AS current_bronze,
                COUNT(*) FILTER (WHERE current_medal = 'WOOD') AS current_wood
            FROM cat_medal
            GROUP BY category_code
        )
        SELECT
            cpa.category_code,
            cpa.procurement_count,
            cpa.total_amount,
            COALESCE(cfa.direct_supply_count, 0) AS direct_supply_count,
            COALESCE(cfa.works_with_products_count, 0) AS works_with_products_count,
            COALESCE(cma.initial_gold, 0) AS initial_gold,
            COALESCE(cma.initial_silver, 0) AS initial_silver,
            COALESCE(cma.initial_bronze, 0) AS initial_bronze,
            COALESCE(cma.initial_wood, 0) AS initial_wood,
            COALESCE(cma.current_gold, 0) AS current_gold,
            COALESCE(cma.current_silver, 0) AS current_silver,
            COALESCE(cma.current_bronze, 0) AS current_bronze,
            COALESCE(cma.current_wood, 0) AS current_wood
        FROM cat_proc_agg cpa
        LEFT JOIN cat_form_agg cfa ON cfa.category_code = cpa.category_code
        LEFT JOIN cat_medal_agg cma ON cma.category_code = cpa.category_code
        """
    ) or []

    sub_rows = crm_db.execute_query(
        _opp_cte()
        + """,
        sub_proc AS (
            SELECT DISTINCT
                category_code,
                subcategory_code,
                subcategory_name,
                procurement_id,
                amount
            FROM opp
            WHERE subcategory_code IS NOT NULL
        ),
        sub_form AS (
            SELECT DISTINCT
                category_code,
                subcategory_code,
                procurement_id,
                opportunity_track
            FROM opp
            WHERE subcategory_code IS NOT NULL
        ),
        sub_form_agg AS (
            SELECT
                category_code,
                subcategory_code,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE opportunity_track = 'DIRECT_SUPPLY')
                    AS direct_supply_count,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE opportunity_track = 'EMBEDDED_MATERIAL')
                    AS works_with_products_count
            FROM sub_form
            GROUP BY category_code, subcategory_code
        ),
        sub_proc_agg AS (
            SELECT
                category_code,
                subcategory_code,
                subcategory_name,
                COUNT(DISTINCT procurement_id) AS procurement_count,
                COALESCE(SUM(amount), 0) AS total_amount
            FROM sub_proc
            GROUP BY category_code, subcategory_code, subcategory_name
        )
        SELECT
            spa.category_code,
            spa.subcategory_code,
            spa.subcategory_name,
            spa.procurement_count,
            spa.total_amount,
            COALESCE(sfa.direct_supply_count, 0) AS direct_supply_count,
            COALESCE(sfa.works_with_products_count, 0) AS works_with_products_count
        FROM sub_proc_agg spa
        LEFT JOIN sub_form_agg sfa
          ON sfa.category_code = spa.category_code
         AND sfa.subcategory_code = spa.subcategory_code
        """
    ) or []

    unclassified_rows = crm_db.execute_query(
        _opp_cte()
        + """,
        unclassified_proc AS (
            SELECT DISTINCT category_code, procurement_id, amount
            FROM opp
            WHERE subcategory_code IS NULL
        )
        SELECT
            category_code,
            COUNT(DISTINCT procurement_id) AS procurement_count,
            COALESCE(SUM(amount), 0) AS total_amount
        FROM unclassified_proc
        GROUP BY category_code
        """
    ) or []

    agg_by_category = {
        str(row.get("category_code") or ""): row for row in agg_rows
    }
    subs_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for row in sub_rows:
        code = str(row.get("category_code") or "")
        subs_by_category.setdefault(code, []).append(
            {
                "subcategory_code": row.get("subcategory_code"),
                "subcategory_name": row.get("subcategory_name"),
                "procurement_count": int(row.get("procurement_count") or 0),
                "total_amount": float(row.get("total_amount") or 0),
                "direct_supply_count": int(row.get("direct_supply_count") or 0),
                "works_with_products_count": int(
                    row.get("works_with_products_count") or 0
                ),
            }
        )

    unclassified_by_category = {
        str(row.get("category_code") or ""): {
            "procurement_count": int(row.get("procurement_count") or 0),
            "total_amount": float(row.get("total_amount") or 0),
        }
        for row in unclassified_rows
    }

    categories: List[Dict[str, Any]] = []
    for row in category_rows:
        code = str(row.get("category_code") or "")
        agg = agg_by_category.get(code, {})
        initial = _empty_medals()
        initial.update(
            {
                "gold": int(agg.get("initial_gold") or 0),
                "silver": int(agg.get("initial_silver") or 0),
                "bronze": int(agg.get("initial_bronze") or 0),
                "wood": int(agg.get("initial_wood") or 0),
            }
        )
        current = _empty_medals()
        current.update(
            {
                "gold": int(agg.get("current_gold") or 0),
                "silver": int(agg.get("current_silver") or 0),
                "bronze": int(agg.get("current_bronze") or 0),
                "wood": int(agg.get("current_wood") or 0),
            }
        )
        categories.append(
            {
                "category_code": code,
                "category_name": str(row.get("category_name") or "").strip(),
                "procurement_count": int(agg.get("procurement_count") or 0),
                "total_amount": float(agg.get("total_amount") or 0),
                "direct_supply_count": int(agg.get("direct_supply_count") or 0),
                "works_with_products_count": int(
                    agg.get("works_with_products_count") or 0
                ),
                "initial_medals": initial,
                "current_medals": current,
                "confirmed_medals": _empty_medals(),
                "subcategories": subs_by_category.get(code, []),
                "unclassified": unclassified_by_category.get(
                    code, {"procurement_count": 0, "total_amount": 0}
                ),
            }
        )
    return {"categories": categories}


def get_category_summary(crm_db: Any, medal_view: str = "initial") -> Dict[str, Any]:
    if medal_view not in {"initial", "current"}:
        raise ValueError(f"unsupported medal_view: {medal_view!r}")
    medal_column = "cm.initial_medal" if medal_view == "initial" else "cm.current_medal"
    rows = crm_db.execute_query(
        _opp_cte()
        + f""",
        cat_proc AS (
            SELECT DISTINCT category_code, procurement_id, amount
            FROM opp
        ),
        cat_medal AS (
            SELECT
                category_code,
                procurement_id,
                MAX(initial_medal) AS initial_medal,
                MAX(current_medal) AS current_medal
            FROM opp
            GROUP BY category_code, procurement_id
        ),
        global_amount AS (
            SELECT DISTINCT procurement_id, amount
            FROM opp
        )
        SELECT
            (SELECT COUNT(*) FROM crm_product_categories WHERE is_active = TRUE)
                AS category_count,
            (SELECT COUNT(*) FROM cat_proc) AS opportunity_count,
            COALESCE((SELECT SUM(amount) FROM global_amount), 0) AS total_amount,
            COUNT(*) FILTER (WHERE {medal_column} = 'GOLD') AS gold,
            COUNT(*) FILTER (WHERE {medal_column} = 'SILVER') AS silver,
            COUNT(*) FILTER (WHERE {medal_column} = 'BRONZE') AS bronze,
            COUNT(*) FILTER (WHERE {medal_column} = 'WOOD') AS wood
        FROM cat_proc cp
        LEFT JOIN cat_medal cm
          ON cm.category_code = cp.category_code
         AND cm.procurement_id = cp.procurement_id
        """
    ) or []
    row = rows[0] if rows else {}
    return {
        "category_count": int(row.get("category_count") or 0),
        "opportunity_count": int(row.get("opportunity_count") or 0),
        "total_amount": float(row.get("total_amount") or 0),
        "medals": {
            "gold": int(row.get("gold") or 0),
            "silver": int(row.get("silver") or 0),
            "bronze": int(row.get("bronze") or 0),
            "wood": int(row.get("wood") or 0),
        },
    }


def _mode_from_track(track: Any) -> str:
    value = str(track or "").upper()
    if value == "DIRECT_SUPPLY":
        return "direct_supply"
    if value == "EMBEDDED_MATERIAL":
        return "works_with_products"
    return "works_with_products" if value else "unknown"


def get_category_procurements(
    crm_db: Any,
    category_code: str,
    subcategory_code: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    if subcategory_code is None:
        return []

    if subcategory_code == "__unclassified__":
        subcategory_sql = "AND o.commercial_subcategory_code IS NULL"
        params = (category_code, limit)
    else:
        subcategory_sql = "AND o.commercial_subcategory_code = %s"
        params = (category_code, subcategory_code, limit)

    rows = crm_db.execute_query(
        f"""
        SELECT DISTINCT ON (o.procurement_id, o.commercial_category_code)
            o.procurement_id,
            p.auction_name,
            p.initial_price,
            p.customer,
            p.okpd_code,
            p.okpd_name,
            o.commercial_category_code AS category_code,
            o.commercial_subcategory_code AS subcategory_code,
            s.subcategory_name,
            o.opportunity_track,
            o.candidate_initial_medal,
            o.current_effective_medal,
            o.confirmed_base_medal
        FROM crm_procurement_category_opportunities o
        JOIN crm_procurements p ON p.id = o.procurement_id
        LEFT JOIN crm_product_subcategories s
          ON s.subcategory_code = o.commercial_subcategory_code
         AND s.category_id = (
                SELECT c.id
                FROM crm_product_categories c
                WHERE c.category_code = o.commercial_category_code
                ORDER BY c.id
                LIMIT 1
            )
        WHERE o.status = 'CURRENT'
          AND o.commercial_category_code = %s
          {subcategory_sql}
        ORDER BY o.procurement_id, o.commercial_category_code, o.id DESC
        LIMIT %s
        """,
        params,
    ) or []
    return [
        {
            "object_key": None,
            "procurement_id": row.get("procurement_id"),
            "auction_name": row.get("auction_name"),
            "initial_price": row.get("initial_price"),
            "customer": row.get("customer"),
            "okpd_code": row.get("okpd_code"),
            "okpd_name": row.get("okpd_name"),
            "category_code": row.get("category_code"),
            "subcategory_code": row.get("subcategory_code"),
            "subcategory_name": row.get("subcategory_name"),
            "product_name": row.get("subcategory_name"),
            "quantity": None,
            "unit": None,
            "procurement_mode": _mode_from_track(row.get("opportunity_track")),
            "object_present": None,
            "object_type": None,
            "work_type": None,
            "candidate_initial_medal": row.get("candidate_initial_medal"),
            "current_effective_medal": row.get("current_effective_medal"),
            "confirmed_base_medal": row.get("confirmed_base_medal"),
        }
        for row in rows
    ]
