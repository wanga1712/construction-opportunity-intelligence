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
    commercial_state: str = "UNCONFIRMED"  # CONFIRMED, UNCONFIRMED, REJECTED
    medal_authority: str = "UNANNOTATED"  # EXPERT_ANNOTATION, MODEL_PROMOTED, UNANNOTATED
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
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[str] = None


class CategoryOpportunityService:
    """Read model service for extracting and aggregating Category Opportunities."""

    def __init__(self, db_manager: Any = None):
        self.db = db_manager
        self.last_query_status: Dict[str, Dict[str, Any]] = {
            'document_intelligence': {'status': 'UNEXECUTED', 'rows': 0, 'error': None},
            'crm_procurement_category_opportunities': {'status': 'UNEXECUTED', 'rows': 0, 'error': None},
            'crm_v3_expert_annotations': {'status': 'UNEXECUTED', 'rows': 0, 'error': None},
        }

    def _safe_exec(self, query_key: str, db_alias: str, sql: str, params: tuple) -> List[Any]:
        if self.db is None:
            self.last_query_status[query_key] = {'status': 'QUERY_OK_ZERO_ROWS', 'rows': 0, 'error': None}
            return []
        try:
            try:
                rows = self.db.execute_query(db_alias, sql, params, fetch=True)
            except TypeError:
                rows = self.db.execute_query(sql, params)
            
            rows_list = list(rows or [])
            if len(rows_list) > 0:
                self.last_query_status[query_key] = {'status': 'QUERY_OK_ROWS', 'rows': len(rows_list), 'error': None}
            else:
                self.last_query_status[query_key] = {'status': 'QUERY_OK_ZERO_ROWS', 'rows': 0, 'error': None}
            return rows_list
        except Exception as e:
            logger.error("Query error on %s (%s): %s", query_key, db_alias, e)
            self.last_query_status[query_key] = {'status': 'QUERY_ERROR', 'rows': 0, 'error': str(e)}
            return []

    def get_opportunities_for_procurements(
        self, procurement_ids: Sequence[int]
    ) -> Dict[int, List[CategoryOpportunity]]:
        """Bulk fetch category opportunities for multiple procurements in 1-2 SQL queries (Zero N+1)."""
        if not procurement_ids:
            return {}

        pids = list(set(procurement_ids))
        result: Dict[int, List[CategoryOpportunity]] = {pid: [] for pid in pids}
        
        if self.db is None:
            return result

        try:
            # Step 1: Query match details JOIN queue LEFT JOIN structured_entities from document_intelligence
            sql = """
            SELECT 
                d.id AS detail_id,
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
                q.research_prior_band,
                s.id AS structured_entity_id,
                s.quantity_value,
                s.quantity_unit_normalized,
                s.quantity_unit_raw,
                s.unit_price_value,
                s.total_price_value,
                s.product_relation
            FROM document_match_details d
            JOIN document_processing_queue q ON d.procurement_id = q.procurement_id
            LEFT JOIN structured_entities s ON d.id = s.detail_id
            WHERE d.procurement_id = ANY(%s)
              AND d.validation_status = 'CONFIRMED'
            """
            rows = self._safe_exec('document_intelligence', 'document_intelligence', sql, (pids,))
            if not rows:
                return result

            # Step 2: Fetch Category Commercial Authority from crm DB
            authority_map = self._fetch_commercial_authorities(pids)

            # Group rows by procurement_id -> category_code
            grouped: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
            for r in rows:
                if isinstance(r, dict):
                    pid = r['procurement_id']
                    cat = r['category_code']
                    row_dict = r
                else:
                    pid, cat = r[1], r[2]
                    row_dict = {
                        'detail_id': r[0],
                        'procurement_id': r[1], 'category_code': r[2], 'subcategory_code': r[3],
                        'matched_term': r[4], 'page_or_sheet': r[5], 'row_number': r[6],
                        'context_before': r[7], 'context_after': r[8], 'validation_status': r[9],
                        'validated_at': r[10], 'procurement_scope_type': r[11],
                        'normalized_nmck_rub': r[12], 'research_prior_band': r[13],
                        'structured_entity_id': r[14] if len(r) > 14 else None,
                        'quantity_value': r[15] if len(r) > 15 else None,
                        'quantity_unit_normalized': r[16] if len(r) > 16 else None,
                        'quantity_unit_raw': r[17] if len(r) > 17 else None,
                        'unit_price_value': r[18] if len(r) > 18 else None,
                        'total_price_value': r[19] if len(r) > 19 else None,
                        'product_relation': r[20] if len(r) > 20 else None,
                    }

                grouped.setdefault(pid, {}).setdefault(cat, []).append(row_dict)

            for pid, cat_map in grouped.items():
                opps = []
                confirmed_category_count = len(cat_map)
                for cat_code, items in cat_map.items():
                    auth_info = authority_map.get((pid, cat_code))
                    opp = self._build_opportunity(pid, cat_code, items, confirmed_category_count, auth_info)
                    opps.append(opp)
                result[pid] = opps

        except Exception as e:
            logger.error("Error bulk fetching category opportunities: %s", e)

        return result

    def _fetch_commercial_authorities(self, pids: List[int]) -> Dict[tuple[int, str], Dict[str, Any]]:
        """Fetch authority rows from crm_procurement_category_opportunities and crm_v3_expert_annotations."""
        authority_map: Dict[tuple[int, str], Dict[str, Any]] = {}
        
        # 1. Query crm_procurement_category_opportunities
        sql_opps = """
        SELECT 
            procurement_id,
            commercial_category_code,
            current_effective_medal,
            confirmed_base_medal,
            commercial_state,
            medal_authority,
            confirmed_by,
            confirmed_at,
            updated_at
        FROM crm_procurement_category_opportunities
        WHERE procurement_id = ANY(%s)
        """
        rows = self._safe_exec('crm_procurement_category_opportunities', 'crm', sql_opps, (pids,))
        for r in rows:
            if isinstance(r, dict):
                cat = r.get('commercial_category_code')
                if not cat:
                    continue
                pid = r.get('procurement_id')
                medal = r.get('current_effective_medal') or r.get('confirmed_base_medal')
                state = r.get('commercial_state') or 'CONFIRMED'
                auth = r.get('medal_authority') or 'MODEL_PROMOTED'
                by = r.get('confirmed_by')
                at = str(r.get('confirmed_at') or r.get('updated_at') or '')
            elif isinstance(r, (list, tuple)) and len(r) >= 9:
                pid, cat = r[0], r[1]
                medal = r[2] or r[3]
                state = r[4] or 'CONFIRMED'
                auth = r[5] or 'MODEL_PROMOTED'
                by = r[6]
                at = str(r[7] or r[8] or '')
            else:
                continue

            if pid is not None and cat and medal in ('GOLD', 'SILVER', 'BRONZE', 'WOOD'):
                authority_map[(int(pid), str(cat))] = {
                    'medal': medal,
                    'state': state,
                    'authority': auth,
                    'confirmed_by': by,
                    'confirmed_at': at,
                }

        # 2. Check crm_v3_expert_annotations (takes precedence over model_promoted)
        sql_exp = """
        SELECT 
            procurement_id,
            payload,
            created_at,
            created_by
        FROM crm_v3_expert_annotations
        WHERE procurement_id = ANY(%s)
          AND is_current = TRUE
        """
        exp_rows = self._safe_exec('crm_v3_expert_annotations', 'crm', sql_exp, (pids,))
        for r in exp_rows:
            if isinstance(r, dict):
                pid = r.get('procurement_id')
                payload = r.get('payload') or {}
                created_at = str(r.get('created_at') or '')
                created_by = r.get('created_by')
            elif isinstance(r, (list, tuple)) and len(r) >= 4:
                pid = r[0]
                payload = r[1] or {}
                created_at = str(r[2] or '')
                created_by = r[3]
            else:
                continue

            if pid is not None and isinstance(payload, dict):
                cat_medals = payload.get('category_medals') or {}
                exp_medal = payload.get('expert_medal')
                if exp_medal and 'category_code' in payload:
                    cat_medals[payload['category_code']] = exp_medal

                for cat_code, med in cat_medals.items():
                    if med in ('GOLD', 'SILVER', 'BRONZE', 'WOOD'):
                        authority_map[(int(pid), str(cat_code))] = {
                            'medal': med,
                            'state': 'CONFIRMED',
                            'authority': 'EXPERT_ANNOTATION',
                            'confirmed_by': created_by,
                            'confirmed_at': created_at,
                        }

        return authority_map

    def get_opportunities_for_procurement(
        self, procurement_id: int
    ) -> List[CategoryOpportunity]:
        """Fetch category opportunities for a single procurement."""
        res = self.get_opportunities_for_procurements([procurement_id])
        return res.get(procurement_id, [])

    def _build_opportunity(
        self,
        procurement_id: int,
        category_code: str,
        items: List[Dict[str, Any]],
        confirmed_category_count: int,
        auth_info: Optional[Dict[str, Any]] = None,
    ) -> CategoryOpportunity:
        first = items[0]
        cat_name = CATEGORY_NAMES.get(category_code, category_code.replace("_", " ").title())
        
        # Aggregate unique materials, distinct detail_ids and structured_entity_ids
        materials_seen: Set[str] = set()
        detail_ids_seen: Set[Any] = set()
        structured_entity_ids_seen: Set[Any] = set()
        processed_value_keys: Set[Any] = set()
        
        confirmed_materials: List[Dict[str, Any]] = []
        unit_map: Dict[str, Dict[str, Any]] = {}
        total_val = 0.0
        val_count = 0
        qty_count = 0
        structured_rel: Optional[str] = None

        for it in items:
            detail_id = it.get('detail_id')
            if detail_id is not None:
                detail_ids_seen.add(detail_id)
            entity_id = it.get('structured_entity_id')
            if entity_id is not None:
                structured_entity_ids_seen.add(entity_id)

            term = (it.get('matched_term') or 'Неизвестный материал').strip()
            norm_term = term.lower()
            if norm_term not in materials_seen:
                materials_seen.add(norm_term)
                confirmed_materials.append({
                    'material_name': term,
                    'page_or_sheet': it.get('page_or_sheet'),
                    'row_number': it.get('row_number'),
                    'context': f"{it.get('context_before') or ''} {it.get('context_after') or ''}".strip(),
                    'detail_id': detail_id,
                    'structured_entity_id': entity_id,
                })

            if not structured_rel and it.get('product_relation'):
                structured_rel = it.get('product_relation')

            # Check quantity / value from structured_entities
            qty = it.get('quantity_value')
            unit = it.get('quantity_unit_normalized') or it.get('quantity_unit_raw') or 'pcs'
            if qty is not None:
                qty_count += 1
                if unit not in unit_map:
                    unit_map[unit] = {'unit': unit, 'quantity': 0.0, 'positions': 0}
                unit_map[unit]['quantity'] += float(qty)
                unit_map[unit]['positions'] += 1

            # Prevent double-counting price totals across 1:N structured entities per detail_id
            val_key = entity_id if entity_id is not None else detail_id
            val = it.get('total_price_value')
            unit_p = it.get('unit_price_value')
            
            if val_key is None or val_key not in processed_value_keys:
                if val_key is not None:
                    processed_value_keys.add(val_key)

                if val is not None:
                    val_count += 1
                    total_val += float(val)
                elif unit_p is not None and qty is not None:
                    val_count += 1
                    total_val += float(unit_p) * float(qty)

        # Determine supply value method
        val_method = "NOT_AVAILABLE"
        final_val = None
        if val_count > 0:
            final_val = total_val
            val_method = "EXPLICIT_LINE_TOTAL"
        else:
            scope = first.get('procurement_scope_type')
            nmck = first.get('normalized_nmck_rub')
            # Direct goods single category upper bound check: ONLY if confirmed_category_count == 1
            if scope == 'DIRECT_GOODS' and nmck is not None and confirmed_category_count == 1:
                final_val = float(nmck)
                val_method = "DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND"

        # Product relation mapping
        if structured_rel and structured_rel in RELATION_DISPLAY:
            rel = structured_rel
        else:
            scope = first.get('procurement_scope_type') or 'WORKS_WITH_EMBEDDED_PRODUCTS'
            rel_map = {
                'DIRECT_GOODS': 'PRIMARY_SUBJECT',
                'WORKS_WITH_EMBEDDED_PRODUCTS': 'EMBEDDED_IN_WORKS',
                'DESIGN_PROJECT': 'SPECIFIED_IN_PROJECT',
                'EQUIPMENT_AND_INSTALLATION': 'EQUIPMENT_WITH_INSTALLATION',
                'SERVICE_WITH_CONSUMABLES': 'CONSUMABLE_FOR_SERVICE',
            }
            rel = rel_map.get(scope, 'EMBEDDED_IN_WORKS')

        # Authority Resolution for Commercial Medal (CATEGORY_MEDAL_FROM_RESEARCH_PRIOR = NO)
        if auth_info:
            medal = auth_info.get('medal', 'UNASSIGNED')
            state = auth_info.get('state', 'CONFIRMED')
            authority = auth_info.get('authority', 'MODEL_PROMOTED')
            conf_by = auth_info.get('confirmed_by')
            conf_at = auth_info.get('confirmed_at')
        else:
            # Unannotated -> UNASSIGNED / UNCONFIRMED / UNANNOTATED
            medal = 'UNASSIGNED'
            state = 'UNCONFIRMED'
            authority = 'UNANNOTATED'
            conf_by = None
            conf_at = None

        if medal not in ('GOLD', 'SILVER', 'BRONZE', 'WOOD'):
            medal = 'UNASSIGNED'

        latest_confirmed = conf_at or str(first.get('validated_at') or '')
        pos_count = len(detail_ids_seen) if detail_ids_seen else len(items)
        ev_count = len(detail_ids_seen) if detail_ids_seen else len(items)

        return CategoryOpportunity(
            procurement_id=procurement_id,
            category_id=category_code,
            category_name=cat_name,
            subcategory_id=first.get('subcategory_code'),
            subcategory_name=first.get('subcategory_code'),
            commercial_medal=medal,
            commercial_state=state,
            medal_authority=authority,
            product_relation=rel,
            material_count=len(materials_seen),
            position_count=pos_count,
            quantities_by_unit=list(unit_map.values()),
            potential_supply_value_rub=final_val,
            potential_supply_value_method=val_method,
            facts_with_quantity=qty_count,
            facts_with_value=val_count,
            evidence_count=ev_count,
            latest_confirmed_at=latest_confirmed,
            confirmed_materials=confirmed_materials,
            confirmed_by=conf_by,
            confirmed_at=conf_at,
        )
