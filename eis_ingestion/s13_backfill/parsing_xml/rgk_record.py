"""Parse a 44-FZ RGK XML once into a normalized RGKRecord. No DB I/O."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from parsing_xml.xml_parser import XMLParser
from parsing_xml.xml_parser_recouped_contract import (
    _non_target_version_key,
    extract_rgk_contract_subject,
    extract_rgk_okpd_codes,
)


@dataclass
class RGKRecord:
    file_name: str
    file_path: str
    contract_number: str
    auction_name: Optional[str] = None
    delivery_start_date: Optional[str] = None
    delivery_end_date: Optional[str] = None
    final_price: Optional[str] = None
    okpd_codes: list[str] = field(default_factory=list)
    okpd_code: Optional[str] = None
    okpd_id: Optional[int] = None
    contractor_inn: Optional[str] = None
    contractor_id: Optional[int] = None
    contractor_fields: dict[str, Any] = field(default_factory=dict)
    document_links: list[dict[str, Any]] = field(default_factory=list)
    notification_number: Optional[str] = None
    reestr_number: Optional[str] = None
    version_key: str = ""
    raw_file: Optional[str] = None
    source_version: Optional[str] = None
    source_publish: Optional[str] = None

    def as_fields(self) -> dict[str, Any]:
        return {
            "contract_number": self.contract_number,
            "auction_name": self.auction_name,
            "delivery_start_date": self.delivery_start_date,
            "delivery_end_date": self.delivery_end_date,
            "final_price": self.final_price,
            "okpd_codes": list(self.okpd_codes),
            "okpd_codes_list": list(self.okpd_codes),
            "okpd_code": self.okpd_code,
            "okpd_id": self.okpd_id,
            "contractor_id": self.contractor_id,
            "notification_number": self.notification_number or self.contract_number,
            "reestr_number": self.reestr_number,
            "raw_file": self.raw_file or self.file_name,
        }


def _local_findall(root, xpath: str):
    tag = xpath.split(":")[-1]
    return root.findall(f".//{tag}")


def _first_text(root, xpath: str) -> Optional[str]:
    elements = _local_findall(root, xpath)
    for elem in elements:
        if elem is not None and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def _xpath_text(root, xpath: str) -> Optional[str]:
    element = root.find(f".//{xpath}")
    if element is not None and element.text and element.text.strip():
        return element.text.strip()
    return None


def extract_contract_number(root) -> Optional[str]:
    possible_xpaths = [
        "order/notificationNumber",
        "notificationNumber",
        "contractNumber",
        "contract_number",
        "order/contractNumber",
        "order/contract_number",
        "contract/notificationNumber",
        "contract/contractNumber",
    ]
    for xpath in possible_xpaths:
        value = _xpath_text(root, xpath) or _first_text(root, xpath)
        if value:
            return value
    for elem in root.iter():
        tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        lowered = tag_name.lower()
        if (
            "notificationnumber" in lowered
            or "contractnumber" in lowered
            or "contract_number" in lowered
        ) and elem.text:
            value = elem.text.strip()
            if value:
                return value
    return None


def extract_source_meta(root) -> tuple[Optional[str], Optional[str]]:
    version = _first_text(root, "versionNumber") or _first_text(root, "docVersion")
    publish = (
        _first_text(root, "docPublishDate")
        or _first_text(root, "publishDate")
        or _first_text(root, "publishDTInEIS")
        or _first_text(root, "modificationDate")
        or _first_text(root, "signDate")
    )
    return version, publish


def filename_guid(file_name: str) -> str:
    parts = os.path.basename(file_name).split("_")
    if len(parts) >= 4:
        return parts[3].split(".")[0].upper()
    return ""


def _publish_sort_key(text: Optional[str]) -> str:
    if not text:
        return ""
    raw = str(text).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        return parsed.isoformat()
    return parsed.astimezone(timezone.utc).isoformat()


def canonical_source_key(record: RGKRecord) -> tuple:
    """EIS version, then publish timestamp, then filename GUID. Not DB id or mtime."""
    try:
        version = int(str(record.source_version).strip()) if record.source_version not in (None, "") else 0
    except (TypeError, ValueError):
        version = 0
    return (version, _publish_sort_key(record.source_publish), filename_guid(record.file_name))


def extract_contract_number_from_filename(file_name: str) -> Optional[str]:
    base = os.path.basename(file_name)
    if not base.startswith("contract_"):
        return None
    parts = base.split("_")
    if len(parts) > 1 and parts[1]:
        return parts[1]
    return None


def _extract_contractor(root, contractor_tags: dict) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for tag, xpath in (contractor_tags or {}).items():
        found[tag] = _xpath_text(root, xpath)
    inn = found.get("inn")
    if isinstance(inn, str):
        inn = inn.strip() or None
        found["inn"] = inn
    return found


def _extract_links(root, links_tags: dict) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for tag_name, tag_data in (links_tags or {}).items():
        xpath = tag_data.get("xpath")
        if not xpath:
            continue
        for elem in root.findall(xpath):
            file_name_tag = tag_data.get("file_name", tag_data.get("default_file_name", tag_name))
            file_name_elem = elem.find(file_name_tag) if file_name_tag else None
            url_elem = elem.find(tag_data.get("document_links"))
            file_name = (
                file_name_elem.text.strip()
                if file_name_elem is not None and file_name_elem.text
                else file_name_tag
            )
            url = url_elem.text.strip() if url_elem is not None and url_elem.text else None
            if url:
                found.append({"file_name": file_name, "document_links": url})
    return found


def parse_rgk_root(
    root,
    *,
    file_name: str,
    file_path: str,
    tags: dict,
    contract_number_fallback: Optional[str] = None,
    cleaned_xml: str = "",
) -> Optional[RGKRecord]:
    reestr_tags = tags.get("reestr_contract") or {}
    number = _first_text(root, reestr_tags.get("contract_number", "order/notificationNumber"))
    number = number or extract_contract_number(root) or contract_number_fallback
    if not number:
        return None

    start_dates = root.findall(".//executionPeriod/startDate")
    end_dates = root.findall(".//executionPeriod/endDate")
    delivery_start = None
    if start_dates and start_dates[0].text and start_dates[0].text.strip():
        delivery_start = start_dates[0].text.strip()
    elif reestr_tags.get("delivery_start_date"):
        delivery_start = _first_text(root, reestr_tags["delivery_start_date"])
    delivery_end = None
    if end_dates and end_dates[-1].text and end_dates[-1].text.strip():
        delivery_end = end_dates[-1].text.strip()
    elif reestr_tags.get("delivery_end_date"):
        delivery_end = _first_text(root, reestr_tags["delivery_end_date"])

    auction_name = _first_text(root, reestr_tags.get("auction_name", "contractSubject"))
    subject = extract_rgk_contract_subject(root)
    if subject and (not auction_name or str(auction_name).startswith("Контракт ")):
        auction_name = subject

    codes = extract_rgk_okpd_codes(root)
    contractor_fields = _extract_contractor(root, tags.get("contractor") or {})
    inn = contractor_fields.get("inn")
    source_version, source_publish = extract_source_meta(root)

    return RGKRecord(
        file_name=file_name,
        file_path=file_path,
        contract_number=str(number).strip(),
        auction_name=auction_name,
        delivery_start_date=delivery_start,
        delivery_end_date=delivery_end,
        final_price=_first_text(root, reestr_tags.get("final_price", "priceInfo/price")),
        okpd_codes=codes,
        okpd_code=codes[0] if codes else None,
        contractor_inn=str(inn).strip() if inn else None,
        contractor_fields=contractor_fields,
        document_links=_extract_links(root, tags.get("links_documentation") or {}),
        notification_number=_first_text(root, reestr_tags.get("notification_number", "notificationNumber")),
        reestr_number=_first_text(root, reestr_tags.get("reestr_number", "reestrNumber")),
        version_key=_non_target_version_key(str(number).strip(), cleaned_xml),
        raw_file=os.path.basename(file_path),
        source_version=source_version,
        source_publish=source_publish,
    )


def parse_rgk_file(
    file_path: str,
    tags: dict,
    contract_number_fallback: Optional[str] = None,
) -> tuple[Optional[RGKRecord], int]:
    """Return (record, parse_passes). parse_passes is 1 on success or failed parse."""
    with open(file_path, "r", encoding="utf-8") as handle:
        xml_content = handle.read()
    cleaned = XMLParser.remove_namespaces(xml_content)
    root = ET.fromstring(cleaned)
    fallback = contract_number_fallback or extract_contract_number_from_filename(file_path)
    record = parse_rgk_root(
        root,
        file_name=os.path.basename(file_path),
        file_path=file_path,
        tags=tags,
        contract_number_fallback=fallback,
        cleaned_xml=cleaned,
    )
    return record, 1
