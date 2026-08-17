"""Three commercial-decision authorities.

MODEL_RAW_DECISION       — Qwen/routing proposal (procurement_ai_assessments)
EXPERT_ANNOTATION        — human correction (crm_v3_expert_annotations)
CURRENT_ACCEPTED_DECISION — production commercial truth
                            (crm_procurement_category_opportunities status=CURRENT)

Shadow mode: new model results stay MODEL_RAW and must not auto-promote
into CURRENT_ACCEPTED_DECISION.
"""
from __future__ import annotations

import os

MODEL_RAW_DECISION = "MODEL_RAW_DECISION"
EXPERT_ANNOTATION = "EXPERT_ANNOTATION"
CURRENT_ACCEPTED_DECISION = "CURRENT_ACCEPTED_DECISION"

SHADOW_ENV = "CRM_V3_QWEN_SHADOW_MODE"
INFERENCE_ENV = "CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED"


def qwen_shadow_mode() -> bool:
    return os.getenv(SHADOW_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


def qwen_candidate_inference_enabled() -> bool:
    """Production freeze sets this to 0. Default 1 for tests/dev."""
    return os.getenv(INFERENCE_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def automatic_model_acceptance_enabled() -> bool:
    return (not qwen_shadow_mode()) and qwen_candidate_inference_enabled()
