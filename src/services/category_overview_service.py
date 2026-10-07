"""SQL-backed category overview for the first screen of the analytics contour.

The service returns UI-ready aggregates without loading all procurements into
Python.  Categories come from ``crm_product_categories``, which is also the
single source of truth for dynamically promoted categories.
"""
from __future__ import annotations

from typing import Any, Dict, List


_MEDALS = ("GOLD", "SILVER", "BRONZE", "WOOD")


def _empty_medals() -> Dict[str, int]:
    return {medal.lower(): 0 for medal in _MEDALS}


def get_category_overview(crm_db: Any) -> Dict[str, Any]:
    """Return the UI contract for the category-first analytics screen."""
    category_rows = crm_db.execute_query(
        """
        SELECT category_code, category_name, sort_order
        FROM crm_product_categories
        WHERE is_active = TRUE
        ORDER BY sort_order, category_name, category_code
        """
    ) or []

    agg_rows = crm_db.execute_query(
        """
        WITH opp_proc AS (
            SELECT
                o.category_code,
                o.subcategory_code,
                o.subcategory_name,
                p.id AS procurement_id,
                p.initial_price AS amount,
                pc.procurement_mode,
                pc.object_present,
                pc.primary_class,
                pc.object_type,
                pc.work_type
            FROM crm_procurement_opportunities o
            LEFT JOIN crm_procurement_classifications pc
              ON pc.object_key = o.object_key
            LEFT JOIN crm_procurements p
              ON p.source_table = o.registry_type
             AND p.source_id = o.tender_id
        ),
        distinct_opp AS (
            SELECT DISTINCT category_code, procurement_id
            FROM opp_proc
            WHERE procurement_id IS NOT NULL
        ),
        proc_opp AS (
            SELECT DISTINCT
                category_code,
                procurement_id,
                amount,
                procurement_mode,
                primary_class,
                object_type,
                work_type
            FROM opp_proc
            WHERE procurement_id IS NOT NULL
        ),
        cat_agg AS (
            SELECT
                category_code,
                COUNT(DISTINCT procurement_id) AS procurement_count,
                COALESCE(SUM(amount), 0) AS total_amount,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE procurement_mode = 'direct_supply')
                    AS direct_supply_count,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE procurement_mode = 'works_with_products')
                    AS works_with_products_count
            FROM proc_opp
            GROUP BY category_code
        ),
        medal_rows AS (
            SELECT
                procurement_id,
                commercial_category_code,
                MAX(candidate_medal) AS candidate_medal,
                MAX(confirmed_base_medal) AS confirmed_base_medal
            FROM crm_procurement_category_opportunities
            WHERE status = 'CURRENT'
            GROUP BY procurement_id, commercial_category_code
        ),
        medal_agg AS (
            SELECT
                do.category_code,
                COUNT(*) FILTER (WHERE mr.candidate_medal = 'GOLD') AS candidate_gold,
                COUNT(*) FILTER (WHERE mr.candidate_medal = 'SILVER') AS candidate_silver,
                COUNT(*) FILTER (WHERE mr.candidate_medal = 'BRONZE') AS candidate_bronze,
                COUNT(*) FILTER (WHERE mr.candidate_medal = 'WOOD') AS candidate_wood,
                COUNT(*) FILTER (WHERE mr.confirmed_base_medal = 'GOLD') AS confirmed_gold,
                COUNT(*) FILTER (WHERE mr.confirmed_base_medal = 'SILVER') AS confirmed_silver,
                COUNT(*) FILTER (WHERE mr.confirmed_base_medal = 'BRONZE') AS confirmed_bronze,
                COUNT(*) FILTER (WHERE mr.confirmed_base_medal = 'WOOD') AS confirmed_wood
            FROM distinct_opp do
            LEFT JOIN medal_rows mr
              ON mr.procurement_id = do.procurement_id
             AND mr.commercial_category_code = do.category_code
            GROUP BY do.category_code
        ),
        sub_opp AS (
            SELECT DISTINCT
                category_code,
                subcategory_code,
                subcategory_name,
                procurement_id,
                amount,
                procurement_mode,
                primary_class,
                object_type,
                work_type
            FROM opp_proc
            WHERE procurement_id IS NOT NULL
        ),
        sub_agg AS (
            SELECT
                category_code,
                subcategory_code,
                subcategory_name,
                COUNT(DISTINCT procurement_id) AS procurement_count,
                COALESCE(SUM(amount), 0) AS total_amount,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE procurement_mode = 'direct_supply')
                    AS direct_supply_count,
                COUNT(DISTINCT procurement_id)
                    FILTER (WHERE procurement_mode = 'works_with_products')
                    AS works_with_products_count
            FROM sub_opp
            GROUP BY category_code, subcategory_code, subcategory_name
        )
        SELECT
            ca.category_code,
            ca.procurement_count,
            ca.total_amount,
            ca.direct_supply_count,
            ca.works_with_products_count,
            ma.candidate_gold,
            ma.candidate_silver,
            ma.candidate_bronze,
            ma.candidate_wood,
            ma.confirmed_gold,
            ma.confirmed_silver,
            ma.confirmed_bronze,
            ma.confirmed_wood
        FROM cat_agg ca
        LEFT JOIN medal_agg ma ON ma.category_code = ca.category_code
        """
    ) or []

    sub_rows = crm_db.execute_query(
        """
        WITH opp_proc AS (
            SELECT
                o.category_code,
                o.subcategory_code,
                o.subcategory_name,
                p.id AS procurement_id,
                p.initial_price AS amount,
                pc.procurement_mode,
                pc.primary_class,
                pc.object_type,
                pc.work_type
            FROM crm_procurement_opportunities o
            LEFT JOIN crm_procurement_classifications pc
              ON pc.object_key = o.object_key
            LEFT JOIN crm_procurements p
              ON p.source_table = o.registry_type
             AND p.source_id = o.tender_id
        ),
        sub_opp AS (
            SELECT DISTINCT
                category_code,
                subcategory_code,
                subcategory_name,
                procurement_id,
                amount,
                procurement_mode,
                primary_class,
                object_type,
                work_type
            FROM opp_proc
            WHERE procurement_id IS NOT NULL
        )
        SELECT
            category_code,
            subcategory_code,
            subcategory_name,
            COUNT(DISTINCT procurement_id) AS procurement_count,
            COALESCE(SUM(amount), 0) AS total_amount,
            COUNT(DISTINCT procurement_id)
                FILTER (WHERE procurement_mode = 'direct_supply')
                AS direct_supply_count,
            COUNT(DISTINCT procurement_id)
                FILTER (WHERE procurement_mode = 'works_with_products')
                AS works_with_products_count
        FROM sub_opp
        GROUP BY category_code, subcategory_code, subcategory_name
        """
    ) or []

    agg_by_category: Dict[str, Dict[str, Any]] = {}
    for row in agg_rows:
        code = str(row.get("category_code") or "")
        agg_by_category[code] = row

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

    categories: List[Dict[str, Any]] = []
    for row in category_rows:
        code = str(row.get("category_code") or "")
        agg = agg_by_category.get(code, {})
        candidate = _empty_medals()
        candidate.update(
            {
                "gold": int(agg.get("candidate_gold") or 0),
                "silver": int(agg.get("candidate_silver") or 0),
                "bronze": int(agg.get("candidate_bronze") or 0),
                "wood": int(agg.get("candidate_wood") or 0),
            }
        )
        confirmed = _empty_medals()
        confirmed.update(
            {
                "gold": int(agg.get("confirmed_gold") or 0),
                "silver": int(agg.get("confirmed_silver") or 0),
                "bronze": int(agg.get("confirmed_bronze") or 0),
                "wood": int(agg.get("confirmed_wood") or 0),
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
                "candidate_medals": candidate,
                "confirmed_medals": confirmed,
                "subcategories": subs_by_category.get(code, []),
            }
        )

    return {"categories": categories}
