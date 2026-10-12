"""Tests for the Qwen escalation contract (WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1).

No network: the transport call is injected, so every branch of the canonical
validation is exercised deterministically.
"""
from __future__ import annotations

import pytest

from src.services import expert_object_taxonomy as OT
from src.services import object_classification as OC
from src.services import product_ontology as PO
from src.services import qwen_object_classifier as Q


def _call(response: str):
    def _fn(prompt: str, **_kwargs):
        return {"response": response}

    return _fn


def _boom(exc: Exception):
    def _fn(prompt: str, **_kwargs):
        raise exc

    return _fn


# --- prompts ----------------------------------------------------------------
def test_object_prompt_is_built_from_taxonomy_only() -> None:
    prompt = Q.build_object_prompt(7, "Ремонт моста", "42.11", "x")
    for sector in OT.OBJECT_SECTOR_VALUES:
        assert sector in prompt
    for object_type in sorted(OT.all_object_types()):
        assert object_type in prompt
    assert "object_applicable" in prompt
    assert "YES|UNKNOWN" in prompt


def test_mode_prompt_offers_only_canonical_modes() -> None:
    prompt = Q.build_mode_prompt(7, "Поставка ноутбуков", "26.20", "x")
    for mode in PO.PROCUREMENT_MODE_VALUES:
        assert mode in prompt


# --- mode stage -------------------------------------------------------------
@pytest.mark.parametrize("mode", PO.PROCUREMENT_MODE_VALUES)
def test_mode_stage_accepts_every_canonical_mode(mode: str) -> None:
    result = Q.classify_mode_via_model(
        "x", call=_call('{"procurement_mode":"%s","confidence":91,"reason":"r"}' % mode)
    )
    assert result.ok and result.mode == mode
    assert result.confidence == 91


def test_mode_stage_rejects_non_canonical_value() -> None:
    result = Q.classify_mode_via_model("x", call=_call('{"procurement_mode":"WORKS"}'))
    assert not result.ok and result.invalid and result.mode is None
    assert result.reason.startswith("NON_CANONICAL_MODE")


def test_mode_stage_rejects_unparsable_answer() -> None:
    result = Q.classify_mode_via_model("x", call=_call("не json вовсе"))
    assert result.invalid and result.reason == "UNPARSABLE_JSON"


def test_mode_stage_surfaces_transport_error_without_persisting() -> None:
    result = Q.classify_mode_via_model("x", call=_boom(RuntimeError("connection refused")))
    assert result.error and not result.invalid and result.mode is None


def test_mode_stage_parses_fenced_json() -> None:
    fenced = '```json\n{"procurement_mode": "DIRECT", "confidence": 80}\n```'
    result = Q.classify_mode_via_model("x", call=_call(fenced))
    assert result.ok and result.mode == PO.PROCUREMENT_MODE_DIRECT


# --- object stage -----------------------------------------------------------
def test_object_stage_resolves_valid_axes() -> None:
    payload = (
        '{"object_applicable":"YES","object_sector":"INFRASTRUCTURE","object_type":"BRIDGE",'
        '"object_subtype":"NONE","object_context":["landscaping"],"application_area":[],'
        '"confidence":88,"reason":"мост"}'
    )
    result = Q.classify_object_via_model("x", call=_call(payload))
    assert result.status == OC.STATUS_RESOLVED_MODEL
    assert (result.sector, result.object_type) == ("INFRASTRUCTURE", "BRIDGE")
    assert result.object_subtype is None
    assert result.object_context == "landscaping"
    assert result.application_area is None
    assert OC.validate_classification(
        OC.model_row(
            "OBJECT", status=result.status, sector=result.sector,
            object_type=result.object_type, object_subtype=result.object_subtype,
            object_context=result.object_context, application_area=result.application_area,
        ).as_row(1)
    ) == ()


def test_object_stage_rejects_type_from_wrong_sector() -> None:
    payload = '{"object_applicable":"YES","object_sector":"RESIDENTIAL","object_type":"URBAN_IMPROVEMENT"}'
    result = Q.classify_object_via_model("x", call=_call(payload))
    assert result.status == OC.STATUS_MODEL_INVALID and result.invalid
    assert not result.sector and not result.object_type


def test_object_stage_rejects_unknown_sector() -> None:
    payload = '{"object_applicable":"YES","object_sector":"SPACE","object_type":"ROAD"}'
    assert Q.classify_object_via_model("x", call=_call(payload)).status == OC.STATUS_MODEL_INVALID


def test_object_stage_reports_uncertain_object_as_object_uncertain() -> None:
    result = Q.classify_object_via_model(
        "x", call=_call('{"object_applicable":"UNKNOWN","confidence":10,"reason":"мало данных"}')
    )
    assert result.status == OC.STATUS_OBJECT_UNCERTAIN
    assert result.object_type is None


def test_object_stage_drops_non_canonical_subtype_but_keeps_object() -> None:
    payload = (
        '{"object_applicable":"YES","object_sector":"INFRASTRUCTURE","object_type":"ROAD",'
        '"object_subtype":"WATER_NETWORK"}'
    )
    result = Q.classify_object_via_model("x", call=_call(payload))
    assert result.status == OC.STATUS_RESOLVED_MODEL
    assert result.object_subtype is None


def test_object_stage_invalid_on_transport_error() -> None:
    result = Q.classify_object_via_model("x", call=_boom(TimeoutError("timeout")))
    assert result.status == OC.STATUS_MODEL_INVALID and result.error


def test_classifier_stats_freezes_model_settings() -> None:
    stats = Q.classifier_stats()
    assert stats["model"] == "qwen2.5:7b"
    assert stats["temperature"] == 0 and stats["seed"] == 42
    assert stats["classifier_version"] == "qwen_object_v1"