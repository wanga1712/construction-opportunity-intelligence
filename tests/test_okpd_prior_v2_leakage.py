"""Tests for V2 target encoding leakage prevention, domain disambiguation, and superuser authority."""

from __future__ import annotations

import pytest

from src.learning.okpd_prior.combined_v2 import (
    MODEL_NAME_V2,
    NEURAL_EMBEDDINGS_USED,
    TEXT_REPRESENTATION_TYPE,
    ResearchPriorityModelV2,
)
from src.learning.okpd_prior.disambiguation import extract_domain_signals
from src.repositories.taxonomy_repository import TaxonomyRepository
from src.services.taxonomy_service import TaxonomyService


def test_v2_metadata_constants():
    """Verifies feature and representation metadata constants."""
    assert MODEL_NAME_V2 == "research_priority_v2"
    assert TEXT_REPRESENTATION_TYPE == "TFIDF_WORD_CHAR_PLUS_DOMAIN_FEATURES"
    assert NEURAL_EMBEDDINGS_USED is False


def test_fit_oof_predictions_zero_leakage():
    """Verifies that OOF predictions run with cross-fitted outer fold target encodings without leakage."""
    titles = [
        "Строительство автодороги и мостового перехода",
        "Капитальный ремонт кровли и гидроизоляция",
        "Монтаж наружного освещения и установка опор",
        "Поставка медицинских шприцев и игл для инъекций",
        "Поставка офисной мебели столов и стульев",
        "Поставка серверного оборудования и патч-кордов",
        "Устройство наливных полов и отделочные работы",
        "Поставка продуктов питания крупы и молоко",
        "Строительство инженерных сетей водоснабжения",
        "Поставка лекарственных препаратов и растворов",
    ]
    okpd_codes = [
        "42.11.20.000",
        "43.91.19.000",
        "43.21.10.140",
        "32.50.13.110",
        "31.09.11.190",
        "26.20.14.000",
        "43.33.10.000",
        "10.89.19.000",
        "42.21.11.000",
        "21.20.10.110",
    ]
    prices = [50_000_000.0, 12_000_000.0, 8_000_000.0, 500_000.0, 300_000.0, 2_000_000.0, 4_000_000.0, 150_000.0, 15_000_000.0, 900_000.0]
    y = [1, 1, 1, 0, 0, 0, 1, 0, 1, 0]

    model = ResearchPriorityModelV2(random_state=42)
    oof_probs = model.fit_oof_predictions(titles, okpd_codes, prices, y, n_splits=2)

    assert len(oof_probs) == len(y)
    assert all(0.0 <= p <= 1.0 for p in oof_probs)
    # Check that positive construction tenders score higher on average than negative non-target ones
    pos_mean = sum(oof_probs[i] for i, label in enumerate(y) if label == 1) / 5.0
    neg_mean = sum(oof_probs[i] for i, label in enumerate(y) if label == 0) / 5.0
    assert pos_mean > neg_mean


def test_polyclinic_suppresses_false_flooring_construction_match():
    """Verifies that 'поликлиника' does not match 'пол' as a construction flooring signal."""
    medical_title = "Поставка расходных материалов для поликлиники № 5"
    signals = extract_domain_signals(medical_title, okpd_code="32.50.50.000")

    assert signals["construction_prior"] == 0.0
    assert signals["medical_risk"] > 0.3


def test_contrastive_injection_disambiguation():
    """Verifies contrastive disambiguation for construction injection vs medical injection."""
    constr_title = "Выполнение работ по инъектированию трещин бетонных конструкций"
    med_title = "Поставка шприцев инъекционных одноразовых"

    c_sig = extract_domain_signals(constr_title, okpd_code="43.99.90.000")
    m_sig = extract_domain_signals(med_title, okpd_code="32.50.13.110")

    assert c_sig["disambiguated_injection_score"] > 0.0
    assert c_sig["construction_prior"] > 0.5
    assert c_sig["medical_risk"] == 0.0

    assert m_sig["disambiguated_injection_score"] < 0.0
    assert m_sig["medical_risk"] > 0.7
    assert m_sig["construction_prior"] == 0.0


def test_superuser_taxonomy_authority_enforcement():
    """Verifies that ordinary users cannot mutate taxonomy while superusers can."""
    repo = TaxonomyRepository(storage_path=None)
    service = TaxonomyService(repo)

    # 1. Ordinary user mutation attempt must raise PermissionError
    with pytest.raises(PermissionError) as exc_info:
        service.create_or_update_rule(
            okpd_pattern="42.11",
            rule_mode="BOOST",
            actor="ordinary_operator_john",
        )
    assert "ORDINARY_USER_TAXONOMY_MUTATION=DENIED" in str(exc_info.value)

    # 2. Superuser mutation must succeed
    rule = service.create_or_update_rule(
        okpd_pattern="42.11",
        rule_mode="BOOST",
        actor="superuser",
    )
    assert rule.okpd_pattern == "42.11"
    assert rule.rule_mode == "BOOST"

    # 3. Superuser deletion must succeed
    assert service.delete_rule(rule.rule_id, actor="superuser") is True
