from pathlib import Path
from random import Random

import pytest

from src.services.document_learning import (
    AUTOMATIC_SKIP_ENABLED,
    DocumentObservation,
    aggregate_by_document_class,
    aggregate_usefulness,
    assign_provenance,
    automatic_skip_enabled,
    calibration_truth_for,
    exhaustive_document_discovery_enabled,
    exploration_rate,
    export_records,
    insert_observation,
    outcome_from_extraction,
    training_eligibility,
    usefulness_from_extraction,
    wilson_interval,
)
from src.services.document_learning.config import (
    EXHAUSTIVE_DOCUMENT_DISCOVERY_ENV,
    EXPLORATION_RATE_ENV,
)
from src.services.document_learning.stats import required_group_fields


def _obs(**kwargs) -> DocumentObservation:
    payload = {
        "procurement_id": 1,
        "acquisition_policy": "EXHAUSTIVE",
        "source_document_id": "doc-1",
        "usefulness_label": "UNOBSERVED",
    }
    payload.update(kwargs)
    return DocumentObservation(**payload)


def test_flags_default_off_and_skip_forbidden(monkeypatch) -> None:
    monkeypatch.delenv(EXHAUSTIVE_DOCUMENT_DISCOVERY_ENV, raising=False)
    monkeypatch.delenv(EXPLORATION_RATE_ENV, raising=False)
    assert exhaustive_document_discovery_enabled() is False
    assert automatic_skip_enabled() is False
    assert AUTOMATIC_SKIP_ENABLED is False
    assert 0.05 <= exploration_rate() <= 0.10


def test_outcomes_are_factual_and_ignore_selector_score() -> None:
    assert outcome_from_extraction(selector_score=0.99) == "UNOBSERVED"
    assert outcome_from_extraction(
        download_status="OK",
        parse_status="OK",
        commercial_evidence_found=True,
        selector_score=0.01,
    ) == "USEFUL_COMMERCIAL_EVIDENCE"
    assert outcome_from_extraction(
        download_status="OK",
        parse_status="OK",
        evidence_count=0,
        selector_score=1.0,
    ) == "PARSED_NO_COMMERCIAL_EVIDENCE"
    assert outcome_from_extraction(download_status="FAILED") == "DOWNLOAD_FAILED"
    assert outcome_from_extraction(
        download_status="OK", parse_status="FAILED"
    ) == "PARSE_FAILED"
    assert outcome_from_extraction(
        download_status="OK", parse_status="UNSUPPORTED"
    ) == "UNSUPPORTED_FORMAT"
    assert outcome_from_extraction(
        download_status="OK", parse_status="OK", file_size=0
    ) == "EMPTY_DOCUMENT"
    assert outcome_from_extraction(
        download_status="OK", parse_status="OK", is_duplicate=True
    ) == "DUPLICATE_DOCUMENT"
    assert usefulness_from_extraction(
        download_status="OK", parse_status="OK", evidence_count=2
    ) == "USEFUL_COMMERCIAL_EVIDENCE"


def test_failures_are_not_collapsed_into_no_evidence() -> None:
    failures = [
        outcome_from_extraction(download_status="FAILED"),
        outcome_from_extraction(download_status="OK", parse_status="FAILED"),
        outcome_from_extraction(download_status="OK", parse_status="UNSUPPORTED"),
        outcome_from_extraction(download_status="OK", parse_status="EMPTY"),
        outcome_from_extraction(is_duplicate=True, download_status="OK", parse_status="OK"),
    ]
    assert "PARSED_NO_COMMERCIAL_EVIDENCE" not in failures
    assert "USEFUL" not in failures
    assert "NOT_USEFUL" not in failures
    with pytest.raises(ValueError, match="unknown usefulness_label"):
        _obs(usefulness_label="NOT_USEFUL")
    with pytest.raises(ValueError, match="unknown usefulness_label"):
        _obs(usefulness_label="USEFUL")


def test_calibration_truth_is_unbiased_only_for_exhaustive_and_exploration() -> None:
    assert calibration_truth_for("EXHAUSTIVE") is True
    assert calibration_truth_for("RANDOM_EXPLORATION") is True
    assert calibration_truth_for("MODEL_SELECTED") is False
    assert calibration_truth_for("HISTORICAL_FILTERED") is False
    exhaustive = _obs(acquisition_policy="EXHAUSTIVE", calibration_truth=False)
    explore = _obs(
        acquisition_policy="RANDOM_EXPLORATION",
        source_document_id="e",
        calibration_truth=False,
    )
    selected = _obs(
        acquisition_policy="MODEL_SELECTED",
        source_document_id="s",
        usefulness_label="USEFUL_COMMERCIAL_EVIDENCE",
        calibration_truth=True,
    )
    historical = _obs(
        acquisition_policy="HISTORICAL_FILTERED",
        source_document_id="h",
        usefulness_label="USEFUL_COMMERCIAL_EVIDENCE",
        calibration_truth=True,
    )
    assert exhaustive.calibration_truth is True
    assert explore.calibration_truth is True
    assert selected.calibration_truth is False
    assert historical.calibration_truth is False
    assert selected.to_record()["calibration_truth"] is False
    exported = export_records([selected])
    assert exported["rows"][0]["calibration_truth"] is False
    assert exported["eligibility"]["eligible"] is False


