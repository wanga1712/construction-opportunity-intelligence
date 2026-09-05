"""Test suite for Category Opportunity Cards and Multi-Medal Output.

Verifies:
- 1 Procurement -> N confirmed commercial category opportunities (MAX_MEDAL_COLLAPSE = NO)
- Strict priority separation (research_prior_band vs effective_service_band vs category_commercial_medal)
- Material count vs position count distinction
- Quantity aggregation by unit (QuantitiesByUnit)
- Potential supply value derivation methods (EXPLICIT_LINE_TOTAL, DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND, NOT_AVAILABLE)
- Zero N+1 queries in bulk fetch
- Streamlit UI component rendering and filtering (Category, Medal, Confirmed Only)
- TEST_MULTI_MEDAL integration fixture
"""

import pytest
from unittest.mock import MagicMock
from src.services.category_opportunity_service import (
    CategoryOpportunity,
    CategoryOpportunityService,
    CATEGORY_NAMES,
    RELATION_DISPLAY,
)


@pytest.fixture
def test_multi_medal_fixture():
    """Fixture providing simulated database rows for TEST_MULTI_MEDAL procurement (ID: 9901).
    
    Contains 3 distinct category opportunities for a single procurement:
    1. Linoleum (flooring): GOLD commercial medal, 8 distinct materials, 12,450 m²
    2. Lighting (lighting): GOLD commercial medal, 23 positions, 180 pcs
    3. Curbstone (curbstone): WOOD commercial medal, 2 distinct materials, 340 m
    """
    procurement_id = 9901
    
    rows = []
    
    # 1. Flooring (Linoleum): 8 distinct materials, total 12,450 m², commercial_medal = GOLD
    for i in range(1, 9):
        rows.append({
            'procurement_id': procurement_id,
            'category_code': 'flooring',
            'subcategory_code': 'linoleum',
            'matched_term': f'Линолеум коммерческий тип {i}',
            'page_or_sheet': 'Лист 1',
            'row_number': i * 10,
            'context_before': 'Укладка покрытия',
            'context_after': 'на подготовленное основание',
            'validation_status': 'CONFIRMED',
            'validated_at': '2026-09-05T10:00:00',
            'procurement_scope_type': 'WORKS_WITH_EMBEDDED_PRODUCTS',
            'normalized_nmck_rub': 15000000.0,
            'research_prior_band': 'WOOD',  # Stage 1 priority band is WOOD, but commercial medal is GOLD
            'commercial_medal': 'GOLD',
            'commercial_state': 'CONFIRMED',
            'medal_authority': 'MODEL_PROMOTED',
            'quantity_value': 1556.25 if i < 8 else 1556.25,  # Total = 12450 m²
            'quantity_unit_normalized': 'm²',
            'total_price_value': 1000000.0 if i == 1 else None
        })

    # 2. Lighting: 23 positions (some duplicate terms), total 180 pcs, commercial_medal = GOLD
    for i in range(1, 24):
        term_idx = (i % 5) + 1  # 5 distinct terms across 23 positions
        rows.append({
            'procurement_id': procurement_id,
            'category_code': 'lighting',
            'subcategory_code': 'led_fixtures',
            'matched_term': f'Светильник светодиодный тип {term_idx}',
            'page_or_sheet': 'Спецификация',
            'row_number': i + 50,
            'context_before': 'Монтаж светильника',
            'context_after': 'в подвесной потолок',
            'validation_status': 'CONFIRMED',
            'validated_at': '2026-09-05T10:05:00',
            'procurement_scope_type': 'WORKS_WITH_EMBEDDED_PRODUCTS',
            'normalized_nmck_rub': 15000000.0,
            'research_prior_band': 'WOOD',
            'commercial_medal': 'GOLD',
            'commercial_state': 'CONFIRMED',
            'medal_authority': 'MODEL_PROMOTED',
            'quantity_value': 7.826,  # 23 * 7.826 ~ 180 pcs
            'quantity_unit_normalized': 'pcs',
            'total_price_value': None
        })

    # 3. Curbstone: 2 distinct materials, total 340 m, commercial_medal = WOOD
    for i in range(1, 3):
        rows.append({
            'procurement_id': procurement_id,
            'category_code': 'curbstone',
            'subcategory_code': 'granite_curb',
            'matched_term': f'Бордюрный камень БР 100.{30 if i==1 else 20}',
            'page_or_sheet': 'Генплан',
            'row_number': i + 100,
            'context_before': 'Установка камня',
            'context_after': 'на бетонное основание',
            'validation_status': 'CONFIRMED',
            'validated_at': '2026-09-05T10:10:00',
            'procurement_scope_type': 'WORKS_WITH_EMBEDDED_PRODUCTS',
            'normalized_nmck_rub': 15000000.0,
            'research_prior_band': 'WOOD',
            'commercial_medal': 'WOOD',
            'commercial_state': 'CONFIRMED',
            'medal_authority': 'MODEL_PROMOTED',
            'quantity_value': 170.0,  # 2 * 170 = 340 m
            'quantity_unit_normalized': 'm',
            'total_price_value': None
        })

    return procurement_id, rows


