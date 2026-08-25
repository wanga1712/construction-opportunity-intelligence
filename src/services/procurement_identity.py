"""Procurement identity and public EIS link authority (44-FZ / 223-FZ).

Semantic read authority:
  PROCUREMENT_NUMBER == crm_procurements.contract_number for OPEN notices,
  proven from S7 tag maps:
    44:  purchaseNumber
    223: purchaseNoticeData/registrationNumber

Private LK URLs (lk.zakupki.gov.ru/.../noticeInfoId=...) are NOT public
procurement identity and must never be rendered as verified direct links.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlparse


class LinkValidity(str, Enum):
    VERIFIED_FACTUAL = "VERIFIED_FACTUAL"
    SOURCE_PROVIDED_UNVERIFIED = "SOURCE_PROVIDED_UNVERIFIED"
    MISSING = "MISSING"
    INVALID = "INVALID"


PUBLIC_223_TEMPLATE = (
    "https://zakupki.gov.ru/epz/order/notice/notice223/common-info.html"
    "?regNumber={reg_number}"
)

# 44-FZ notices already use public EPZ templates; keep host/path allowlist.
_PUBLIC_EPZ_HOST = "zakupki.gov.ru"
_PRIVATE_LK_HOST = "lk.zakupki.gov.ru"


@dataclass(frozen=True)
class ProcurementLinkView:
    procurement_number: str | None
    law: str  # "44" | "223" | "OTHER"
    stored_tender_link: str | None
    public_url: str | None
    validity: LinkValidity
    notice_info_id: str | None = None
    render_direct_link: bool = False
    caption: str | None = None


def source_law_code(source_table: str | None) -> str:
    src = (source_table or "").lower()
    if "223" in src:
        return "223"
    if "44" in src:
        return "44"
    if "615" in src:
        return "615"
    return "OTHER"


def normalize_procurement_number(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.upper().startswith("MISSING-"):
        return None
    return text


def extract_notice_info_id(url: str | None) -> str | None:
    if not url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return None
    vals = qs.get("noticeInfoId") or qs.get("noticeinfoid")
    return vals[0] if vals else None


def is_private_lk_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
        path = (urlparse(url).path or "").lower()
    except Exception:
        return False
    if host != _PRIVATE_LK_HOST:
        return False
    return "/223/purchase/private/" in path or "noticeinfoid" in (urlparse(url).query or "").lower()


def is_public_epz_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
    except Exception:
        return False
    if host != _PUBLIC_EPZ_HOST:
        return False
    return "/epz/order/notice/" in path


def public_url_matches_number(url: str | None, procurement_number: str | None) -> bool:
    if not url or not procurement_number:
        return False
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        return False
    for key in ("regNumber", "regnumber", "reestr-number", "noticeInfoId"):
        vals = qs.get(key) or []
        if any(str(v).strip() == procurement_number for v in vals):
            # noticeInfoId match is NOT identity match for public number
            if key.lower() == "noticeinfoid":
                return False
            return True
    return procurement_number in url


def build_public_223_url(procurement_number: str) -> str:
    return PUBLIC_223_TEMPLATE.format(reg_number=procurement_number)


def resolve_procurement_link(
    *,
    source_table: str | None,
    contract_number: Any,
    tender_link: Any,
) -> ProcurementLinkView:
    """Resolve display/public link without remote HTTP and without extra SQL."""
    number = normalize_procurement_number(contract_number)
    stored = str(tender_link or "").strip() or None
    law = source_law_code(source_table)
    notice_info_id = extract_notice_info_id(stored)

    if law == "223":
        if number:
            public = build_public_223_url(number)
            return ProcurementLinkView(
                procurement_number=number,
                law=law,
                stored_tender_link=stored,
                public_url=public,
                validity=LinkValidity.VERIFIED_FACTUAL,
                notice_info_id=notice_info_id,
                render_direct_link=True,
                caption=None,
            )
        return ProcurementLinkView(
            procurement_number=None,
            law=law,
            stored_tender_link=stored,
            public_url=None,
            validity=LinkValidity.INVALID if stored else LinkValidity.MISSING,
            notice_info_id=notice_info_id,
            render_direct_link=False,
            caption="Прямая ссылка на закупку не подтверждена",
        )

    if law == "44":
        if stored and is_public_epz_url(stored) and public_url_matches_number(stored, number):
            return ProcurementLinkView(
                procurement_number=number,
                law=law,
                stored_tender_link=stored,
                public_url=stored,
                validity=LinkValidity.VERIFIED_FACTUAL,
                notice_info_id=None,
                render_direct_link=True,
            )
        if stored and is_private_lk_url(stored):
            return ProcurementLinkView(
                procurement_number=number,
                law=law,
                stored_tender_link=stored,
                public_url=None,
                validity=LinkValidity.INVALID,
                notice_info_id=extract_notice_info_id(stored),
                render_direct_link=False,
                caption="Прямая ссылка на закупку не подтверждена",
            )
        if stored and is_public_epz_url(stored) and number and not public_url_matches_number(stored, number):
            return ProcurementLinkView(
                procurement_number=number,
                law=law,
                stored_tender_link=stored,
                public_url=None,
                validity=LinkValidity.INVALID,
                render_direct_link=False,
                caption="Прямая ссылка на закупку не подтверждена",
            )
        if stored and is_public_epz_url(stored) and not number:
            # Keep stored public URL only when we cannot contradict it.
            return ProcurementLinkView(
                procurement_number=None,
                law=law,
                stored_tender_link=stored,
                public_url=stored,
                validity=LinkValidity.SOURCE_PROVIDED_UNVERIFIED,
                render_direct_link=False,
                caption="Прямая ссылка на закупку не подтверждена",
            )
        return ProcurementLinkView(
            procurement_number=number,
            law=law,
            stored_tender_link=stored,
            public_url=None,
            validity=LinkValidity.MISSING if not stored else LinkValidity.INVALID,
            render_direct_link=False,
            caption="Прямая ссылка на закупку не подтверждена",
        )

    # OTHER / 615: never invent templates
    if stored and not is_private_lk_url(stored):
        return ProcurementLinkView(
            procurement_number=number,
            law=law,
            stored_tender_link=stored,
            public_url=stored,
            validity=LinkValidity.SOURCE_PROVIDED_UNVERIFIED,
            render_direct_link=False,
            caption="Прямая ссылка на закупку не подтверждена",
        )
    return ProcurementLinkView(
        procurement_number=number,
        law=law,
        stored_tender_link=stored,
        public_url=None,
        validity=LinkValidity.MISSING if not stored else LinkValidity.INVALID,
        notice_info_id=notice_info_id,
        render_direct_link=False,
        caption="Прямая ссылка на закупку не подтверждена",
    )


def canonical_tender_link_for_storage(
    *,
    source_table: str | None,
    contract_number: Any,
    tender_link: Any,
) -> str | None:
    """Preferred stored public link for projection / repair."""
    view = resolve_procurement_link(
        source_table=source_table,
        contract_number=contract_number,
        tender_link=tender_link,
    )
    if view.validity == LinkValidity.VERIFIED_FACTUAL and view.public_url:
        return view.public_url
    if view.stored_tender_link and not is_private_lk_url(view.stored_tender_link):
        return view.stored_tender_link
    return None
