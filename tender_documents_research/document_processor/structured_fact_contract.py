"""
R4 Structured Product Fact Contract & Validation Helpers.
Provides data classes, fingerprinting, quote verification, and serialization
for R4 structured product/material/equipment/technology/work extraction.
"""

from dataclasses import dataclass, field, asdict
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

STRUCTURED_EXTRACTOR_NAME = "structured_fact_extractor"
STRUCTURED_EXTRACTOR_VERSION = "v1"
EXTRACTION_METHOD = "QWEN_STRUCTURED_FACT_V1"
PROMPT_VERSION = "structured_fact_v1"

ALLOWED_ENTITY_TYPES = {"PRODUCT", "MATERIAL", "EQUIPMENT", "TECHNOLOGY", "WORK"}

def normalize_whitespace(text: str) -> str:
    """Normalizes all whitespace (newlines, tabs, spaces) to single spaces and strips."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def verify_source_quote(source_quote: str, source_text_snapshot: str) -> bool:
    """
    Validates that normalized source_quote is a non-empty substring of normalized source_text_snapshot.
    """
    if not source_quote or not source_quote.strip():
        return False
    if not source_text_snapshot or not source_text_snapshot.strip():
        return False
    
    norm_quote = normalize_whitespace(source_quote)
    norm_snapshot = normalize_whitespace(source_text_snapshot)
    return norm_quote in norm_snapshot

def compute_sha256(text: str) -> str:
    """Computes UTF-8 SHA256 hex digest of a string."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

def compute_entity_fingerprint(
    entity_type: str,
    product_name_raw: str,
    manufacturer_raw: Optional[str] = None,
    brand_raw: Optional[str] = None,
    model_article_raw: Optional[str] = None,
    source_quote: str = "",
) -> str:
    """
    Computes a stable deterministic SHA256 fingerprint for a structured entity.
    """
    key = "|".join([
        (entity_type or "PRODUCT").upper(),
        normalize_whitespace(product_name_raw or ""),
        normalize_whitespace(manufacturer_raw or ""),
        normalize_whitespace(brand_raw or ""),
        normalize_whitespace(model_article_raw or ""),
        normalize_whitespace(source_quote or ""),
    ])
    return compute_sha256(key)

def compute_attribute_fingerprint(
    attribute_name_normalized: str,
    raw_value: str,
    source_quote: str = "",
) -> str:
    """
    Computes a stable deterministic SHA256 fingerprint for a structured attribute.
    """
    key = "|".join([
        normalize_whitespace(attribute_name_normalized or "").lower(),
        normalize_whitespace(raw_value or ""),
        normalize_whitespace(source_quote or ""),
    ])
    return compute_sha256(key)

@dataclass
class StructuredAttribute:
    attribute_name: str
    attribute_name_normalized: str
    raw_value: str
    source_quote: str
    normalized_value: Optional[str] = None
    numeric_value: Optional[float] = None
    unit_raw: Optional[str] = None
    unit_normalized: Optional[str] = None
    confidence: Optional[float] = None
    attribute_fingerprint: str = ""

    def __post_init__(self):
        if not self.attribute_fingerprint:
            self.attribute_fingerprint = compute_attribute_fingerprint(
                self.attribute_name_normalized, self.raw_value, self.source_quote
            )

@dataclass
class StructuredEntity:
    product_name_raw: str
    source_quote: str
    entity_type: str = "PRODUCT"
    product_name_normalized: Optional[str] = None
    manufacturer_raw: Optional[str] = None
    manufacturer_normalized: Optional[str] = None
    brand_raw: Optional[str] = None
    brand_normalized: Optional[str] = None
    product_line_raw: Optional[str] = None
    product_line_normalized: Optional[str] = None
    model_article_raw: Optional[str] = None
    model_article_normalized: Optional[str] = None
    quantity_value: Optional[float] = None
    quantity_unit_raw: Optional[str] = None
    quantity_unit_normalized: Optional[str] = None
    unit_price_value: Optional[float] = None
    total_price_value: Optional[float] = None
    currency_code: str = "RUB"
    confidence: Optional[float] = None
    attributes: List[StructuredAttribute] = field(default_factory=list)
    entity_fingerprint: str = ""

    def __post_init__(self):
        if not self.entity_fingerprint:
            self.entity_fingerprint = compute_entity_fingerprint(
                self.entity_type,
                self.product_name_raw,
                self.manufacturer_raw,
                self.brand_raw,
                self.model_article_raw,
                self.source_quote,
            )