def test_wilson_one_of_one_is_not_certain() -> None:
    rate, low, high = wilson_interval(1, 1)
    assert rate == 1.0
    assert low is not None and high is not None
    assert low < 1.0
    stats = aggregate_usefulness(
        [
            _obs(
                usefulness_label="USEFUL_COMMERCIAL_EVIDENCE",
            )
        ]
    )
    assert stats["empirical_useful_rate"] == 1.0
    assert stats["point_estimate_is_certain"] is False
    assert stats["wilson_low"] < 1.0


def test_document_class_stats_use_source_type_and_keep_title_signals() -> None:
    rows = [
        _obs(
            procurement_id=10,
            source_document_id="a",
            source_document_type="Техническое задание",
            document_title="ТЗ школа",
            usefulness_label="USEFUL_COMMERCIAL_EVIDENCE",
            acquisition_policy="EXHAUSTIVE",
        ),
        _obs(
            procurement_id=11,
            source_document_id="b",
            source_document_type="Техническое задание",
            document_title="ТЗ больница",
            usefulness_label="PARSED_NO_COMMERCIAL_EVIDENCE",
            acquisition_policy="RANDOM_EXPLORATION",
        ),
        _obs(
            procurement_id=11,
            source_document_id="c",
            source_document_type="Техническое задание",
            document_title="ТЗ больница",
            usefulness_label="DOWNLOAD_FAILED",
            acquisition_policy="MODEL_SELECTED",
        ),
        _obs(
            procurement_id=12,
            source_document_id="d",
            source_document_type=None,
            document_title="Извещение о закупке.pdf",
            file_extension="pdf",
            mime_type="application/pdf",
            usefulness_label="PARSE_FAILED",
            acquisition_policy="HISTORICAL_FILTERED",
        ),
    ]
    groups = aggregate_by_document_class(rows)
    tz = next(item for item in groups if item["document_class"] == "Техническое задание")
    for field in required_group_fields():
        assert field in tz
    assert tz["observations"] == 3
    assert tz["procurements"] == 2
    assert tz["download_successes"] == 2
    assert tz["download_failures"] == 1
    assert tz["parse_successes"] == 2
    assert tz["parse_failures"] == 0
    assert tz["useful_count"] == 1
    assert tz["no_evidence_count"] == 1
    assert tz["empirical_useful_rate"] == 0.5
    assert tz["wilson_low"] < tz["empirical_useful_rate"] < tz["wilson_high"]
    assert tz["by_provenance"]["EXHAUSTIVE"] == 1
    assert tz["by_provenance"]["RANDOM_EXPLORATION"] == 1
    assert tz["by_provenance"]["MODEL_SELECTED"] == 1
    assert tz["by_provenance"]["HISTORICAL_FILTERED"] == 0
    untitled = next(item for item in groups if item["document_class"] is None)
    assert untitled["title_signal"] == "извещение о закупке.pdf"
    assert untitled["file_extension"] == "pdf"
    assert untitled["parse_failures"] == 1
    assert untitled["useful_count"] == 0
    assert untitled["no_evidence_count"] == 0
    assert untitled["empirical_useful_rate"] is None
    assert untitled["by_provenance"]["HISTORICAL_FILTERED"] == 1


def test_document_class_is_not_inferred_from_title() -> None:
    row = _obs(
        source_document_type=None,
        document_title="Локальная смета №1",
        usefulness_label="USEFUL_COMMERCIAL_EVIDENCE",
    )
    groups = aggregate_by_document_class([row])
    assert groups[0]["document_class"] is None
    assert groups[0]["title_signal"] == "локальная смета №1"


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


def test_store_inserts_without_ddl() -> None:
    captured: list[tuple[str, tuple]] = []

    class FakeDb:
        def execute_query(self, sql, params=None):
            captured.append((sql, params))
            assert "CREATE" not in sql.upper()
            assert "ALTER" not in sql.upper()
            return [{"id": 15}]

    row = _obs(
        procurement_id=3,
        acquisition_policy="RANDOM_EXPLORATION",
        source_document_id="x",
        usefulness_label="PARSED_NO_COMMERCIAL_EVIDENCE",
        matched_categories=["cable_support_systems"],
    )
    assert insert_observation(row, FakeDb()) == 15
    assert "INSERT INTO crm_v3_document_observations" in captured[0][0]
    assert captured[0][1][0] == row.observation_key()
    assert captured[0][1][-1] is True


def test_migration_is_source_controlled_and_has_no_worker_start() -> None:
    sql = Path("src/migrations/crm_v3_document_observation_1.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS crm_v3_document_observations" in sql
    assert "USEFUL_COMMERCIAL_EVIDENCE" in sql
    assert "PARSED_NO_COMMERCIAL_EVIDENCE" in sql
    assert "UNSUPPORTED_FORMAT" in sql
    assert "EMPTY_DOCUMENT" in sql
    assert "DUPLICATE_DOCUMENT" in sql
    assert "MODEL_SELECTED=FALSE" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON crm_v3_document_observations TO crm_app" in sql
    assert "systemctl start" not in sql
    assert "Do NOT start document workers" in sql
    assert "'USEFUL'" not in sql or "USEFUL_COMMERCIAL_EVIDENCE" in sql
    assert "NOT_USEFUL" not in sql
