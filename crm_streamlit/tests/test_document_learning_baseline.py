from pathlib import Path
from random import Random

from src.services.document_learning import (
    AUTOMATIC_SKIP_ENABLED,
    DocumentObservation,
    aggregate_usefulness,
    assign_provenance,
    automatic_skip_enabled,
    exhaustive_document_discovery_enabled,
    exploration_rate,
    export_records,
    insert_observation,
    training_eligibility,
    usefulness_from_extraction,
    wilson_interval,
)
from src.services.document_learning.config import (
    EXHAUSTIVE_DOCUMENT_DISCOVERY_ENV,
    EXPLORATION_RATE_ENV,
)


def test_flags_default_off_and_skip_forbidden(monkeypatch) -> None:
    monkeypatch.delenv(EXHAUSTIVE_DOCUMENT_DISCOVERY_ENV, raising=False)
    monkeypatch.delenv(EXPLORATION_RATE_ENV, raising=False)
    assert exhaustive_document_discovery_enabled() is False
    assert automatic_skip_enabled() is False
    assert AUTOMATIC_SKIP_ENABLED is False
    assert 0.05 <= exploration_rate() <= 0.10


def test_usefulness_ignores_selector_score() -> None:
    assert usefulness_from_extraction(selector_score=0.99) == "UNOBSERVED"
    assert usefulness_from_extraction(
        download_status="OK",
        parse_status="OK",
        commercial_evidence_found=True,
        selector_score=0.01,
    ) == "USEFUL"
    assert usefulness_from_extraction(
        download_status="OK",
        parse_status="OK",
        evidence_count=0,
        selector_score=1.0,
    ) == "NOT_USEFUL"
    assert usefulness_from_extraction(download_status="FAILED") == "DOWNLOAD_FAILED"
    assert usefulness_from_extraction(
        download_status="OK", parse_status="FAILED"
    ) == "PARSE_FAILED"


def test_historical_filtered_is_not_calibration_truth() -> None:
    row = DocumentObservation(
        procurement_id=1,
        acquisition_policy="HISTORICAL_FILTERED",
        source_document_id="doc-1",
        usefulness_label="USEFUL",
    )
    assert row.calibration_truth is False
    assert row.observation_key().startswith("1:doc-1:HISTORICAL_FILTERED:")


def test_wilson_one_of_one_is_not_certain() -> None:
    rate, low, high = wilson_interval(1, 1)
    assert rate == 1.0
    assert low is not None and high is not None
    assert low < 1.0
    stats = aggregate_usefulness(
        [
            DocumentObservation(
                procurement_id=1,
                acquisition_policy="EXHAUSTIVE",
                source_document_id="only",
                usefulness_label="USEFUL",
            )
        ]
    )
    assert stats["empirical_useful_rate"] == 1.0
    assert stats["point_estimate_is_certain"] is False
    assert stats["wilson_low"] < 1.0


def test_exhaustive_and_exploration_mix_never_self_selected_only() -> None:
    exhaustive = assign_provenance(
        ["a", "b", "c"], ["a"], exhaustive=True, exploration_rate=0.08
    )
    assert set(exhaustive.values()) == {"EXHAUSTIVE"}
    mixed = assign_provenance(
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        ["a", "b"],
        exhaustive=False,
        exploration_rate=0.10,
        rng=Random(1),
    )
    assert "MODEL_SELECTED" in mixed.values()
    assert "RANDOM_EXPLORATION" in mixed.values()
    assert mixed["a"] == "MODEL_SELECTED"
    assert training_eligibility(["MODEL_SELECTED", "MODEL_SELECTED"])["eligible"] is False
    assert training_eligibility(["HISTORICAL_FILTERED"])["eligible"] is False
    assert training_eligibility(["MODEL_SELECTED", "RANDOM_EXPLORATION"])["eligible"] is True
    assert training_eligibility(["EXHAUSTIVE"])["eligible"] is True


def test_export_marks_self_selected_ineligible() -> None:
    payload = export_records(
        [
            DocumentObservation(
                procurement_id=7,
                acquisition_policy="MODEL_SELECTED",
                source_document_id="sel",
                usefulness_label="USEFUL",
            )
        ]
    )
    assert payload["eligibility"]["eligible"] is False
    assert payload["eligibility"]["reason"] == "SELF_SELECTED_ONLY"
    assert payload["rows"][0]["acquisition_policy"] == "MODEL_SELECTED"


def test_store_inserts_without_ddl() -> None:
    captured: list[tuple[str, tuple]] = []

    class FakeDb:
        def execute_query(self, sql, params=None):
            captured.append((sql, params))
            assert "CREATE" not in sql.upper()
            assert "ALTER" not in sql.upper()
            return [{"id": 15}]

    row = DocumentObservation(
        procurement_id=3,
        acquisition_policy="RANDOM_EXPLORATION",
        source_document_id="x",
        usefulness_label="NOT_USEFUL",
        matched_categories=["cable_support_systems"],
    )
    assert insert_observation(row, FakeDb()) == 15
    assert "INSERT INTO crm_v3_document_observations" in captured[0][0]
    assert captured[0][1][0] == row.observation_key()


def test_migration_is_source_controlled_and_has_no_worker_start() -> None:
    sql = Path("src/migrations/crm_v3_document_observation_1.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS crm_v3_document_observations" in sql
    assert "HISTORICAL_FILTERED" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON crm_v3_document_observations TO crm_app" in sql
    assert "systemctl start" not in sql
    assert "Do NOT start document workers" in sql