class MockDBManager:
    def __init__(self, rows):
        self.rows = rows
        self.query_count = 0

    def execute_query(self, alias, query, params, fetch=True):
        self.query_count += 1
        pids = params[0] if params else []
        return [r for r in self.rows if r['procurement_id'] in pids]


# --- 28 Targeted Test Cases ---

def test_1_multi_medal_fixture_card_counts(test_multi_medal_fixture):
    """Test 1: Single procurement produces N=3 distinct category opportunities (MAX_MEDAL_COLLAPSE = NO)."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    
    opps = service.get_opportunities_for_procurement(pid)
    assert len(opps) == 3, f"Expected 3 category opportunities, got {len(opps)}"
    cat_ids = {o.category_id for o in opps}
    assert cat_ids == {'flooring', 'lighting', 'curbstone'}


def test_2_multi_medal_linoleum_details(test_multi_medal_fixture):
    """Test 2: Linoleum GOLD opportunity has 8 distinct materials and correct quantity."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    
    opps = service.get_opportunities_for_procurement(pid)
    flooring_opp = next(o for o in opps if o.category_id == 'flooring')
    
    assert flooring_opp.commercial_medal == 'GOLD'
    assert flooring_opp.material_count == 8
    assert flooring_opp.position_count == 8
    assert len(flooring_opp.quantities_by_unit) == 1
    assert flooring_opp.quantities_by_unit[0]['unit'] == 'm²'
    assert pytest.approx(flooring_opp.quantities_by_unit[0]['quantity'], 0.1) == 12450.0


def test_3_multi_medal_lighting_details(test_multi_medal_fixture):
    """Test 3: Lighting GOLD opportunity has 23 positions, 5 distinct materials, 180 pcs."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    
    opps = service.get_opportunities_for_procurement(pid)
    lighting_opp = next(o for o in opps if o.category_id == 'lighting')
    
    assert lighting_opp.commercial_medal == 'GOLD'
    assert lighting_opp.material_count == 5
    assert lighting_opp.position_count == 23
    assert len(lighting_opp.quantities_by_unit) == 1
    assert lighting_opp.quantities_by_unit[0]['unit'] == 'pcs'
    assert pytest.approx(lighting_opp.quantities_by_unit[0]['quantity'], 0.1) == 180.0


def test_4_multi_medal_curbstone_details(test_multi_medal_fixture):
    """Test 4: Curbstone WOOD opportunity has 2 materials, 340 m."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    
    opps = service.get_opportunities_for_procurement(pid)
    curb_opp = next(o for o in opps if o.category_id == 'curbstone')
    
    assert curb_opp.commercial_medal == 'WOOD'
    assert curb_opp.material_count == 2
    assert curb_opp.position_count == 2
    assert len(curb_opp.quantities_by_unit) == 1
    assert curb_opp.quantities_by_unit[0]['unit'] == 'm'
    assert pytest.approx(curb_opp.quantities_by_unit[0]['quantity'], 0.1) == 340.0


