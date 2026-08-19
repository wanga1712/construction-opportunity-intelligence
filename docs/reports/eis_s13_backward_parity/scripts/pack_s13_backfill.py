#!/usr/bin/env python3
"""Create a local s13_backfill tarball for isolated replay. No secrets."""
from __future__ import annotations

import os
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "eis_ingestion" / "s13_backfill"
OUT = Path(os.environ.get("TEMP", "/tmp")) / "s13_backfill.tgz"
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".env"}


def keep(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    if path.suffix in SKIP_SUFFIX or path.name.endswith(".env"):
        return False
    return True


def main() -> int:
    if not SRC.is_dir():
        raise SystemExit("missing eis_ingestion/s13_backfill")
    with tarfile.open(OUT, "w:gz") as tar:
        for path in SRC.rglob("*"):
            if path.is_file() and keep(path):
                tar.add(path, arcname=str(Path("s13_backfill") / path.relative_to(SRC)))
    print("S13_BACKFILL_TGZ=" + str(OUT))
    print("S13_BACKFILL_BYTES=" + str(OUT.stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
