from __future__ import annotations

import json
from pathlib import Path

from eis_ingestion.observability.source_day_sla import source_day_status


def test_region_progress_means_incomplete(tmp_path: Path):
    pd = tmp_path / "processed_dates.json"
    rp = tmp_path / "region_progress.json"
    pd.write_text("[]", encoding="utf-8")
    rp.write_text(
        json.dumps({"2026-08-12": {"processed_regions": ["1", "10", "15", "16"]}}),
        encoding="utf-8",
    )
    status = source_day_status("2026-08-12", pd, rp)
    assert status.complete is False
    assert status.region_progress_count == 4
    assert status.reason == "REGION_PROGRESS_PRESENT"


def test_cursor_file_alone_is_not_complete(tmp_path: Path):
    pd = tmp_path / "processed_dates.json"
    rp = tmp_path / "region_progress.json"
    pd.write_text('["2026-08-12"]', encoding="utf-8")
    rp.write_text("{}", encoding="utf-8")
    status = source_day_status("2026-08-12", pd, rp)
    assert status.complete is False
    assert status.in_processed_dates is True
