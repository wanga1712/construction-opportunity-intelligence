#!/usr/bin/env python3
"""Fail if tracked Git content looks like secrets or local denylist literals.

Banned production hosts are not hardcoded here. Copy
tools/repo_hygiene_denylist.example to .hygiene/denylist.txt and add local
literals. Generic patterns always run.

Prints paths and rule names only — never matched secret values.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENYLIST_CANDIDATES = (
    Path(os.environ["REPO_HYGIENE_DENYLIST"])
    if os.environ.get("REPO_HYGIENE_DENYLIST")
    else None,
    ROOT / ".hygiene" / "denylist.txt",
)
GENERIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private_key_block", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
    ("wireguard_private_key", re.compile(r"(?m)^PrivateKey\s*=")),
    (
        "password_or_token_assignment",
        re.compile(
            r"(?i)(?:password|passwd|api_token|secret_key|access_token)\s*=\s*"
            r"['\"]([^'\"$\r\n<{]{8,})['\"]"
        ),
    ),
    (
        "postgres_uri_with_password",
        re.compile(r"postgres(?:ql)?://[^:\s/]+:[^@\s/]+@"),
    ),
]
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".ovpn"}
SECRET_NAMES = {
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "wg0.conf",
    "credentials.json",
    "db_credintials.env",
}


def git_tracked_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        text=True,
        errors="replace",
    )
    others = subprocess.check_output(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        errors="replace",
    )
    items = [item.replace("\\", "/") for item in out.split("\0") if item]
    items.extend(item.replace("\\", "/") for item in others.split("\0") if item)
    return items


def load_denylist() -> tuple[list[str], str]:
    for candidate in DENYLIST_CANDIDATES:
        if candidate is None:
            continue
        if candidate.is_file():
            lines = []
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    lines.append(line)
            return lines, str(candidate)
    return [], ""


def is_secret_path(rel: str) -> str | None:
    name = Path(rel).name
    lower = name.lower()
    if lower in SECRET_NAMES:
        return "tracked_secret_filename"
    suffix = Path(rel).suffix.lower()
    if suffix in SECRET_SUFFIXES and not lower.endswith(".pub"):
        return "tracked_key_or_cert"
    if name == ".env":
        return "tracked_env_file"
    if lower.endswith(".env") and not (
        lower.endswith(".env.example") or lower.endswith(".env.template")
    ):
        return "tracked_env_file"
    return None


def main() -> int:
    denylist, denylist_source = load_denylist()
    findings: list[str] = []
    for rel in git_tracked_files():
        path_rule = is_secret_path(rel)
        if path_rule:
            findings.append(f"{rel}  [{path_rule}]")
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for rule_name, pattern in GENERIC_RULES:
            if pattern.search(text):
                findings.append(f"{rel}  [{rule_name}]")
        for needle in denylist:
            if needle and needle in text:
                findings.append(f"{rel}  [denylist]")
                break
    print(f"DENYLIST_LOADED={'YES' if denylist else 'NO'}")
    if denylist_source:
        print(f"DENYLIST_SOURCE={Path(denylist_source).name}")
    print(f"FINDING_COUNT={len(findings)}")
    for line in findings:
        print(line)
    if findings:
        print("REPO_HYGIENE_CHECK=FAIL")
        return 1
    print("REPO_HYGIENE_CHECK=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
