"""Data Transfer Objects for Document Product Discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional


class RowType(str, Enum):
    """Classification of a row in an estimate, BOQ, or specification."""
    PRODUCT = "PRODUCT"
    MATERIAL = "MATERIAL"
    EQUIPMENT = "EQUIPMENT"
    WORK = "WORK"
    SERVICE = "SERVICE"
    MACHINE = "MACHINE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DiscoveryStatus(str, Enum):
    """Lifecycle status of an auto-discovered product category."""
    AUTO_DISCOVERED = "AUTO_DISCOVERED"
    MODEL_CONFIRMED = "MODEL_CONFIRMED"
    EXPERT_CONFIRMED = "EXPERT_CONFIRMED"
    REJECTED = "REJECTED"
    MERGED = "MERGED"


class UnitCategory(str, Enum):
    """Standardized physical measurement unit categories."""
    PCS = "PCS"          # штуки, комплекты, единицы
    LENGTH = "LENGTH"    # метры, км
    AREA = "AREA"        # кв. метры, м2
    VOLUME = "VOLUME"    # куб. метры, литры
    WEIGHT = "WEIGHT"    # кг, тонны
    SET = "SET"          # комплекты, наборы
    OTHER = "OTHER"      # неизвестные или составные единицы


@dataclass
class ExtractedTableRow:
    """Raw table row parsed deterministically from an uploaded or downloaded document."""
    procurement_id: int
    document_id: str
    file_path: str
    sheet_name: str
    page_number: Optional[int]
    table_index: int
    row_index: int
    raw_cells: List[str]
    raw_text: str
    section_name: str = ""
    column_mapping: Dict[str, int] = field(default_factory=dict)
    observation_key: str = ""

    def compute_observation_key(self, doc_hash: str = "") -> str:
        """Computes deterministic stable hash key for this extracted row."""
        raw_sig = f"{self.procurement_id}:{doc_hash or self.document_id}:{self.sheet_name or self.page_number}:{self.table_index}:{self.row_index}:{self.raw_text.strip()}".encode("utf-8")
        self.observation_key = hashlib.sha256(raw_sig).hexdigest()
        return self.observation_key


@dataclass
class ProductNormalizationDecision:
    """Structured normalization result from model / rule normalizer."""
    item_type: RowType
    normalized_product_name: str
    domain: str = "GENERAL"
    category_name: str = ""
    subcategory_name: str = ""
    product_family: str = ""
    aliases: List[str] = field(default_factory=list)
    confidence: float = 0.8
    novelty_probability: float = 0.0
    explanation: str = ""


@dataclass
class ProductObservationDTO:
    """Individual product observation extracted from a tender document row."""
    observation_id: str
    procurement_id: int
    document_id: Optional[str] = None
    file_path: Optional[str] = None
    sheet_name: Optional[str] = None
    section_name: Optional[str] = None
    row_index: int = 0
    raw_text: str = ""
    normalized_name: str = ""
    category_name: str = ""
    domain: str = "GENERAL"
    subcategory_name: str = ""
    product_family: str = ""
    row_type: RowType = RowType.UNKNOWN
    quantity: float = 0.0
    unit_raw: str = ""
    unit_category: UnitCategory = UnitCategory.OTHER
    unit_price: float = 0.0
    total_amount: float = 0.0
    is_seed: bool = False
    seed_observation_id: Optional[str] = None
    confidence: float = 0.5
    observation_key: str = ""
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["row_type"] = self.row_type.value
        data["unit_category"] = self.unit_category.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProductObservationDTO":
        d = dict(data)
        d["row_type"] = RowType(d.get("row_type", RowType.UNKNOWN))
        d["unit_category"] = UnitCategory(d.get("unit_category", UnitCategory.OTHER))
        return cls(**d)


@dataclass
class ProductCategoryDTO:
    """Canonical or discovered product category with hierarchy support."""
    category_id: str
    canonical_name: str
    domain: str = "GENERAL"
    parent_category_id: Optional[str] = None
    hierarchy_level: str = "CATEGORY"  # DOMAIN, CATEGORY, SUBCATEGORY, PRODUCT_FAMILY
    status: DiscoveryStatus = DiscoveryStatus.AUTO_DISCOVERED
    first_discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observation_count: int = 0
    procurement_count: int = 0
    total_discovered_amount: float = 0.0
    aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProductCategoryDTO":
        d = dict(data)
        d["status"] = DiscoveryStatus(d.get("status", DiscoveryStatus.AUTO_DISCOVERED))
        return cls(**d)


@dataclass
class CategoryRelationDTO:
    """Co-occurrence and quantitative relationship between two product categories."""
    category_a: str
    category_b: str
    co_occurrence_count: int = 0
    conditional_prob_b_given_a: float = 0.0
    conditional_prob_a_given_b: float = 0.0
    median_amount_ratio: float = 0.0
    median_quantity_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CategoryRelationDTO":
        return cls(**data)