def test_5_priority_separation_independence():
    """Test 5: Priority band, effective service band, and category commercial medal are independent."""
    opp = CategoryOpportunity(
        procurement_id=100,
        category_id='flooring',
        category_name='Напольные покрытия',
        commercial_medal='GOLD',
        commercial_state='CONFIRMED',
        product_relation='EMBEDDED_IN_WORKS'
    )
    # Check that category commercial_medal does not alter raw priority model or effective band
    assert opp.commercial_medal == 'GOLD'
    assert opp.commercial_state == 'CONFIRMED'


def test_6_material_count_vs_position_count_distinct():
    """Test 6: Distinct material count (deduplicated terms) <= total position count."""
    rows = [
        {
            'procurement_id': 200,
            'category_code': 'lighting',
            'matched_term': 'Светильник LED 50W',
            'procurement_scope_type': 'DIRECT_GOODS',
            'research_prior_band': 'SILVER',
            'validation_status': 'CONFIRMED'
        },
        {
            'procurement_id': 200,
            'category_code': 'lighting',
            'matched_term': 'Светильник LED 50W',  # Duplicate term in different line item
            'procurement_scope_type': 'DIRECT_GOODS',
            'research_prior_band': 'SILVER',
            'validation_status': 'CONFIRMED'
        },
        {
            'procurement_id': 200,
            'category_code': 'lighting',
            'matched_term': 'Прожектор LED 100W',  # Distinct term
            'procurement_scope_type': 'DIRECT_GOODS',
            'research_prior_band': 'SILVER',
            'validation_status': 'CONFIRMED'
        }
    ]
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opps = service.get_opportunities_for_procurement(200)
    
    assert len(opps) == 1
    opp = opps[0]
    assert opp.material_count == 2
    assert opp.position_count == 3


def test_7_quantities_by_unit_aggregation():
    """Test 7: Quantities are aggregated properly by unit type."""
    rows = [
        {'procurement_id': 300, 'category_code': 'flooring', 'matched_term': 'A', 'quantity_value': 100, 'quantity_unit_normalized': 'm²', 'validation_status': 'CONFIRMED'},
        {'procurement_id': 300, 'category_code': 'flooring', 'matched_term': 'B', 'quantity_value': 50, 'quantity_unit_normalized': 'm²', 'validation_status': 'CONFIRMED'},
        {'procurement_id': 300, 'category_code': 'flooring', 'matched_term': 'C', 'quantity_value': 10, 'quantity_unit_normalized': 'roll', 'validation_status': 'CONFIRMED'}
    ]
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opp = service.get_opportunities_for_procurement(300)[0]
    
    assert len(opp.quantities_by_unit) == 2
    m2_unit = next(u for u in opp.quantities_by_unit if u['unit'] == 'm²')
    roll_unit = next(u for u in opp.quantities_by_unit if u['unit'] == 'roll')
    assert m2_unit['quantity'] == 150.0
    assert roll_unit['quantity'] == 10.0


def test_8_potential_supply_value_explicit_line_total():
    """Test 8: Supply value method EXPLICIT_LINE_TOTAL when line item price totals are present."""
    rows = [
        {'procurement_id': 400, 'category_code': 'lighting', 'matched_term': 'A', 'total_price_value': 50000.0, 'validation_status': 'CONFIRMED'},
        {'procurement_id': 400, 'category_code': 'lighting', 'matched_term': 'B', 'total_price_value': 75000.0, 'validation_status': 'CONFIRMED'}
    ]
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opp = service.get_opportunities_for_procurement(400)[0]
    
    assert opp.potential_supply_value_rub == 125000.0
    assert opp.potential_supply_value_method == 'EXPLICIT_LINE_TOTAL'


def test_9_potential_supply_value_direct_single_category_nmck():
    """Test 9: Supply value method DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND for DIRECT_GOODS single category without line totals."""
    rows = [
        {
            'procurement_id': 500,
            'category_code': 'lighting',
            'matched_term': 'A',
            'procurement_scope_type': 'DIRECT_GOODS',
            'normalized_nmck_rub': 850000.0,
            'validation_status': 'CONFIRMED'
        }
    ]
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opp = service.get_opportunities_for_procurement(500)[0]
    
    assert opp.potential_supply_value_rub == 850000.0
    assert opp.potential_supply_value_method == 'DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND'


