"""
R4 Structured Product Fact Contract & Validation Helpers.
Provides data classes, fingerprinting, quote verification, value-bound field evidence,
numeric & currency consistency, and strict validation rules for R4 structured fact extraction.
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

class ExtractionRunIdentityConflict(ValueError):
    """Raised when an extraction run identity matches an existing run but immutable inputs differ."""
    pass

def normalize_whitespace(text: str) -> str:
    """Normalizes all whitespace (newlines, tabs, spaces) to single spaces and strips."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()

def verify_source_quote(source_quote: str, source_text_snapshot: str) -> bool:
    """
    Validates that normalized source_quote is a non-empty substring of normalized source_text_snapshot.
    """
    if not source_quote or not str(source_quote).strip():
        return False
    if not source_text_snapshot or not str(source_text_snapshot).strip():
        return False
    
    norm_quote = normalize_whitespace(source_quote)
    norm_snapshot = normalize_whitespace(source_text_snapshot)
    return norm_quote in norm_snapshot

def parse_numeric_values_from_string(raw_str: str) -> List[float]:
    """
    Parses numeric values from a raw string (e.g. '10 шт', '4 500,00 руб', '10.5 м3').
    Handles spaces in thousand separators and comma as decimal separator.
    """
    if not raw_str:
        return []
    # Replace spaces inside numbers e.g. "4 500" -> "4500"
    cleaned = re.sub(r"(\d)\s+(\d)", r"\1\2", raw_str)
    # Find decimal numbers with dot or comma
    tokens = re.findall(r"\d+(?:[.,]\d+)?", cleaned)
    results: List[float] = []
    for tok in tokens:
        try:
            val = float(tok.replace(",", "."))
            results.append(val)
        except ValueError:
            pass
    return results

def validate_numeric_consistency(raw_str: Optional[str], value: Optional[float]) -> bool:
    """
    Validates that normalized numeric value is consistent with raw string fact.
    If raw_str contains parseable numbers, value must match one of them.
    """
    if value is None:
        return True
    if not raw_str or not raw_str.strip():
        return False
    
    parsed = parse_numeric_values_from_string(raw_str)
    if not parsed:
        return True  # If complex text cannot be parsed deterministically, raw fact is preserved
    
    return any(abs(p - value) < 1e-4 for p in parsed)

def validate_currency_consistency(raw_str: Optional[str], currency_code: Optional[str]) -> bool:
    """
    Validates that currency_code matches recognized raw wording (руб., рублей, ₽, RUB).
    """
    if not currency_code:
        return True
    if not raw_str or not raw_str.strip():
        return False
    
    norm_raw = normalize_whitespace(raw_str).lower()
    if currency_code.upper() == "RUB":
        return any(term in norm_raw for term in ["руб", "рублей", "рубля", "₽", "rub"])
    
    return True

