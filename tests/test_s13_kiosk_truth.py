import sys
from pathlib import Path

DEPLOY = Path(__file__).parents[1] / "deploy"
sys.path.insert(0, str(DEPLOY))

import s13_kiosk_truth as truth


def test_same_cohort_funnel_reconciles_and_terminal_ambiguity_is_not_rejection():
    crm_rows = [
        ["1", "COMPLETED", "candidate", "", "ELIGIBLE", truth.ADMISSION_POLICY, "OPEN", "1", "ACTIVE", "DOCUMENT_RESEARCH_REQUIRED", "t", "t", "f", "t", "f"],
        ["2", "UNASSESSED", "unassessed", "", "ELIGIBLE", truth.ADMISSION_POLICY, "OPEN", "0", "", "", "f", "f", "t", "f", "f"],
        ["3", "COMPLETED", "unassessed", "", "ELIGIBLE", truth.ADMISSION_POLICY, "OPEN", "0", "", "", "f", "t", "f", "t", "f"],
        ["4", "OUT_OF_PROFILE", "out_of_profile", "", "ELIGIBLE", truth.ADMISSION_POLICY, "OPEN", "0", "", "", "f", "f", "t", "t", "f"],
    ]
    calls = []

    def query(db, sql, timeout):
        calls.append((db, sql, timeout))
        if db == "crm":
            return "\n".join("|".join(row) for row in crm_rows)
        if "estimate_row_normalization_procurements" in sql:
            return "\n".join(["1|1|COMPLETED|t", "2|0||f", "3|0||f", "4|0||f"])
        return "\n".join([
            "1||f|f|f|f||f|t|t|1",
            "2||f|f|f|f||f|f|f|0",
            "3||f|f|f|f||f|f|f|0",
            "4||f|f|f|f||f|f|f|0",
        ])

    result = truth.collect_today_truth(query, captured_at="snapshot")
    assert result["received"] == 4
    assert result["commercial"] == {"accepted": 1, "rejected": 1, "processing": 1, "error": 1, "denominator": 4}
    assert sum(result["commercial"][k] for k in ("accepted", "rejected", "processing", "error")) == result["received"]
    assert result["review_required_ids"] == [3]
    assert result["lifecycle"] == {"actionable": 1, "closed": 0, "error": 0, "denominator": 1}
    assert result["documents"]["already_researched"] == 1
    assert result["normalization"] == {"parsed": 1, "normalized": 1, "pending": 0, "failed": 0, "denominator": 1}
    assert result["ready_cards"]["count"] == 1
    assert "current_date" in calls[0][1]
    assert all("ARRAY[1,2,3,4]" in sql for _, sql, _ in calls[1:])


def test_processing_without_a_live_document_worker_is_not_active():
    crm_rows = [["7", "COMPLETED", "candidate", "", "ELIGIBLE", truth.ADMISSION_POLICY, "OPEN", "1", "ACTIVE", "DOCUMENT_RESEARCH_REQUIRED", "f", "t", "f", "t", "f"]]

    def query(db, sql, timeout):
        if db == "crm":
            return "|".join(crm_rows[0])
        if "estimate_row_normalization_procurements" in sql:
            return "7|0||f"
        return "7|PROCESSING|t|f|f|f|3|f|f|f|0"

    result = truth.collect_today_truth(query, live_document_workers=0)
    assert result["documents"]["in_progress"] == 0
    assert result["documents"]["failed"] == 1
    assert result["documents"]["stale_processing"] == 1
