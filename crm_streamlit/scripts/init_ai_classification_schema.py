"""One-time initializer for crm_object_ai_classifications schema."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from src.services.db_bootstrap import connect_databases  # noqa: E402
from src.services.object_ai_classification_store import ensure_schema  # noqa: E402


def main() -> int:
    _radar_db, _tender_db, crm_db, warn = connect_databases()
    if not crm_db:
        print(f"CRM DB unavailable: {warn}")
        return 2
    ok = ensure_schema(crm_db)
    print("ensure_schema:", "ok" if ok else "failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

