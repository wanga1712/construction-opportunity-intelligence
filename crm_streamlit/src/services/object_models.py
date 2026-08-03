"""Модель объекта для страницы «Объекты»."""
from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class ObjectViewItem:
    """Объект в списке с уровнем полноты данных."""
    key: str
    name: str
    address: Optional[str]
    segment: str
    status: Optional[str]
    sources: List[str] = field(default_factory=list)
    pd_number: Optional[str] = None
    expertise_number: Optional[str] = None
    region: Optional[str] = None
    region_id: Optional[int] = None
    registry_type: Optional[str] = None
    tender_id: Optional[int] = None
    doc_matches: int = 0
    matched_files: int = 0
    matched_product_preview: List[str] = field(default_factory=list)
    matched_products_ai: List[str] = field(default_factory=list)
    matched_product_groups: Set[str] = field(default_factory=set)
    matched_products_by_group: dict = field(default_factory=dict)
    docs_volume_preview: Optional[str] = None
    docs_evidence_preview: List[str] = field(default_factory=list)
    docs_preview_line: Optional[str] = None
    balance_holder: Optional[str] = None  # r.customer — текст в реестре контрактов
    customer_name: Optional[str] = None  # организатор торгов (JOIN customer по customer_id)
    customer_inn: Optional[str] = None  # ИНН организатора
    contractor_name: Optional[str] = None
    contractor_inn: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    delivery_start_date: Optional[str] = None
    delivery_end_date: Optional[str] = None
    quality_tier: str = "basic"
    info_flags: List[str] = field(default_factory=list)
    info_score: int = 0
    contract_number: Optional[str] = None
    domrf_object_id: Optional[str] = None
    search_text: str = ""
    ai_priority_score: int = 0
    ai_priority_reason: Optional[str] = None
    ai_delivery_chance: Optional[str] = None
    ai_volume_signal: Optional[str] = None
    ai_sales_action: Optional[str] = None
    ai_manager_next_step: Optional[str] = None
    ai_talk_track: Optional[str] = None
    ai_primary_class: Optional[str] = None
    ai_subcategory: Optional[str] = None
    ai_object_type: Optional[str] = None
    ai_object_subtype: Optional[str] = None
    ai_social_status: Optional[str] = None
    ai_work_type: Optional[str] = None
    ai_project_stage: Optional[str] = None
    ai_stage_signals: List[str] = field(default_factory=list)
    ai_stage_reason: Optional[str] = None
    ai_infrastructure_tags: List[str] = field(default_factory=list)
    ai_classification_confidence: int = 0
    expertise_developer: Optional[str] = None
    expertise_technical_customer: Optional[str] = None
    expertise_planner: Optional[str] = None
    matched_tender_number: Optional[str] = None
    matched_tender_table: Optional[str] = None
    matched_tender_id: Optional[int] = None
    pipeline_stage_code: str = "ai_routed"
    pipeline_stage_label: str = "AI категоризация"
    ai_card_status_code: Optional[str] = None
    ai_card_status_reason: Optional[str] = None