@dataclass
class ExtractionRun:
    detail_id: int
    procurement_id: int
    category_code: str
    source_text_snapshot: str
    source_text_sha256: str = ""
    match_id: Optional[int] = None
    queue_id: Optional[int] = None
    subcategory_code: Optional[str] = None
    document_name: Optional[str] = None
    archive_member_path: Optional[str] = None
    page_or_sheet: Optional[str] = None
    row_number: Optional[int] = None
    source_validator_name: str = "context_validator"
    source_validator_version: str = "v4"
    source_validation_method: str = "QWEN_CONTEXT_V4"
    extractor_name: str = STRUCTURED_EXTRACTOR_NAME
    extractor_version: str = STRUCTURED_EXTRACTOR_VERSION
    extraction_method: str = EXTRACTION_METHOD
    prompt_version: str = PROMPT_VERSION
    model_name: Optional[str] = None
    status: str = "PENDING"
    raw_response: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    entities: List[StructuredEntity] = field(default_factory=list)

    def __post_init__(self):
        if not self.source_text_sha256 and self.source_text_snapshot:
            self.source_text_sha256 = compute_sha256(self.source_text_snapshot)

def validate_extraction_run(run: ExtractionRun) -> Tuple[bool, List[str]]:
    """
    Validates an ExtractionRun instance for data integrity, valid entity types,
    SHA256 snapshot consistency, and mandatory source quote verification.
    """
    errors: List[str] = []

    if not run.source_text_snapshot:
        errors.append("source_text_snapshot is empty")
    else:
        calc_sha = compute_sha256(run.source_text_snapshot)
        if run.source_text_sha256 and run.source_text_sha256 != calc_sha:
            errors.append(f"source_text_sha256 mismatch: expected {calc_sha}, got {run.source_text_sha256}")

    for idx, ent in enumerate(run.entities):
        if ent.entity_type not in ALLOWED_ENTITY_TYPES:
            errors.append(f"Entity [{idx}] has invalid entity_type '{ent.entity_type}'")
        
        if not ent.product_name_raw or not ent.product_name_raw.strip():
            errors.append(f"Entity [{idx}] product_name_raw is empty")

        if not verify_source_quote(ent.source_quote, run.source_text_snapshot):
            errors.append(f"Entity [{idx}] source_quote failed verification against source snapshot")

        for attr_idx, attr in enumerate(ent.attributes):
            if not attr.raw_value or not attr.raw_value.strip():
                errors.append(f"Entity [{idx}] Attribute [{attr_idx}] raw_value is empty")
            if not verify_source_quote(attr.source_quote, run.source_text_snapshot):
                errors.append(f"Entity [{idx}] Attribute [{attr_idx}] source_quote failed verification against source snapshot")

    return (len(errors) == 0, errors)

def extraction_run_to_dict(run: ExtractionRun) -> Dict[str, Any]:
    """Serializes an ExtractionRun object to a plain dictionary."""
    return asdict(run)

def extraction_run_from_dict(data: Dict[str, Any]) -> ExtractionRun:
    """Deserializes a dictionary into an ExtractionRun instance."""
    entities_data = data.pop("entities", [])
    run = ExtractionRun(**data)

    entities: List[StructuredEntity] = []
    for ent_dict in entities_data:
        attrs_data = ent_dict.pop("attributes", [])
        attrs = [StructuredAttribute(**attr_dict) for attr_dict in attrs_data]
        ent = StructuredEntity(attributes=attrs, **ent_dict)
        entities.append(ent)

    run.entities = entities
    return run
