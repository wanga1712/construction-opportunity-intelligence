"""Initialize CRM tables for multi-profile/product-group search.

Run:
    python scripts/init_profiled_search_schema.py
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


def main() -> int:
    _radar_db, _tender_db, crm_db, warn = connect_databases()
    if warn:
        print(f"DB warning: {warn}")
    if not crm_db or crm_db.is_offline_mode():
        print("CRM DB is not available")
        return 2

    service = ProfiledSearchService(crm_db)
    service.ensure_schema()

    groups = service.product_groups()
    profiles = service.search_profiles()
    profile_groups = service.profile_groups()

    print(f"Product groups: {len(groups)}")
    for group in groups:
        print(f"  - {group.code}: {group.name}")

    print(f"Search profiles: {len(profiles)}")
    for profile in profiles:
        print(f"  - {profile.code}: {profile.name}")

    print(f"Profile/product bindings: {len(profile_groups)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
