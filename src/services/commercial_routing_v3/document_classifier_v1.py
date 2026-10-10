"""Canonical read-only document classifier (document_class_v1).

Classifies an EIS source attachment using ONLY already-stored metadata
(file name + source table). Never performs HTTP, never downloads, never writes.

The keyword vocabulary is aligned with the production router
(``tender_documents_research/document_processor/document_routing.py``) and the
download-time skip list (``file_skip_list.py``) so the classifier does not
introduce a second, contradictory naming taxonomy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

DOCUMENT_CLASSIFIER_VERSION = "document_class_v1"


class DocumentClass(str, Enum):
    TECH_SPEC = "TECH_SPEC"
    PRODUCT_SPECIFICATION = "PRODUCT_SPECIFICATION"
    BOQ = "BOQ"
    ESTIMATE = "ESTIMATE"
    PROJECT_DOCUMENTATION = "PROJECT_DOCUMENTATION"
    WORKING_DOCUMENTATION = "WORKING_DOCUMENTATION"
    MATERIAL_SPECIFICATION = "MATERIAL_SPECIFICATION"
    CONTRACT_PROJECT = "CONTRACT_PROJECT"
    NMCK_JUSTIFICATION = "NMCK_JUSTIFICATION"
    PARTICIPANT_REQUIREMENTS = "PARTICIPANT_REQUIREMENTS"
    SECURITY_REQUIREMENTS = "SECURITY_REQUIREMENTS"
    LEGAL_GENERAL = "LEGAL_GENERAL"
    OTHER = "OTHER"


ARCHIVE_EXTENSIONS = frozenset({".rar", ".zip", ".7z", ".tar", ".gz"})

#: Extensions that are provably not evidence-bearing documents.
NON_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".xml",
        ".sig",
        ".p7s",
        ".gge",
        ".sign",
        ".gsfx",
        ".cer",
        ".crt",
        ".key",
        ".pem",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".gif",
        ".dwg",
        ".dxf",
        ".dwf",
    }
)

#: Ordered rules; first match wins. (class, confidence, reason, patterns)
RULES: tuple[tuple[DocumentClass, float, str, tuple[str, ...]], ...] = (
    (
        DocumentClass.NMCK_JUSTIFICATION,
        0.95,
        "NMCK_KEYWORD",
        (
            r"нмцк",
            r"нмцд",
            r"обосновани\w*[\s_]+(начальн|нмцк|нмцд|цены)",
            r"расч[её]т[\s_]+нмц[кд]",
            r"коммерческ\w*[\s_]+предложени",
        ),
    ),
    (
        DocumentClass.ESTIMATE,
        0.95,
        "ESTIMATE_KEYWORD",
        (
            r"смет",
            r"(?<![а-яa-z])лс[\s_№]*\d",
            r"(?<![а-яa-z])лср(?![а-яa-z])",
            r"(?<![а-яa-z])см[\s_]*\d*(?![а-яa-z])",
        ),
    ),
    (
        DocumentClass.MATERIAL_SPECIFICATION,
        0.9,
        "MATERIAL_SPEC_KEYWORD",
        (r"ведомост\w*.{0,20}материал", r"материал\w*.{0,20}ведомост", r"спецификац\w*.{0,20}материал"),
    ),
    (
        DocumentClass.BOQ,
        0.95,
        "BOQ_KEYWORD",
        (
            r"ведомост\w*[\s_]*объ[её]м",
            r"объ[её]мы?[\s_]+работ",
            r"сводн\w*[\s_]+ведомост",
            r"дефектн\w*[\s_]+ведомост",
            r"(?<![а-яa-z])вор(?![а-яa-z])",
            r"ведомост",
        ),
    ),
    (
        DocumentClass.SECURITY_REQUIREMENTS,
        0.85,
        "SECURITY_REQUIREMENTS_KEYWORD",
        (
            r"обеспечени\w*[\s_]+(исполнени|заявк|гарант|контракт)",
            r"банковск\w*[\s_]+гаранти",
            r"(?<![а-яa-z])бг(?![а-яa-z])",
            r"гарантийн\w*[\s_]+обязательств",
        ),
    ),
    (
        DocumentClass.CONTRACT_PROJECT,
        0.95,
        "CONTRACT_PROJECT_KEYWORD",
        (
            r"проект[_\s]?(контракта|договора)",
            r"электронн\w*[\s_]+контракт",
            r"контракт\w*[\s_]+с[\s_]+уч[её]том[\s_]+доп",
            r"\bдоговор",
            r"\bконтракт",
        ),
    ),
    (
        DocumentClass.TECH_SPEC,
        0.95,
        "TECH_SPEC_KEYWORD",
        (
            r"техническ\w*[\s_]+задани",
            r"\bтз\b",
            r"описани[ея][\s_]+объ[её]кта[\s_]+закупки",
            r"задани[ея][\s_]+на[\s_]+(проектирован|поставк|выполнени)",
        ),
    ),
    (
        DocumentClass.PARTICIPANT_REQUIREMENTS,
        0.85,
        "PARTICIPANT_REQUIREMENTS_KEYWORD",
        (
            r"требовани\w*[\s_]+к[\s_]+(участник|состав|содержанию|заявк)",
            r"инструкци\w*[\s_]+по[\s_]+заполнени",
            r"форма[\s_]+(заявк|коммерческ\w*[\s_]+предложени)",
            r"требование[\s_]+к[\s_]+участникам",
            r"порядок[\s_]+подачи[\s_]+заявок",
        ),
    ),
    (
        DocumentClass.WORKING_DOCUMENTATION,
        0.85,
        "WORKING_DOCUMENTATION_KEYWORD",
        (
            r"рабоч\w*[\s_]+документац",
            r"альбом[\s_]+рд",
            r"(?<![а-яa-z])рд(?![а-яa-z])",
        ),
    ),
    (
        DocumentClass.PROJECT_DOCUMENTATION,
        0.85,
        "PROJECT_DOCUMENTATION_KEYWORD",
        (
            r"проектн\w*[\s_]+документац",
            r"(?<![а-яa-z])псд(?![а-яa-z])",
            r"(?<![а-яa-z])пд(?![а-яa-z])",
            r"раздел[\s_]+пд",
            r"том[\s_]*\d",
            r"\bпроект\b",
            r"проектирован",
            r"пояснительн\w*[\s_]+записк",
            r"архитектурн\w*[\s_]+решени",
            r"конструктивн\w*[\s_]+решени",
            r"объ[её]мно[\s\-]планировочн",
            r"инженерн\w*[\s_]+(сети|систем|оборудован)",
            r"(?<![а-яa-z])(ар|кр|пз|эом|оос|подд|сд|тх|ас)(?![а-яa-z])",
        ),
    ),
    (
        DocumentClass.PRODUCT_SPECIFICATION,
        0.8,
        "PRODUCT_SPEC_KEYWORD",
        (r"спецификац", r"перечень[\s_]+(оборудован|товар)", r"характеристик", r"конфигурац", r"оборудовани"),
    ),
    (
        DocumentClass.LEGAL_GENERAL,
        0.7,
        "LEGAL_GENERAL_KEYWORD",
        (
            r"информаци\w*\s+о\s+контракте",
            r"извещени",
            r"протокол",
            r"приложение\s*№?\s*\d+\s*к\s+документации",
            r"инфокарт",
            r"уведомлени",
        ),
    ),
)


@dataclass(frozen=True)
class DocumentClassification:
    document_class: DocumentClass
    confidence: float
    reason: str
    is_document: bool = True
    is_archive: bool = False
    classifier_version: str = DOCUMENT_CLASSIFIER_VERSION


def classify_document_metadata(
    file_name: Optional[str],
    *,
    source_table: Optional[str] = None,
) -> DocumentClassification:
    """Classify a source attachment by stored metadata only."""
    name = (file_name or "").strip()
    if not name:
        return DocumentClassification(
            DocumentClass.OTHER, 0.0, "EMPTY_FILE_NAME", is_document=False
        )

    lower = name.lower()
    dot = lower.rfind(".")
    ext = lower[dot:] if dot > 0 else ""
    if ext in NON_DOCUMENT_EXTENSIONS:
        return DocumentClassification(
            DocumentClass.OTHER, 0.99, f"NON_DOCUMENT_EXTENSION{ext}", is_document=False
        )
    is_archive = ext in ARCHIVE_EXTENSIONS

    haystack = lower
    for doc_class, confidence, reason, patterns in RULES:
        for pattern in patterns:
            if re.search(pattern, haystack):
                return DocumentClassification(
                    doc_class,
                    confidence - (0.1 if is_archive else 0.0),
                    f"{reason}:{pattern}",
                    is_document=True,
                    is_archive=is_archive,
                )

    if not ext:
        return DocumentClassification(
            DocumentClass.OTHER, 0.2, "NO_EXTENSION_UNKNOWN", is_document=False
        )
    return DocumentClassification(
        DocumentClass.OTHER,
        0.1,
        "ARCHIVE_UNKNOWN_CONTENT" if is_archive else "NO_CLASS_RULE_MATCHED",
        is_document=True,
        is_archive=is_archive,
    )
