"""Sync актуальные профили мультипоиска CRM.

Run:
    python scripts/sync_search_profiles_20260723.py
"""
from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.bootstrap import setup_source_path

setup_source_path()

from src.services.db_bootstrap import connect_databases
from src.services.profiled_search import ProfiledSearchService


SQL_PATH = PROJECT_ROOT / "docs" / "DB_PROFILED_SEARCH_PROFILES_20260723.sql"


def main() -> int:
    _radar_db, _tender_db, crm_db, warn = connect_databases()
    if warn:
        print(f"DB warning: {warn}")
    if not crm_db or crm_db.is_offline_mode():
        print("CRM DB is not available")
        return 2

    service = ProfiledSearchService(crm_db)
    service.ensure_schema()
    crm_db.execute_update(SQL_PATH.read_text(encoding="utf-8"))

    groups = service.product_groups()
    profiles = service.search_profiles()
    bindings = service.profile_groups()

    print(f"Product groups: {len(groups)}")
    for group in groups:
        print(f"  - {group.code}: {group.name}")

    print(f"Search profiles: {len(profiles)}")
    for profile in profiles:
        print(f"  - {profile.code}: {profile.name}")

    print(f"Profile/product bindings: {len(bindings)}")
    for binding in bindings:
        print(
            "  - "
            f"{binding['search_profile_code']} -> {binding['product_group_code']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
