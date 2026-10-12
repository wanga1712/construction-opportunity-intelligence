"""Additive migration for the mass canonical object-layer run.

WIP=MASS-CANONICAL-OBJECT-LAYER-RUN-V1.

The migration must (a) widen the status/source/confidence vocabulary exactly as
the code does, (b) keep the raw model output out of the canonical columns,
(c) stay additive + idempotent, and (d) never drop or truncate anything.
"""
from __future__ import annotations

import pathlib

from src.services import object_classification as OC
from src.services import product_candidate_materializer as MAT

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = REPO_ROOT / "src" / "migrations" / "crm_mass_object_layer_run_1.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_exists_and_targets_the_canonical_table() -> None:
    sql = _sql()
    assert "ALTER TABLE crm_procurement_object_classifications" in sql
    assert "crm_procurement_product_candidates" not in sql


def test_migration_is_additive_and_idempotent() -> None:
    sql = _sql()
    assert sql.count("DROP TABLE") == 0
    assert sql.count("TRUNCATE") == 0
    assert sql.count("DELETE FROM") == 0
    # every DROP is guarded, every ADD is guarded; safe to apply twice
    assert sql.count("DROP CONSTRAINT IF EXISTS") >= 5
    assert sql.count("ADD COLUMN IF NOT EXISTS") == 3
    assert "ON_ERROR_STOP" in sql


def test_status_vocabulary_covers_the_code() -> None:
    sql = _sql()
    body = sql.split("ck_cpoc_status", 1)[1].split(");", 1)[0]
    for status in OC.CLASSIFICATION_STATUS_VALUES:
        assert "'%s'" % status in body, status


def test_source_vocabulary_covers_the_code() -> None:
    sql = _sql()
    body = sql.split("ck_cpoc_source", 1)[1].split(");", 1)[0]
    for source in set(OC.ALLOWED_CLASSIFICATION_SOURCES) | {
        OC.SOURCE_UNRESOLVED, OC.SOURCE_QWEN_MODE, OC.SOURCE_QWEN_OBJECT
    }:
        assert "'%s'" % source in body, source


def test_confidence_vocabulary_covers_the_code() -> None:
    sql = _sql()
    body = sql.split("ck_cpoc_confidence_class", 1)[1].split(");", 1)[0]
    for value in (OC.CONFIDENCE_EXPERT, OC.CONFIDENCE_MODEL,
                  OC.CONFIDENCE_HIGH, OC.CONFIDENCE_NONE):
        assert "'%s'" % value in body, value


def test_resolved_model_is_applicable_and_unresolved_stays_unresolved() -> None:
    sql = _sql()
    applicable = sql.split("ck_cpoc_applicable", 1)[1].split(");", 1)[0]
    assert "'RESOLVED_MODEL'" in applicable
    unresolved = sql.split("ck_cpoc_unresolved_axes", 1)[1].split(");", 1)[0]
    for status in (OC.STATUS_MODE_AMBIGUOUS, OC.STATUS_OBJECT_UNCERTAIN,
                   OC.STATUS_MODEL_INVALID, OC.STATUS_OBJECT_MISSING,
                   OC.STATUS_OBJECT_CONFLICT):
        assert "'%s'" % status in unresolved, status


def test_raw_model_output_is_stored_separately() -> None:
    sql = _sql()
    assert "mode_source" in sql
    assert "model_raw" in sql
    assert "model_reason" in sql
    assert "JSONB" in sql


def test_model_confidence_cannot_masquerade_as_human() -> None:
    sql = _sql()
    assert "ck_cpoc_model_provenance" in sql
    body = sql.split("ck_cpoc_model_provenance", 2)[2]
    assert "'QWEN_OBJECT_V1'" in body
    assert "'QWEN_MODE_V1'" in body


def test_qwen_sources_are_not_layer1_object_sources_for_mode_only() -> None:
    # Guard the policy this migration depends on: a mode answer is not an object.
    assert MAT.object_source_allowed(OC.SOURCE_QWEN_OBJECT)
    assert not MAT.object_source_allowed(OC.SOURCE_QWEN_MODE)