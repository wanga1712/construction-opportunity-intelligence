from src.services.hydro.commercial_hierarchy import (
    CommercialLayer,
    HydroObjectCommercialClass,
    ManagementContour,
    ManagementFacts,
    build_commercial_entities,
    build_qwen_shadow_payload,
    classify_management_contour,
    classify_object,
    company_portfolio_score,
    shadow_input_hash,
    validate_shadow_result,
)


def _object(i, **values):
    return {"object_id": i, "area_total": 1000, "floors_underground": 2, "object_potential": {"score": 80}, **values}


def test_zhilishnik_and_other_uk_are_one_card_per_exact_company():
    rows = [_object(1, management_company_id=10, company_name="ГБУ Жилищник района", company_inn="1"), _object(2, management_company_id=10, company_name="ГБУ Жилищник района", company_inn="1"), _object(3, management_company_id=11, company_name="Жилищник другого юрлица", company_inn="2"), _object(4, management_company_id=12, company_name="Частная УК", company_inn="3")]
    entities = build_commercial_entities(rows)
    assert len(entities) == 3
    assert {entity.layer for entity in entities} == {CommercialLayer.ZHILISHNIK, CommercialLayer.OTHER_UK}
    assert sorted(len(entity.objects) for entity in entities) == [1, 1, 2]
    assert classify_management_contour(ManagementFacts(10, name="Жилищник", inn="1")) == ManagementContour.ZHILISHNIK


def test_no_uk_known_categories_and_unknown_bucket():
    rows = [_object(1, purpose="Многоквартирный дом", object_type="Здание"), _object(2, purpose="Нежилое", name="Торговый центр"), _object(3, purpose="Нежилое", name="Государственный музей"), _object(4, purpose=None, object_type=None, name=None)]
    entities = build_commercial_entities(rows)
    classes = [entity.object_class.commercial_class for entity in entities]
    assert HydroObjectCommercialClass.RESIDENTIAL in classes
    assert HydroObjectCommercialClass.COMMERCIAL_RETAIL in classes
    assert HydroObjectCommercialClass.CULTURAL in classes
    assert HydroObjectCommercialClass.UNKNOWN in classes
    assert entities[-1].layer == CommercialLayer.UNKNOWN


def test_kremlin_like_state_signal_does_not_use_address():
    classified = classify_object({"purpose": "Нежилое", "object_type": "Здание", "name": "Специальный государственный объект", "address": "обычный адрес"})
    assert classified.commercial_class == HydroObjectCommercialClass.STATE_PUBLIC


def test_scores_are_separate_and_portfolio_is_bounded():
    score = company_portfolio_score([_object(1), _object(2, area_total=None)])
    assert score.version == "hydro_company_portfolio_v1"
    assert 0 <= score.score <= 100
    assert score.grade in {"A", "B", "C", "D"}


def test_qwen_payload_is_hashed_and_strictly_validated():
    entity = build_commercial_entities([_object(1, purpose="Многоквартирный дом")])[0]
    payload = build_qwen_shadow_payload(entity)
    assert payload["contract"] == "hydro_commercial_interest_v1"
    assert shadow_input_hash(payload) == shadow_input_hash(payload)
    validate_shadow_result({"commercial_interest_score": 72, "commercial_interest_grade": "B", "recommended_channel": "OWNER_OPERATOR", "priority": "MEDIUM", "reasons": ["portfolio facts"], "risks": [], "next_research_step": "verify operator", "confidence": 0.7})


def test_qwen_result_cannot_add_fact_fields():
    try:
        validate_shadow_result({"commercial_interest_score": 50, "commercial_interest_grade": "C", "recommended_channel": "RESEARCH_REQUIRED", "priority": "RESEARCH", "reasons": [], "risks": [], "next_research_step": "research", "confidence": 0.5, "company_inn": "invented"})
    except ValueError:
        pass
    else:
        raise AssertionError("fact mutation field was accepted")
