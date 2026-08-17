"""Fail-closed CRM DB config and no hardcoded password literals in tracked source."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from src.services.crm_db_runtime import CrmDbConfigError, require_crm_db_connect_kwargs

def _git_root(start: Path) -> Path:
    for path in [start, *start.parents]:
        if (path / ".git").exists():
            return path
    raise RuntimeError("git root not found")


ROOT = _git_root(Path(__file__).resolve())

FALLBACK_PASSWORD_GET = re.compile(
    r"""os\.environ\.get\(\s*['\"][A-Z0-9_]*PASSWORD[A-Z0-9_]*['\"]\s*,\s*['\"]([^'\"]+)['\"]"""
)
HARDCODED_PASSWORD_KW = re.compile(
    r"""password\s*=\s*['\"]([^'\"]+)['\"]"""
)
PLACEHOLDER = re.compile(
    r"^(\$\{[A-Z0-9_]+\}$|<YOUR_[A-Z0-9_]+>|CHANGE_ME|changeme|your_password|<.*>|pass|password|)$",
    re.I,
)


def test_missing_crm_db_password_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("CRM_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("CRM_DB_PORT", "5432")
    monkeypatch.setenv("CRM_DB_DATABASE", "crm")
    monkeypatch.setenv("CRM_DB_USER", "crm_app")
    monkeypatch.delenv("CRM_DB_PASSWORD", raising=False)
    with pytest.raises(CrmDbConfigError, match="CRM_DB_PASSWORD"):
        require_crm_db_connect_kwargs()


def test_missing_host_does_not_fall_back(monkeypatch) -> None:
    monkeypatch.delenv("CRM_DB_HOST", raising=False)
    monkeypatch.setenv("CRM_DB_PORT", "5432")
    monkeypatch.setenv("CRM_DB_DATABASE", "crm")
    monkeypatch.setenv("CRM_DB_USER", "crm_app")
    monkeypatch.setenv("CRM_DB_PASSWORD", "from-env-only")
    with pytest.raises(CrmDbConfigError, match="CRM_DB_HOST"):
        require_crm_db_connect_kwargs()


def test_complete_env_returns_kwargs(monkeypatch) -> None:
    monkeypatch.setenv("CRM_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("CRM_DB_PORT", "5432")
    monkeypatch.setenv("CRM_DB_DATABASE", "crm")
    monkeypatch.setenv("CRM_DB_USER", "crm_app")
    monkeypatch.setenv("CRM_DB_PASSWORD", "from-env-only")
    kwargs = require_crm_db_connect_kwargs()
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["user"] == "crm_app"
    assert kwargs["dbname"] == "crm"
    assert kwargs["port"] == 5432
    assert "from-env-only" == kwargs["password"]


def _tracked_text_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    files = []
    for rel in out.splitlines():
        if rel.endswith((".py", ".sh", ".md", ".yml", ".yaml", ".env", ".template", ".json")):
            files.append(rel)
    return files


def test_tracked_tree_has_no_real_password_literals() -> None:
    findings = []
    for rel in _tracked_text_files():
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for match in FALLBACK_PASSWORD_GET.finditer(line):
                value = match.group(1)
                if not PLACEHOLDER.match(value):
                    findings.append(f"{rel}:{i}:env_get_password_fallback")
            for match in HARDCODED_PASSWORD_KW.finditer(line):
                value = match.group(1)
                if not PLACEHOLDER.match(value) and "${" not in value:
                    findings.append(f"{rel}:{i}:hardcoded_password_kwarg")
    assert findings == [], "plaintext credential literals remain:\n" + "\n".join(findings)
