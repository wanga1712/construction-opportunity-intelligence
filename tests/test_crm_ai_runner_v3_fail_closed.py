from __future__ import annotations

import pytest

from src.services.crm_ai_assessment_runner import should_run_legacy_ai_when_v3_enabled
from src.services.commercial_routing_v3.schema_readiness import (
    V3SchemaReadiness,
    decide_v3_runtime_execution_allowed,
)


def test_v3_mode_disallows_legacy_ai_fallback() -> None:
    # Production ignores the flag: AUTOMATIC_V2_FALLBACK is always False.
    # Matches tests/test_v3_routing_contract_pre_golden.py and S13 runtime.
    assert should_run_legacy_ai_when_v3_enabled(True) is False
    assert should_run_legacy_ai_when_v3_enabled(False) is False


def test_schema_missing_refuses_v3_runtime_execution() -> None:
    readiness = V3SchemaReadiness(
        ready=False,
        missing=["missing_table:public.crm_category_okpd_priors"],
        legacy_registry_readable=True,
        live_registry_v3_schema_ready=False,
        missing_details={},
    )
    allowed, reason = decide_v3_runtime_execution_allowed(
        feature_flag_enabled=True,
        readiness=readiness,
    )
    assert allowed is False
    assert reason == "schema_not_ready"


def test_schema_ready_allows_v3_runtime_execution() -> None:
    readiness = V3SchemaReadiness(
        ready=True,
        missing=[],
        legacy_registry_readable=True,
        live_registry_v3_schema_ready=True,
        missing_details={},
    )
    allowed, reason = decide_v3_runtime_execution_allowed(
        feature_flag_enabled=True,
        readiness=readiness,
    )
    assert allowed is True
    assert reason == "ready"
