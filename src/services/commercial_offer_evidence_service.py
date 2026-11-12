"""Read-only commercial-offer evidence extracted from stored document rows.

Commercial offers are deliberately separate from estimate quantities. A quote
may prove an issuer and a unit rate while the row number/code must not be
misread as procurement quantity.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

_INN_RE = re.compile(r"^\d{10}$|^\d{12}$")
_DATE_RE = re.compile(r"^\d{2}\.\d{4}$")
_PERCENT_RE = re.compile(r"^\d+(?:[.,]\d+)?%$")
_ORG_RE = re.compile(
    r'(?:ООО|ОАО|ЗАО|ПАО|АО|ИП|ТД)\b|["«»]',
    re.IGNORECASE,
)


def _clean(parts: Iterable[Any]) -> list[str]:
    return [str(part or "").strip() for part in parts if str(part or "").strip()]


def _number(value: Any) -> Decimal | None:
    text = str(value or "")
    text = text.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _is_price(value: str) -> bool:
    if _PERCENT_RE.match(value):
        return False
    digits = re.sub(r"\D", "", value)
    if digits and len(digits) > 7 and not re.search(r"[.,]", value):
        # Long unformatted identifiers in quote rows are INNs/company codes,
        # not unit rates.
        return False
    number = _number(value)
    return number is not None


def parse_commercial_offer_row(row: dict[str, Any]) -> dict[str, Any] | None:
    quote = str(row.get("source_quote") or "").strip()
    if "ТЦ_" not in quote:
        return None
    parts = _clean(quote.split("|"))
    if not parts:
        return None
    quote_ref_index = next(
        (index for index, part in enumerate(parts) if part.upper().startswith("ТЦ_")),
        None,
    )
    if quote_ref_index is None:
        return None

    inn_index = next(
        (
            index
            for index in range(len(parts) - 1, quote_ref_index, -1)
            if _INN_RE.fullmatch(parts[index])
        ),
        None,
    )
    issuer_name = None
    issuer_inn = None
    if inn_index is not None:
        issuer_inn = parts[inn_index]
        for index in range(inn_index - 1, quote_ref_index, -1):
            candidate = parts[index]
            if _is_price(candidate) or _DATE_RE.match(candidate):
                continue
            if _ORG_RE.search(candidate):
                issuer_name = candidate
                break

    price_limit = inn_index if inn_index is not None else len(parts)
    quote_date_raw = next(
        (
            part
            for part in reversed(parts[quote_ref_index + 1:price_limit])
            if _DATE_RE.match(part)
        ),
        None,
    )
    percent_index = next(
        (
            index
            for index in range(price_limit - 1, quote_ref_index, -1)
            if _PERCENT_RE.match(parts[index])
        ),
        None,
    )
    markup_percent = parts[percent_index] if percent_index is not None else None
    prices = [
        (index, part, _number(part))
        for index, part in enumerate(parts[quote_ref_index + 1:price_limit], start=quote_ref_index + 1)
        if _is_price(part)
    ]
    final_price = prices[-1][2] if prices else None
    price_before_markup = None
    markup_amount = None
    if percent_index is not None:
        before_percent = [
            item for item in prices if item[0] < percent_index
        ]
        after_percent = [
            item for item in prices if item[0] > percent_index
        ]
        price_before_markup = before_percent[-1][2] if before_percent else None
        markup_amount = after_percent[0][2] if after_percent else None
    state = "CONFIRMED" if issuer_name and final_price is not None else "PARTIAL"
    return {
        "evidence_kind": "COMMERCIAL_OFFER",
        "state": state,
        "procurement_id": int(row["procurement_id"]),
        "source_document_id": row.get("source_document_id"),
        "document_name": row.get("document_name"),
        "row_ref": row.get("row_ref"),
        "quote_ref": parts[quote_ref_index],
        "product_name": row.get("name_raw"),
        "category_code": row.get("category_code"),
        "subcategory_code": row.get("subcategory_code"),
        "unit": row.get("unit_raw"),
        "issuer_name": issuer_name,
        "issuer_inn": issuer_inn,
        "quote_date_raw": quote_date_raw,
        "price_before_markup": price_before_markup,
        "markup_percent": markup_percent,
        "markup_amount": markup_amount,
        "unit_price_value": final_price,
        "currency_code": None,
        "quantity_value": None,
        "quantity_state": "NOT_AN_ESTIMATE_QUANTITY",
        "source_quote": quote,
    }


def build_commercial_offer_evidence(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    offers = []
    for row in rows:
        parsed = parse_commercial_offer_row(dict(row))
        if parsed is not None:
            offers.append(parsed)
    return offers
