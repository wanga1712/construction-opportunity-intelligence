"""Document-learning baseline: observation contract only. Workers stay off."""

from src.services.document_learning.config import (
    AUTOMATIC_SKIP_ENABLED,
    automatic_skip_enabled,
    exhaustive_document_discovery_enabled,
    exploration_rate,
)
from src.services.document_learning.contract import (
    CALIBRATION_TRUTH_BY_PROVENANCE,
    OUTCOME_LABELS,
    POLICY_VERSION,
    DocumentObservation,
    calibration_truth_for,
    outcome_from_extraction,
    usefulness_from_extraction,
)
from src.services.document_learning.export import export_jsonl, export_records
from src.services.document_learning.policy import assign_provenance, training_eligibility
from src.services.document_learning.stats import (
    aggregate_by_document_class,
    aggregate_usefulness,
    wilson_interval,
)
from src.services.document_learning.store import insert_observation

__all__ = [
    "AUTOMATIC_SKIP_ENABLED",
    "CALIBRATION_TRUTH_BY_PROVENANCE",
    "OUTCOME_LABELS",
    "POLICY_VERSION",
    "DocumentObservation",
    "aggregate_by_document_class",
    "aggregate_usefulness",
    "assign_provenance",
    "automatic_skip_enabled",
    "calibration_truth_for",
    "exhaustive_document_discovery_enabled",
    "exploration_rate",
    "export_jsonl",
    "export_records",
    "insert_observation",
    "outcome_from_extraction",
    "training_eligibility",
    "usefulness_from_extraction",
    "wilson_interval",
]
