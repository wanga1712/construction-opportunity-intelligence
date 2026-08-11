from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

class ProcessingOutcome(Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NO_LINKS = "NO_LINKS"

@dataclass
class MatchDetailResult:
    category_code: str
    subcategory_code: str
    matched_term: str
    term_type: str
    score: float
    row_data: Dict[str, Any]
    page_or_sheet: str
    row_number: int
    context_before: Dict[str, Any] = field(default_factory=dict)
    context_after: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MatchResult:
    category_code: str
    match_count: int
    score: float
    details: List[MatchDetailResult]

@dataclass
class EvidenceResult:
    category_code: str
    evidence_score: float
    match_count: int
    next_stage: str = "STRUCTURED_EXTRACTION_PENDING"

@dataclass
class FileProcessResult:
    file_name: str
    status: str  # "COMPLETED", "UNSUPPORTED", "SKIPPED", "FAILED"
    pages: int = 0
    sheets: int = 0
    rows: int = 0
    error_message: Optional[str] = None
    matches: List[MatchResult] = field(default_factory=list)
    local_path: Optional[str] = None
    parent_file_name: Optional[str] = None
    parent_local_path: Optional[str] = None
    archive_member_path: Optional[str] = None

@dataclass
class TaskProcessResult:
    procurement_id: int
    queue_id: int
    outcome: ProcessingOutcome
    files: List[FileProcessResult] = field(default_factory=list)
    evidence: List[EvidenceResult] = field(default_factory=list)
    error_message: Optional[str] = None
