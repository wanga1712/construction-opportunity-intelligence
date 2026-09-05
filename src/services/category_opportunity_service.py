"""Category Opportunity Service and Read Model.

Provides canonical projection CategoryOpportunity for procurement x product category,
supporting multi-medal output per procurement without max-medal collapse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

# Category code to display name mapping
CATEGORY_NAMES: Dict[str, str] = {
    "lighting": "Светотехника",
    "flooring": "Напольные покрытия",
    "waterproofing": "Гидроизоляция",
    "waterproofing_concrete_repair": "Гидроизоляция и ремонт бетона",
    "bridge_road_infrastructure": "Мостовая и дорожная инфраструктура",
    "cable_support_systems": "Кабеленесущие системы",
    "composite_structures": "Композитные конструкции",
    "drainage_water_management": "Водоотвод и дренаж",
    "external_utility_networks": "Наружные инженерные сети",
    "structural_reinforcement": "Усиление и ремонт конструкций",
    "curbstone": "Бордюрный камень",
    "concrete_materials": "Материалы для бетона",
}

# Relation type to display name
RELATION_DISPLAY: Dict[str, str] = {
    "PRIMARY_SUBJECT": "Предмет закупки",
    "EMBEDDED_IN_WORKS": "Внутри строительных работ",
    "SPECIFIED_IN_PROJECT": "Предусмотрено проектом",
    "EQUIPMENT_WITH_INSTALLATION": "Поставка + монтаж",
    "CONSUMABLE_FOR_SERVICE": "Расходные материалы услуги",
    "INCIDENTAL": "Сопутствующее",
    "UNKNOWN": "Связь не определена",
}


@dataclass
class CategoryOpportunity:
    procurement_id: int
    category_id: str
    category_name: str
    subcategory_id: Optional[str] = None
    subcategory_name: Optional[str] = None
    commercial_medal: str = "UNASSIGNED"  # GOLD, SILVER, BRONZE, WOOD, UNASSIGNED
    commercial_state: str = "CONFIRMED"
    medal_authority: str = "SYSTEM_DEFAULT"
    product_relation: str = "EMBEDDED_IN_WORKS"
    material_count: int = 0
    position_count: int = 0
    quantities_by_unit: List[Dict[str, Any]] = field(default_factory=list)
    potential_supply_value_rub: Optional[float] = None
    potential_supply_value_method: str = "NOT_AVAILABLE"
    facts_with_quantity: int = 0
    facts_with_value: int = 0
    evidence_count: int = 0
    latest_confirmed_at: Optional[str] = None
    confirmed_materials: List[Dict[str, Any]] = field(default_factory=list)


class CategoryOpportunityService:
    """Read model service for extracting and aggregating Category Opportunities."""

    def __init__(self, db_manager: Any = None):
        self.db = db_manager

    def get_opportunities_for_procurements(
        self, procurement_ids: Sequence[int]
    ) -> Dict[int, List[CategoryOpportunity]]:
        """Bulk fetch category opportunities for multiple procurements in 1-2 SQL queries (Zero N+1)."""
        if not procurement_ids:
            return {}

        pids = list(set(procurement_ids))
        
        # Fixture / In-memory check for TEST_MULTI_MEDAL or simulated test environments
        result: Dict[int, List[CategoryOpportunity]] = {pid: [] for pid in pids}
        
        if self.db is None:
            return result

        try:
            # Query confirmed match details & entities for pids
            sql = """
            SELECT 
                d.procurement_id,
                d.category_code,
                d.subcategory_code,
                d.matched_term,
                d.page_or_sheet,
                d.row_number,
                d.context_before,
                d.context_after,
                d.validation_status,
                d.validated_at,
                q.procurement_scope_type,
                q.normalized_nmck_rub,
                q.research_prior_band
            FROM document_match_details d
            JOIN document_processing_queue q ON d.procurement_id = q.procurement_id
            WHERE d.procurement_id = ANY(%s)
              AND d.validation_status = 'CONFIRMED'
            """
            rows = self.db.execute_query('document_intelligence', sql, (pids,), fetch=True)
            if not rows:
                return result

            # Group by procurement_id -> category_code
            grouped: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
            for r in rows:
                # Handle dict or tuple
                if isinstance(r, dict):
                    pid = r['procurement_id']
                    cat = r['category_code']
                    row_dict = r
                else:
                    pid, cat = r[0], r[1]
                    row_dict = {
                        'procurement_id': r[0], 'category_code': r[1], 'subcategory_code': r[2],
                        'matched_term': r[3], 'page_or_sheet': r[4], 'row_number': r[5],
                        'context_before': r[6], 'context_after': r[7], 'validation_status': r[8],
                        'validated_at': r[9], 'procurement_scope_type': r[10],
                        'normalized_nmck_rub': r[11], 'research_prior_band': r[12]
                    }

                grouped.setdefault(pid, {}).setdefault(cat, []).append(row_dict)

            for pid, cat_map in grouped.items():
                opps = []
                for cat_code, items in cat_map.items():
                    opp = self._build_opportunity(pid, cat_code, items)
                    opps.append(opp)
                result[pid] = opps

        except Exception as e:
            logger.error("Error bulk fetching category opportunities: %s", e)

        return result

    def get_opportunities_for_procurement(
        self, procurement_id: int
    ) -> List[CategoryOpportunity]:
        """Fetch category opportunities for a single procurement."""
        res = self.get_opportunities_for_procurements([procurement_id])
        return res.get(procurement_id, [])

    def _build_opportunity(
        self, procurement_id: int, category_code: str, items: List[Dict[str, Any]]
    ) -> CategoryOpportunity:
        first = items[0]
        cat_name = CATEGORY_NAMES.get(category_code, category_code.replace("_", " ").title())
        
        # Aggregate unique materials vs total evidence
        materials_seen: Set[str] = set()
        confirmed_materials: List[Dict[str, Any]] = []
        
        unit_map: Dict[str, Dict[str, Any]] = {}
        total_val = 0.0
        val_count = 0
        qty_count = 0

        for it in items:
            term = (it.get('matched_term') or 'Неизвестный материал').strip()
            norm_term = term.lower()
            if norm_term not in materials_seen:
                materials_seen.add(norm_term)
                confirmed_materials.append({
                    'material_name': term,
                    'page_or_sheet': it.get('page_or_sheet'),
                    'row_number': it.get('row_number'),
                    'context': f"{it.get('context_before') or ''} {it.get('context_after') or ''}".strip()
                })

            # Check quantity / value if present in structured facts (simulated/passed)
            qty = it.get('quantity_value')
            unit = it.get('quantity_unit_normalized') or it.get('quantity_unit_raw') or 'pcs'
            if qty is not None:
                qty_count += 1
                if unit not in unit_map:
                    unit_map[unit] = {'unit': unit, 'quantity': 0.0, 'positions': 0}
                unit_map[unit]['quantity'] += float(qty)
                unit_map[unit]['positions'] += 1

            val = it.get('total_price_value')
            if val is not None:
                val_count += 1
                total_val += float(val)

        # Determine supply value method
        val_method = "NOT_AVAILABLE"
        final_val = None
        if val_count > 0:
            final_val = total_val
            val_method = "EXPLICIT_LINE_TOTAL"
        else:
            scope = first.get('procurement_scope_type')
            nmck = first.get('normalized_nmck_rub')
            # Direct goods single category upper bound check
            if scope == 'DIRECT_GOODS' and nmck and len(items) > 0:
                final_val = float(nmck)
                val_method = "DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND"

        # Product relation mapping based on scope
        scope = first.get('procurement_scope_type') or 'WORKS_WITH_EMBEDDED_PRODUCTS'
        rel_map = {
            'DIRECT_GOODS': 'PRIMARY_SUBJECT',
            'WORKS_WITH_EMBEDDED_PRODUCTS': 'EMBEDDED_IN_WORKS',
            'DESIGN_PROJECT': 'SPECIFIED_IN_PROJECT',
            'EQUIPMENT_AND_INSTALLATION': 'EQUIPMENT_WITH_INSTALLATION',
            'SERVICE_WITH_CONSUMABLES': 'CONSUMABLE_FOR_SERVICE',
        }
        rel = rel_map.get(scope, 'EMBEDDED_IN_WORKS')

        # Medal determination (GOLD, SILVER, BRONZE, WOOD)
        medal = first.get('research_prior_band') or 'UNASSIGNED'
        if medal not in ('GOLD', 'SILVER', 'BRONZE', 'WOOD'):
            medal = 'UNASSIGNED'

        return CategoryOpportunity(
            procurement_id=procurement_id,
            category_id=category_code,
            category_name=cat_name,
            subcategory_id=first.get('subcategory_code'),
            subcategory_name=first.get('subcategory_code'),
            commercial_medal=medal,
            commercial_state='CONFIRMED',
            medal_authority='SYSTEM_DEFAULT',
            product_relation=rel,
            material_count=len(materials_seen),
            position_count=len(items),
            quantities_by_unit=list(unit_map.values()),
            potential_supply_value_rub=final_val,
            potential_supply_value_method=val_method,
            facts_with_quantity=qty_count,
            facts_with_value=val_count,
            evidence_count=len(items),
            latest_confirmed_at=str(first.get('validated_at') or ''),
            confirmed_materials=confirmed_materials
        )
