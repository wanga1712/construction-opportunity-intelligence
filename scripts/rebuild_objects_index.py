"""Плановая пересборка crm_objects_index для быстрого CRM UI."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from src.services.db_bootstrap import connect_databases  # noqa: E402
from src.services.objects_index_manager import build_objects_index  # noqa: E402


def main() -> int:
    radar_db, tender_db, crm_db, warn = connect_databases()
    if warn:
        print(f"[index] db warning: {warn}")
    ok, message, meta = build_objects_index(crm_db, radar_db, tender_db)
    print(f"[index] {message}")
    if meta:
        print(f"[index] meta: {meta}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
