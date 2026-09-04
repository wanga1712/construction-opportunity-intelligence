"""Comprehensive integration and unit tests for Document Product Discovery subsystem."""

from __future__ import annotations

from src.product_discovery.candidate_qualifier import qualify_section_candidates
from src.product_discovery.category_manager import ProductCategoryManager
from src.product_discovery.coproduct_graph import build_coproduct_relations
from src.product_discovery.dto import (
    DiscoveryStatus,
    ProductObservationDTO,
    RowType,
    UnitCategory,
)
from src.product_discovery.estimate_extractor import (
    discover_coproducts_from_section,
    extract_observations_from_table,
)
from src.product_discovery.product_normalizer import normalize_product_name
from src.product_discovery.row_classifier import classify_row
from src.product_discovery.unit_normalizer import are_units_compatible, normalize_unit


def test_unit_normalization_and_compatibility():
    """Verifies unit category normalization and cross-unit comparison guards."""
    assert normalize_unit("шт") == UnitCategory.PCS
    assert normalize_unit("штук") == UnitCategory.PCS
    assert normalize_unit("м") == UnitCategory.LENGTH
    assert normalize_unit("пог. м") == UnitCategory.LENGTH
    assert normalize_unit("м2") == UnitCategory.AREA
    assert normalize_unit("кв. м") == UnitCategory.AREA
    assert normalize_unit("кг") == UnitCategory.WEIGHT
    assert normalize_unit("компл.") == UnitCategory.SET

    # Compatibility
    assert are_units_compatible(UnitCategory.PCS, UnitCategory.PCS) is True
    assert are_units_compatible(UnitCategory.PCS, UnitCategory.SET) is True
    assert are_units_compatible(UnitCategory.PCS, UnitCategory.LENGTH) is False
    assert are_units_compatible(UnitCategory.AREA, UnitCategory.WEIGHT) is False


def test_row_classifier_works_vs_products():
    """Verifies strict separation between installation works and physical products/equipment."""
    assert classify_row("Монтаж опор наружного освещения", "шт") == RowType.WORK
    assert classify_row("Установка светильников светодиодных", "шт") == RowType.WORK
    assert classify_row("Прокладка кабеля в траншее", "м") == RowType.WORK
    assert classify_row("Устройство бетонных оснований", "м3") == RowType.WORK

    assert classify_row("Опора металлическая ОГК-8", "шт") in (RowType.PRODUCT, RowType.MATERIAL)
    assert classify_row("Светильник уличный светодиодный ДКУ-100", "шт") == RowType.EQUIPMENT
    assert classify_row("Кабель силовой ВВГнг-LS 3х2.5", "м") == RowType.MATERIAL
    assert classify_row("Лифт пассажирский 1000 кг", "шт") == RowType.EQUIPMENT
    assert classify_row("Шприц инъекционный одноразовый 5мл", "шт") in (RowType.PRODUCT, RowType.MATERIAL)


def test_lighting_fixture_discovery_and_noise_suppression():
    """Verifies lighting fixture co-product discovery, qualification criteria, and noise suppression."""
    table_rows = [
        # Seed: Luminaire (300 pcs @ 5.4M)
        {"name": "Светильник светодиодный ДКУ-100Вт", "unit": "шт", "quantity": 300, "unit_price": 18_000.0, "total_amount": 5_400_000.0, "is_seed": True, "section_name": "Освещение автодороги"},
        # Candidate 1: Lighting pole (300 pcs @ 7.44M) -> Qualified by amount and quantity match
        {"name": "Опора металлическая граненая коническая ОГК-8", "unit": "шт", "quantity": 300, "unit_price": 24_800.0, "total_amount": 7_440_000.0, "section_name": "Освещение автодороги"},
        # Candidate 2: Power cable (6000 m @ 1.2M) -> Qualified by section value share (share ~ 8%)
        {"name": "Кабель силовой ВВГнг-LS 3х2.5", "unit": "м", "quantity": 6000, "unit_price": 200.0, "total_amount": 1_200_000.0, "section_name": "Освещение автодороги"},
        # Candidate 3: Hardware bolts (2400 pcs @ 48k) -> Suppressed by noise floor
        {"name": "Болт анкерный М24х1000", "unit": "шт", "quantity": 2400, "unit_price": 20.0, "total_amount": 48_000.0, "section_name": "Освещение автодороги"},
        # Candidate 4: Installation work (300 pcs @ 2.1M) -> Excluded as RowType.WORK
        {"name": "Монтаж опор наружного освещения", "unit": "шт", "quantity": 300, "unit_price": 7_000.0, "total_amount": 2_100_000.0, "section_name": "Освещение автодороги"},
    ]

    observations = extract_observations_from_table(table_rows, procurement_id=1001)
    seed, qualified = discover_coproducts_from_section(observations)

    assert seed is not None
    assert seed.normalized_name == "Светильник уличный светодиодный"

    qualified_names = [cand.normalized_name for cand, _ in qualified]
    assert "Опора наружного освещения" in qualified_names
    assert "Кабель силовой" in qualified_names

    # Verify bolt was suppressed by noise floor
    assert not any("Болт" in cand.raw_text for cand, _ in qualified)

    # Verify installation work was excluded from qualified products
    assert not any("Монтаж" in cand.raw_text for cand, _ in qualified)


