"""Resource policy contract for CRM interactive headroom."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "systemd"


def test_background_slice_excludes_interactive_cpus() -> None:
    text = (DEPLOY / "crm-background-compute.slice").read_text(encoding="utf-8")
    assert "AllowedCPUs=2-7" in text
    assert "CPUQuota=600%" in text
    assert "WEIGHT_ONLY" not in text


def test_crm_hard_interactive_dropin() -> None:
    text = (
        DEPLOY / "crm-streamlit.service.d" / "20-hard-interactive.conf"
    ).read_text(encoding="utf-8")
    assert "MemorySwapMax=0" in text
    assert "MemoryMin=384M" in text
    assert "MemoryLow=768M" in text
    assert "CPUWeight=800" in text


def test_ollama_and_ai_runner_use_background_slice() -> None:
    ollama = (
        DEPLOY / "ollama.service.d" / "20-background-slice.conf"
    ).read_text(encoding="utf-8")
    ai = (
        DEPLOY / "crm-ai-assessment-runner.service.d" / "20-background-slice.conf"
    ).read_text(encoding="utf-8")
    assert "Slice=crm-background-compute.slice" in ollama
    assert "Slice=crm-background-compute.slice" in ai


def test_one_off_compute_wrapper_uses_slice() -> None:
    script = (ROOT / "scripts" / "run_background_compute.sh").read_text(encoding="utf-8")
    assert "systemd-run" in script
    assert "crm-background-compute.slice" in script


def test_light_nav_invariants_still_present() -> None:
    from src.ui.page_deps import requires_companies_load_sync, requires_companies_service

    assert requires_companies_service("system_health") is False
    assert requires_companies_load_sync("system_health") is False
