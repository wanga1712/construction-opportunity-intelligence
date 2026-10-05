"""Config-level authority tests for S13 document worker deployment.

These validate the committed deploy authority, not runtime behaviour:
- exactly five production workers;
- three legacy/disabled units;
- awarded selects the S13 document backend (no legacy fallback);
- no per-worker fixed CPUQuota (floating pool only).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "systemd"

ACTIVE = {
    "tender-docs-daemon-open.service",
    "tender-docs-daemon-open-2.service",
    "tender-docs-daemon-awarded.service",
    "tender-docs-daemon-awarded-2.service",
    "tender-docs-daemon-computers.service",
}
DISABLED = {
    "tender-docs-daemon.service",
    "tender-docs-daemon-open-3.service",
    "tender-docs-daemon-computers-2.service",
}


def _manifest() -> str:
    return (DEPLOY / "PRODUCTION_DOC_WORKERS.md").read_text(encoding="utf-8")


def test_active_worker_set_is_exactly_five():
    text = _manifest()
    assert len(ACTIVE) == 5
    for unit in ACTIVE:
        assert unit in text


def test_disabled_units_listed_and_marked():
    text = _manifest()
    for unit in DISABLED:
        assert unit in text
        assert "DISABLED" in (DEPLOY / unit).read_text(encoding="utf-8")


def test_awarded_selects_s13_document_backend():
    dropin = DEPLOY / "tender-docs-daemon-awarded.service.d" / "zz-s13v4-backend.conf"
    text = dropin.read_text(encoding="utf-8")
    assert "PROCESSING_BACKEND=S13_V4" in text
    assert "S13_DOCUMENT_DB_NAME=document_intelligence" in text
    assert "S13_DOCUMENT_DB_HOST=127.0.0.1" in text


def test_no_active_worker_can_fall_back_to_legacy_queue():
    for unit in ACTIVE:
        dropin = DEPLOY / f"{unit}.d" / "zz-s13v4-backend.conf"
        assert dropin.exists(), f"{unit} has no S13_V4 backend drop-in"
        text = dropin.read_text(encoding="utf-8")
        assert "document_intelligence" in text
        assert "tender_monitor" not in text


def test_no_fixed_per_worker_cpuquota():
    for unit in ACTIVE:
        unit_text = (DEPLOY / unit).read_text(encoding="utf-8")
        assert "CPUQuota=700%" not in unit_text
        assert "CPUQuota=450%" not in unit_text
        assert "CPUQuota=350%" not in unit_text
        floating = DEPLOY / f"{unit}.d" / "30-floating-cpu.conf"
        assert floating.exists(), f"{unit} missing floating-cpu drop-in"
        assert "CPUQuota=" in floating.read_text(encoding="utf-8")
