from types import SimpleNamespace

import pytest

from src.services import pdf_export


def _company(**overrides):
    values = {
        "full_name": 'ООО "Тест"',
        "legal_form": "ООО",
        "inn": "7700000000",
        "region": None,
        "nashdom_count": 3,
        "nashdom_active": 1,
        "segments": SimpleNamespace(
            residential=1,
            social=2,
            commercial=0,
            other=0,
        ),
        "company_category": None,
        "company_grade": None,
        "registry": None,
        "website": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_card_from_company_accepts_preformatted_name_and_empty_export():
    company = _company()

    card = pdf_export.card_from_company(company, "Подготовленное имя")

    assert card.full_name == "Подготовленное имя"
    assert card.inn == "7700000000"
    assert card.region == "—"
    assert pdf_export.CompaniesPdfExporter().build_pdf_bytes([]) is None


def test_card_from_company_preserves_expected_error():
    with pytest.raises(AttributeError):
        pdf_export.card_from_company(SimpleNamespace(), "Имя")