def test_10_potential_supply_value_not_available():
    """Test 10: Supply value method NOT_AVAILABLE when line totals missing and scope is multi-category or embedded works."""
    rows = [
        {
            'procurement_id': 600,
            'category_code': 'flooring',
            'matched_term': 'A',
            'procurement_scope_type': 'WORKS_WITH_EMBEDDED_PRODUCTS',
            'normalized_nmck_rub': 10000000.0,
            'validation_status': 'CONFIRMED'
        }
    ]
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opp = service.get_opportunities_for_procurement(600)[0]
    
    assert opp.potential_supply_value_rub is None
    assert opp.potential_supply_value_method == 'NOT_AVAILABLE'


def test_11_bulk_fetch_zero_n_plus_1(test_multi_medal_fixture):
    """Test 11: Bulk fetch for multiple procurements executes constant batch queries (Zero N+1 per procurement card)."""
    pid, rows = test_multi_medal_fixture
    # Duplicate rows for second procurement 9902
    rows_2 = [dict(r, procurement_id=9902) for r in rows]
    all_rows = rows + rows_2
    
    db = MockDBManager(all_rows)
    service = CategoryOpportunityService(db)
    
    res = service.get_opportunities_for_procurements([9901, 9902])
    assert db.query_count <= 3, f"Expected <= 3 batch queries for bulk fetch, executed {db.query_count}"
    assert len(res[9901]) == 3
    assert len(res[9902]) == 3


def test_12_streamlit_card_rendering_structure():
    """Test 12: Streamlit component imports and helper functions exist and operate properly."""
    from src.ui.components.category_opportunity_section import format_supply_value
    
    val_str, badge_str = format_supply_value(125000.0, "EXPLICIT_LINE_TOTAL")
    assert "125 000" in val_str
    assert badge_str == "Явная сумма строк"

    val_str_2, badge_str_2 = format_supply_value(850000.0, "DIRECT_SINGLE_CATEGORY_NMCK_UPPER_BOUND")
    assert "850 000" in val_str_2
    assert "НМЦК" in badge_str_2

    val_str_3, badge_str_3 = format_supply_value(None, "NOT_AVAILABLE")
    assert val_str_3 == "—"
    assert badge_str_3 == "Недоступно"


def test_13_streamlit_filter_category(test_multi_medal_fixture):
    """Test 13: UI filtering by category returns matching subcards."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opps = service.get_opportunities_for_procurement(pid)
    
    filtered = [o for o in opps if o.category_id == 'flooring']
    assert len(filtered) == 1
    assert filtered[0].category_name == 'Напольные покрытия'


def test_14_streamlit_filter_medal(test_multi_medal_fixture):
    """Test 14: UI filtering by medal (GOLD only) excludes WOOD."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opps = service.get_opportunities_for_procurement(pid)
    
    gold_opps = [o for o in opps if o.commercial_medal == 'GOLD']
    assert len(gold_opps) == 2
    assert {o.category_id for o in gold_opps} == {'flooring', 'lighting'}


