"""Strict DIRECT_SUPPLY extraction template registry."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

DIRECT_TRACKS = frozenset({"DIRECT", "DIRECT_SUPPLY"})


@dataclass(frozen=True)
class DirectTemplateKey:
    category_code: str
    opportunity_track: str
    document_class: str
    file_format: str


@dataclass(frozen=True)
class DirectTemplate:
    key: DirectTemplateKey
    extractor: str = "direct_table_rows_v1"
    accepted_kinds: Tuple[str, ...] = ("spec", "tech")


def _key(category: str, document_class: str, fmt: str,
         kinds: Tuple[str, ...] = ("spec", "tech")) -> DirectTemplateKey:
    return DirectTemplateKey(
        category_code=category,
        opportunity_track="DIRECT_SUPPLY",
        document_class=document_class,
        file_format=fmt,
    )


_TEMPLATES = {
    _key("lighting", "TECH_SPEC", "docx", ("tech", "spec")):
        DirectTemplate(_key("lighting", "TECH_SPEC", "docx"), accepted_kinds=("tech", "spec")),
    _key("lighting", "TECH_SPEC", "xlsx", ("tech", "spec")):
        DirectTemplate(_key("lighting", "TECH_SPEC", "xlsx"), accepted_kinds=("tech", "spec")),
    _key("computers", "TECH_SPEC", "docx", ("tech", "spec")):
        DirectTemplate(_key("computers", "TECH_SPEC", "docx"), accepted_kinds=("tech", "spec")),
    _key("computers", "TECH_SPEC", "xlsx", ("tech", "spec")):
        DirectTemplate(_key("computers", "TECH_SPEC", "xlsx"), accepted_kinds=("tech", "spec")),
    _key("computers", "PRODUCT_SPECIFICATION", "xlsx", ("spec",)):
        DirectTemplate(_key("computers", "PRODUCT_SPECIFICATION", "xlsx"), accepted_kinds=("spec",)),
    _key("flooring", "ESTIMATE", "xlsx", ("spec", "tech")):
        DirectTemplate(_key("flooring", "ESTIMATE", "xlsx"), accepted_kinds=("spec", "tech")),
    _key("cable_support_systems", "TECH_SPEC", "docx", ("tech", "spec")):
        DirectTemplate(
            _key("cable_support_systems", "TECH_SPEC", "docx"),
            accepted_kinds=("tech", "spec"),
        ),
    _key("cable_support_systems", "TECH_SPEC", "xlsx", ("tech", "spec")):
        DirectTemplate(
            _key("cable_support_systems", "TECH_SPEC", "xlsx"),
            accepted_kinds=("tech", "spec"),
        ),
}


def normalize_direct_track(value: object) -> str:
    track = str(value or "").strip().upper()
    return "DIRECT_SUPPLY" if track in DIRECT_TRACKS else track


def normalize_file_format(value: object) -> str:
    fmt = str(value or "").strip().lower().lstrip(".")
    if fmt in {"xls", "xlsm", "xlt", "xltx", "xltm"}:
        return "xlsx"
    if fmt in {"doc", "docm", "dot", "dotx", "rtf"}:
        return "docx"
    return fmt


def resolve_direct_template(
    *,
    category_code: object,
    opportunity_track: object,
    document_class: object,
    file_format: object,
) -> Optional[DirectTemplate]:
    key = DirectTemplateKey(
        category_code=str(category_code or "").strip().lower(),
        opportunity_track=normalize_direct_track(opportunity_track),
        document_class=str(document_class or "").strip().upper(),
        file_format=normalize_file_format(file_format),
    )
    return _TEMPLATES.get(key)


def resolve_direct_template_for_path(
    path: Path,
    *,
    category_code: object,
    opportunity_track: object,
    document_class: object,
) -> Optional[DirectTemplate]:
    return resolve_direct_template(
        category_code=category_code,
        opportunity_track=opportunity_track,
        document_class=document_class,
        file_format=path.suffix,
    )


def registry_keys() -> Tuple[DirectTemplateKey, ...]:
    return tuple(_TEMPLATES.keys())