def compute_sha256(text: str) -> str:
    """Computes UTF-8 SHA256 hex digest of a string."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

def compute_field_evidence_fingerprint(field_name: str, source_quote: str) -> str:
    """Computes a stable deterministic SHA256 fingerprint for field-level documentary evidence."""
    key = "|".join([
        normalize_whitespace(field_name or "").lower(),
        normalize_whitespace(source_quote or ""),
    ])
    return compute_sha256(key)

def compute_entity_fingerprint(
    entity_type: str,
    product_name_raw: str,
    manufacturer_raw: Optional[str] = None,
    brand_raw: Optional[str] = None,
    model_article_raw: Optional[str] = None,
    source_quote: str = "",
) -> str:
    """Computes a stable deterministic SHA256 fingerprint for a structured entity."""
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
    """Computes a stable deterministic SHA256 fingerprint for a structured attribute."""
    key = "|".join([
        normalize_whitespace(attribute_name_normalized or "").lower(),
        normalize_whitespace(raw_value or ""),
        normalize_whitespace(source_quote or ""),
    ])
    return compute_sha256(key)

@dataclass
class StructuredFieldEvidence:
    field_name: str
    source_quote: str
    evidence_fingerprint: str = ""

    def __post_init__(self):
        if not self.evidence_fingerprint:
            self.evidence_fingerprint = compute_field_evidence_fingerprint(
                self.field_name, self.source_quote
            )

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
    quantity_raw: Optional[str] = None
    quantity_value: Optional[float] = None
    quantity_unit_raw: Optional[str] = None
    quantity_unit_normalized: Optional[str] = None
    unit_price_raw: Optional[str] = None
    unit_price_value: Optional[float] = None
    total_price_raw: Optional[str] = None
    total_price_value: Optional[float] = None
    currency_raw: Optional[str] = None
    currency_code: Optional[str] = None  # Nullable currency (Section 13: NO default RUB!)
    confidence: Optional[float] = None
    field_evidence: List[StructuredFieldEvidence] = field(default_factory=list)
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
    source_validator_name: str
    source_validator_version: str
    source_validation_method: str
    source_text_sha256: str = ""
    match_id: Optional[int] = None
    queue_id: Optional[int] = None
    subcategory_code: Optional[str] = None
    document_name: Optional[str] = None
    archive_member_path: Optional[str] = None
    page_or_sheet: Optional[str] = None
    row_number: Optional[int] = None
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
    Strictly validates an ExtractionRun instance for:
    1. Mandatory explicit source provenance (context_validator v4 QWEN_CONTEXT_V4)
    2. SHA256 snapshot consistency
    3. Valid entity types
    4. Value-bound field-level evidence (source quote MUST contain raw_value and exist in snapshot)
    5. Numeric & currency normalization consistency
    6. Attribute raw value provenance within attribute source_quote
    """
    errors: List[str] = []

    # 1. Source Provenance Explicitness (Section 5 & 6)
    if not run.source_validator_name or run.source_validator_name != "context_validator":
        errors.append(f"Invalid source_validator_name '{run.source_validator_name}': expected 'context_validator'")
    if not run.source_validator_version or run.source_validator_version.lower() != "v4":
        errors.append(f"Invalid source_validator_version '{run.source_validator_version}': expected 'v4'")
    if not run.source_validation_method or run.source_validation_method.upper() != "QWEN_CONTEXT_V4":
        errors.append(f"Invalid source_validation_method '{run.source_validation_method}': expected 'QWEN_CONTEXT_V4'")

    # 2. Source Snapshot & SHA (Section 9, 10, 11)
    if not run.source_text_snapshot or not run.source_text_snapshot.strip():
        errors.append("source_text_snapshot is empty")
    else:
        calc_sha = compute_sha256(run.source_text_snapshot)
        if run.source_text_sha256 and run.source_text_sha256 != calc_sha:
            errors.append(f"source_text_sha256 mismatch: expected {calc_sha}, got {run.source_text_sha256}")

    # 3. Entity & Field Evidence Validation (Section 14 & 15)
    core_field_map = [
        ("product_name_raw", "product_name"),
        ("manufacturer_raw", "manufacturer"),
        ("brand_raw", "brand"),
        ("product_line_raw", "product_line"),
        ("model_article_raw", "model_article"),
        ("quantity_raw", "quantity"),
        ("unit_price_raw", "unit_price"),
        ("total_price_raw", "total_price"),
        ("currency_raw", "currency"),
    ]

    for idx, ent in enumerate(run.entities):
        if ent.entity_type not in ALLOWED_ENTITY_TYPES:
            errors.append(f"Entity [{idx}] has invalid entity_type '{ent.entity_type}'")
        
        if not ent.product_name_raw or not ent.product_name_raw.strip():
            errors.append(f"Entity [{idx}] product_name_raw is empty")

        if not verify_source_quote(ent.source_quote, run.source_text_snapshot):
            errors.append(f"Entity [{idx}] entity anchor source_quote failed verification against source snapshot")

        # Field Evidence Index
        field_ev_quotes: Dict[str, List[str]] = {}
        for fe in ent.field_evidence:
            if not fe.source_quote or not verify_source_quote(fe.source_quote, run.source_text_snapshot):
                errors.append(f"Entity [{idx}] FieldEvidence '{fe.field_name}' quote failed verification against source snapshot")
            field_ev_quotes.setdefault(fe.field_name, []).append(fe.source_quote)

        # Check raw core field value-bound provenance (Section 14 & 15)
        for raw_attr, field_name in core_field_map:
            raw_val = getattr(ent, raw_attr, None)
            if raw_val:
                quotes = field_ev_quotes.get(field_name, [])
                if not quotes:
                    errors.append(f"Entity [{idx}] populated '{raw_attr}' requires '{field_name}' field_evidence")
                else:
                    norm_val = normalize_whitespace(raw_val)
                    supported = any(norm_val in normalize_whitespace(q) for q in quotes)
                    if not supported:
                        errors.append(f"Entity [{idx}] raw_value '{raw_val}' for '{field_name}' is NOT supported by field_evidence quote(s)")

        # Numeric / Normalized Consistency Checks (Section 16 & 17)
        if ent.quantity_value is not None:
            if not ent.quantity_raw:
                errors.append(f"Entity [{idx}] populated quantity_value requires quantity_raw")
            elif not validate_numeric_consistency(ent.quantity_raw, ent.quantity_value):
                errors.append(f"Entity [{idx}] quantity_value {ent.quantity_value} inconsistent with quantity_raw '{ent.quantity_raw}'")

        if ent.unit_price_value is not None:
            if not ent.unit_price_raw:
                errors.append(f"Entity [{idx}] populated unit_price_value requires unit_price_raw")
            elif not validate_numeric_consistency(ent.unit_price_raw, ent.unit_price_value):
                errors.append(f"Entity [{idx}] unit_price_value {ent.unit_price_value} inconsistent with unit_price_raw '{ent.unit_price_raw}'")

        if ent.total_price_value is not None:
            if not ent.total_price_raw:
                errors.append(f"Entity [{idx}] populated total_price_value requires total_price_raw")
            elif not validate_numeric_consistency(ent.total_price_raw, ent.total_price_value):
                errors.append(f"Entity [{idx}] total_price_value {ent.total_price_value} inconsistent with total_price_raw '{ent.total_price_raw}'")

        if ent.currency_code is not None:
            if not ent.currency_raw:
                errors.append(f"Entity [{idx}] populated currency_code requires currency_raw")
            elif not validate_currency_consistency(ent.currency_raw, ent.currency_code):
                errors.append(f"Entity [{idx}] currency_code '{ent.currency_code}' inconsistent with currency_raw '{ent.currency_raw}'")

        # Attribute Value Provenance (Section 18 & 19)
        for attr_idx, attr in enumerate(ent.attributes):
            if not attr.raw_value or not attr.raw_value.strip():
                errors.append(f"Entity [{idx}] Attribute [{attr_idx}] raw_value is empty")
            if not verify_source_quote(attr.source_quote, run.source_text_snapshot):
                errors.append(f"Entity [{idx}] Attribute [{attr_idx}] source_quote failed verification against source snapshot")
            else:
                norm_attr_raw = normalize_whitespace(attr.raw_value)
                norm_attr_quote = normalize_whitespace(attr.source_quote)
                if norm_attr_raw not in norm_attr_quote:
                    errors.append(f"Entity [{idx}] Attribute [{attr_idx}] raw_value '{attr.raw_value}' is NOT supported by attribute source_quote '{attr.source_quote}'")

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
        field_ev_data = ent_dict.pop("field_evidence", [])
        
        attrs = [StructuredAttribute(**attr_dict) for attr_dict in attrs_data]
        field_ev = [StructuredFieldEvidence(**fe_dict) for fe_dict in field_ev_data]
        
        ent = StructuredEntity(attributes=attrs, field_evidence=field_ev, **ent_dict)
        entities.append(ent)

    run.entities = entities
    return run