def test_hidden_product_lift_discovery():
    """Verifies that high-value equipment (passenger lift) is discovered in general construction estimates."""
    table_rows = [
        {"name": "Разборка перегородок и покрытий", "unit": "м2", "quantity": 500, "total_amount": 350_000.0, "section_name": "Общестроительные работы"},
        {"name": "Лифт пассажирский грузоподъемностью 1000 кг", "unit": "шт", "quantity": 4, "unit_price": 4_500_000.0, "total_amount": 18_000_000.0, "section_name": "Лифтовое оборудование"},
        {"name": "Монтаж лифтового оборудования", "unit": "компл", "quantity": 4, "total_amount": 2_400_000.0, "section_name": "Лифтовое оборудование"},
    ]

    observations = extract_observations_from_table(table_rows, procurement_id=2002)
    # Seedless section discovery
    lift_section_obs = [o for o in observations if o.section_name == "Лифтовое оборудование"]
    qualified = qualify_section_candidates(seed=None, observations=lift_section_obs)

    assert len(qualified) == 1
    cand, reason = qualified[0]
    assert cand.normalized_name == "Лифт пассажирский"
    assert cand.total_amount == 18_000_000.0
    assert cand.row_type == RowType.EQUIPMENT


def test_category_manager_alias_resolution_and_authority_boundary():
    """Verifies alias deduplication and model vs expert authority boundaries."""
    mgr = ProductCategoryManager()

    # 1. Register first pole observation
    obs1 = ProductObservationDTO(
        observation_id="obs_1",
        procurement_id=3001,
        raw_text="Опора металлическая ОГК-8",
        total_amount=5_000_000.0,
    )
    cat1 = mgr.register_observation(obs1)
    assert cat1.canonical_name == "Опора наружного освещения"
    assert cat1.status == DiscoveryStatus.AUTO_DISCOVERED
    assert cat1.observation_count == 1

    # 2. Register second near-synonym pole
    obs2 = ProductObservationDTO(
        observation_id="obs_2",
        procurement_id=3002,
        raw_text="Опора коническая фланцевая ОГКф-9",
        total_amount=4_000_000.0,
    )
    cat2 = mgr.register_observation(obs2)
    # Must map to same category id
    assert cat2.category_id == cat1.category_id
    assert cat2.observation_count == 2
    assert cat2.total_discovered_amount == 9_000_000.0
    assert len(cat2.aliases) >= 1

    # 3. Model confirmation check (model cannot set EXPERT_CONFIRMED)
    confirmed_by_model = mgr.confirm_category(cat1.category_id, actor="model_qwen")
    assert confirmed_by_model.status == DiscoveryStatus.MODEL_CONFIRMED

    # 4. Expert confirmation check
    confirmed_by_expert = mgr.confirm_category(cat1.category_id, actor="lead_expert")
    assert confirmed_by_expert.status == DiscoveryStatus.EXPERT_CONFIRMED


def test_coproduct_graph_construction():
    """Verifies co-product graph calculation of conditional probabilities and amount ratios."""
    obs_list = [
        # Tender 1: Pole + Luminaire
        ProductObservationDTO(observation_id="1", procurement_id=101, raw_text="Светильник светодиодный ДКУ", category_name="Светильник уличный светодиодный", row_type=RowType.EQUIPMENT, quantity=100, unit_category=UnitCategory.PCS, total_amount=2_000_000.0),
        ProductObservationDTO(observation_id="2", procurement_id=101, raw_text="Опора освещения ОГК", category_name="Опора наружного освещения", row_type=RowType.PRODUCT, quantity=100, unit_category=UnitCategory.PCS, total_amount=3_000_000.0),

        # Tender 2: Pole + Luminaire
        ProductObservationDTO(observation_id="3", procurement_id=102, raw_text="Светильник светодиодный ДКУ", category_name="Светильник уличный светодиодный", row_type=RowType.EQUIPMENT, quantity=50, unit_category=UnitCategory.PCS, total_amount=1_000_000.0),
        ProductObservationDTO(observation_id="4", procurement_id=102, raw_text="Опора освещения ОГК", category_name="Опора наружного освещения", row_type=RowType.PRODUCT, quantity=50, unit_category=UnitCategory.PCS, total_amount=1_500_000.0),
    ]

    relations = build_coproduct_relations(obs_list)
    assert len(relations) >= 2

    pole_given_lum = next((r for r in relations if r.category_a == "Светильник уличный светодиодный" and r.category_b == "Опора наружного освещения"), None)
    assert pole_given_lum is not None
    assert pole_given_lum.co_occurrence_count == 2
    assert pole_given_lum.conditional_prob_b_given_a == 1.0
    assert pole_given_lum.median_amount_ratio == 1.5
    assert pole_given_lum.median_quantity_ratio == 1.0