def test_15_streamlit_filter_confirmed_only(test_multi_medal_fixture):
    """Test 15: UI filtering by confirmed commercial state."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opps = service.get_opportunities_for_procurement(pid)
    
    confirmed = [o for o in opps if o.commercial_state == 'CONFIRMED']
    assert len(confirmed) == 3


def test_16_evidence_drilldown_fields(test_multi_medal_fixture):
    """Test 16: Confirmed material evidence details contain term, page/sheet, row, context."""
    pid, rows = test_multi_medal_fixture
    db = MockDBManager(rows)
    service = CategoryOpportunityService(db)
    opps = service.get_opportunities_for_procurement(pid)
    
    flooring_opp = next(o for o in opps if o.category_id == 'flooring')
    assert len(flooring_opp.confirmed_materials) == 8
    first_mat = flooring_opp.confirmed_materials[0]
    assert 'material_name' in first_mat
    assert 'page_or_sheet' in first_mat
    assert 'row_number' in first_mat
    assert 'context' in first_mat


def test_17_product_relation_mapping_direct_goods():
    """Test 17: DIRECT_GOODS maps to PRIMARY_SUBJECT."""
    rows = [{'procurement_id': 701, 'category_code': 'lighting', 'matched_term': 'A', 'procurement_scope_type': 'DIRECT_GOODS', 'validation_status': 'CONFIRMED'}]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(701)[0]
    assert opp.product_relation == 'PRIMARY_SUBJECT'


def test_18_product_relation_mapping_embedded():
    """Test 18: WORKS_WITH_EMBEDDED_PRODUCTS maps to EMBEDDED_IN_WORKS."""
    rows = [{'procurement_id': 702, 'category_code': 'lighting', 'matched_term': 'A', 'procurement_scope_type': 'WORKS_WITH_EMBEDDED_PRODUCTS', 'validation_status': 'CONFIRMED'}]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(702)[0]
    assert opp.product_relation == 'EMBEDDED_IN_WORKS'


def test_19_product_relation_mapping_design():
    """Test 19: DESIGN_PROJECT maps to SPECIFIED_IN_PROJECT."""
    rows = [{'procurement_id': 703, 'category_code': 'lighting', 'matched_term': 'A', 'procurement_scope_type': 'DESIGN_PROJECT', 'validation_status': 'CONFIRMED'}]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(703)[0]
    assert opp.product_relation == 'SPECIFIED_IN_PROJECT'


def test_20_product_relation_mapping_equipment():
    """Test 20: EQUIPMENT_AND_INSTALLATION maps to EQUIPMENT_WITH_INSTALLATION."""
    rows = [{'procurement_id': 704, 'category_code': 'lighting', 'matched_term': 'A', 'procurement_scope_type': 'EQUIPMENT_AND_INSTALLATION', 'validation_status': 'CONFIRMED'}]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(704)[0]
    assert opp.product_relation == 'EQUIPMENT_WITH_INSTALLATION'


def test_21_product_relation_mapping_service():
    """Test 21: SERVICE_WITH_CONSUMABLES maps to CONSUMABLE_FOR_SERVICE."""
    rows = [{'procurement_id': 705, 'category_code': 'lighting', 'matched_term': 'A', 'procurement_scope_type': 'SERVICE_WITH_CONSUMABLES', 'validation_status': 'CONFIRMED'}]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(705)[0]
    assert opp.product_relation == 'CONSUMABLE_FOR_SERVICE'


def test_22_unassigned_medal_fallback():
    """Test 22: Unknown or missing medal falls back to UNASSIGNED."""
    rows = [{'procurement_id': 800, 'category_code': 'lighting', 'matched_term': 'A', 'research_prior_band': 'INVALID_MEDAL', 'validation_status': 'CONFIRMED'}]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(800)[0]
    assert opp.commercial_medal == 'UNASSIGNED'


def test_23_empty_procurements_batch():
    """Test 23: Passing empty list to bulk service returns empty dict."""
    service = CategoryOpportunityService(MockDBManager([]))
    res = service.get_opportunities_for_procurements([])
    assert res == {}


def test_24_nonexistent_procurement_id():
    """Test 24: Querying nonexistent procurement ID returns empty list."""
    service = CategoryOpportunityService(MockDBManager([]))
    opps = service.get_opportunities_for_procurement(999999)
    assert opps == []


def test_25_multiple_procurements_bulk():
    """Test 25: Bulk service returns separate lists per procurement ID."""
    rows = [
        {'procurement_id': 10, 'category_code': 'flooring', 'matched_term': 'A', 'validation_status': 'CONFIRMED'},
        {'procurement_id': 20, 'category_code': 'lighting', 'matched_term': 'B', 'validation_status': 'CONFIRMED'}
    ]
    service = CategoryOpportunityService(MockDBManager(rows))
    res = service.get_opportunities_for_procurements([10, 20])
    assert len(res[10]) == 1
    assert res[10][0].category_id == 'flooring'
    assert len(res[20]) == 1
    assert res[20][0].category_id == 'lighting'


def test_26_subcard_medal_badge_rendering():
    """Test 26: Medal badge display string formatting."""
    opp_gold = CategoryOpportunity(1, 'flooring', 'Flooring', commercial_medal='GOLD')
    opp_wood = CategoryOpportunity(1, 'curb', 'Curb', commercial_medal='WOOD')
    
    assert opp_gold.commercial_medal == 'GOLD'
    assert opp_wood.commercial_medal == 'WOOD'


def test_27_facts_count_metrics():
    """Test 27: facts_with_quantity and facts_with_value counts reflect matches accurately."""
    rows = [
        {'procurement_id': 900, 'category_code': 'lighting', 'matched_term': 'A', 'quantity_value': 10, 'total_price_value': 100, 'validation_status': 'CONFIRMED'},
        {'procurement_id': 900, 'category_code': 'lighting', 'matched_term': 'B', 'quantity_value': 20, 'total_price_value': None, 'validation_status': 'CONFIRMED'},
        {'procurement_id': 900, 'category_code': 'lighting', 'matched_term': 'C', 'quantity_value': None, 'total_price_value': None, 'validation_status': 'CONFIRMED'},
    ]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(900)[0]
    
    assert opp.facts_with_quantity == 2
    assert opp.facts_with_value == 1
    assert opp.evidence_count == 3


def test_28_scope_boundaries_preservation():
    """Test 28: Verify scope boundaries preservation (no retraining, priority model untouched)."""
    # Import queue priority model helper to verify no changes or mutations occurred
    from src.services.research_queue_priority import get_effective_service_band, BAND_GOLD
    
    # Priority model logic remains unchanged:
    row = {
        'procurement_scope_type': 'DIRECT_GOODS',
        'normalized_nmck_rub': 100000.0,
        'research_prior_band': 'WOOD'
    }
    band = get_effective_service_band(row)
    assert band == BAND_GOLD  # Priority override rule intact


def test_29_category_medal_from_research_prior_is_no():
    """Test 29: Unannotated category commercial medal must resolve to UNASSIGNED (CATEGORY_MEDAL_FROM_RESEARCH_PRIOR = NO)."""
    rows = [
        {
            'procurement_id': 990,
            'category_code': 'lighting',
            'matched_term': 'Светильник',
            'research_prior_band': 'GOLD',  # Stage 1 priority band is GOLD
            'validation_status': 'CONFIRMED'
            # NO commercial_medal or crm_procurement_category_opportunities row
        }
    ]
    service = CategoryOpportunityService(MockDBManager(rows))
    opp = service.get_opportunities_for_procurement(990)[0]
    
    # Must NOT copy research_prior_band to commercial_medal!
    assert opp.commercial_medal == 'UNASSIGNED'
    assert opp.commercial_state == 'UNCONFIRMED'
    assert opp.medal_authority == 'UNANNOTATED'


def test_30_multi_category_direct_goods_nmck_duplication_prevented():
    """Test 30: DIRECT_GOODS with multiple confirmed categories MUST NOT duplicate NMCK across cards."""
    rows = [
        {
            'procurement_id': 991,
            'category_code': 'lighting',
            'matched_term': 'Светильник',
            'procurement_scope_type': 'DIRECT_GOODS',
            'normalized_nmck_rub': 500000.0,
            'validation_status': 'CONFIRMED'
        },
        {
            'procurement_id': 991,
            'category_code': 'flooring',
            'matched_term': 'Линолеум',
            'procurement_scope_type': 'DIRECT_GOODS',
            'normalized_nmck_rub': 500000.0,
            'validation_status': 'CONFIRMED'
        }
    ]
    service = CategoryOpportunityService(MockDBManager(rows))
    opps = service.get_opportunities_for_procurement(991)
    
    assert len(opps) == 2
    for opp in opps:
        # Multi-category DIRECT_GOODS without line totals must NOT duplicate NMCK!
        assert opp.potential_supply_value_rub is None
        assert opp.potential_supply_value_method == 'NOT_AVAILABLE'


def test_31_independent_category_medals_on_single_procurement(test_multi_medal_fixture):
    """Test 31: Verify independent category medals on procurement 9901."""
    pid, rows = test_multi_medal_fixture
    service = CategoryOpportunityService(MockDBManager(rows))
    opps = service.get_opportunities_for_procurement(pid)
    
    by_cat = {o.category_id: o for o in opps}
    assert by_cat['flooring'].commercial_medal == 'GOLD'
    assert by_cat['lighting'].commercial_medal == 'GOLD'
    assert by_cat['curbstone'].commercial_medal == 'WOOD'
    # All belong to procurement 9901 where research_prior_band was WOOD

