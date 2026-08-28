"""Unit tests for procurement identity / public EIS link authority."""
from __future__ import annotations

from src.services.procurement_identity import (
    LinkValidity,
    build_public_223_url,
    canonical_tender_link_for_storage,
    is_private_lk_url,
    public_url_matches_number,
    resolve_procurement_link,
)


def test_223_private_lk_becomes_public_epz_from_registration_number() -> None:
    private = (
        "https://lk.zakupki.gov.ru/223/purchase/private/purchase/notice-info/"
        "details.html?noticeInfoId=19557278"
    )
    view = resolve_procurement_link(
        source_table="reestr_contract_223_fz",
        contract_number="32615833902",
        tender_link=private,
    )
    assert view.procurement_number == "32615833902"
    assert view.notice_info_id == "19557278"
    assert view.validity == LinkValidity.VERIFIED_FACTUAL
    assert view.render_direct_link is True
    assert view.public_url == (
        "https://zakupki.gov.ru/epz/order/notice/notice223/common-info.html"
        "?regNumber=32615833902"
    )
    assert is_private_lk_url(private) is True
    assert is_private_lk_url(view.public_url) is False


def test_operator_confirmed_223_pair_notice_info_id_is_not_public_id() -> None:
    private = (
        "https://lk.zakupki.gov.ru/223/purchase/private/purchase/notice-info/"
        "details.html?noticeInfoId=20167502"
    )
    view = resolve_procurement_link(
        source_table="reestr_contract_223_fz",
        contract_number="32616311665",
        tender_link=private,
    )
    assert view.notice_info_id == "20167502"
    assert view.procurement_number == "32616311665"
    assert view.public_url == build_public_223_url("32616311665")
    assert "noticeInfoId" not in (view.public_url or "")
    assert "lk.zakupki.gov.ru" not in (view.public_url or "")


def test_44_public_epz_survives_when_reg_number_matches() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html"
        "?regNumber=0318100051226000067"
    )
    view = resolve_procurement_link(
        source_table="reestr_contract_44_fz",
        contract_number="0318100051226000067",
        tender_link=url,
    )
    assert view.render_direct_link is True
    assert view.public_url == url
    assert public_url_matches_number(url, "0318100051226000067") is True


def test_44_mismatched_public_url_not_rendered() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ok20/view/common-info.html"
        "?regNumber=9999999999999999999"
    )
    view = resolve_procurement_link(
        source_table="reestr_contract_44_fz",
        contract_number="0318100051226000067",
        tender_link=url,
    )
    assert view.render_direct_link is False
    assert view.validity == LinkValidity.INVALID
    assert view.procurement_number == "0318100051226000067"


def test_missing_link_still_shows_number_authority() -> None:
    view = resolve_procurement_link(
        source_table="reestr_contract_223_fz",
        contract_number="32615833902",
        tender_link=None,
    )
    assert view.procurement_number == "32615833902"
    assert view.render_direct_link is True  # derived from number
    assert view.public_url is not None


def test_canonical_storage_never_persists_private_lk() -> None:
    private = (
        "https://lk.zakupki.gov.ru/223/purchase/private/purchase/notice-info/"
        "details.html?noticeInfoId=19557278"
    )
    stored = canonical_tender_link_for_storage(
        source_table="reestr_contract_223_fz",
        contract_number="32615833902",
        tender_link=private,
    )
    assert stored is not None
    assert "lk.zakupki.gov.ru" not in stored
    assert "regNumber=32615833902" in stored


def test_card_surface_shows_procurement_number_without_extra_sql() -> None:
    # Static contract: resolve uses only already-loaded card fields.
    view = resolve_procurement_link(
        source_table="reestr_contract_223_fz",
        contract_number="32615833902",
        tender_link="https://lk.zakupki.gov.ru/223/purchase/private/x?noticeInfoId=1",
    )
    assert view.procurement_number == "32615833902"
