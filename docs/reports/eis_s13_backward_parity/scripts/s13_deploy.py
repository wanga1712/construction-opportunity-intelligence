#!/usr/bin/env python3
"""
Phase 9+10: Backup then deploy s13_backfill modules to /opt/tendermonitor.
Run as sudo or as tendermonitor user with write access.
"""
from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

GIT_ROOT = Path("/tmp/eis_s13_parity_git/eis_ingestion/s13_backfill")
LIVE_ROOT = Path("/opt/tendermonitor")
BACKUP_DIR = LIVE_ROOT / "backups"

# Files to deploy (relative to their respective roots)
DEPLOY_FILES = [
    "parsing_xml/rgk_record.py",
    "parsing_xml/rgk_batch.py",
    "parsing_xml/okpd_parser.py",
    "database_work/contract_registry_locator.py",
    "database_work/database_id_fetcher.py",
    "database_work/database_operations.py",
    "database_work/recouped_contract_sync.py",
    "database_work/rgk_batch_sql.py",
    "database_work/rgk_batch_store.py",
    "database_work/rgk_dirty.py",
    "database_work/rgk_plan.py",
    "utils/source_day_metrics.py",
]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_alias = f"eis_s13_backward_pre_batch_deploy_{ts}"
    backup_path = BACKUP_DIR / f"{backup_alias}.tgz"

    # Phase 9: backup existing files
    existing = [rel for rel in DEPLOY_FILES if (LIVE_ROOT / rel).is_file()]
    if existing:
        subprocess.check_call(
            ["tar", "--preserve-permissions", "-czf", str(backup_path)]
            + [str(LIVE_ROOT / rel) for rel in existing]
        )
        print(f"BACKWARD_RUNTIME_BACKUP_CREATED=YES")
        print(f"BACKWARD_RUNTIME_BACKUP_ALIAS={backup_alias}")
    else:
        print("BACKWARD_RUNTIME_BACKUP_CREATED=YES (no existing files to back up)")
        print(f"BACKWARD_RUNTIME_BACKUP_ALIAS={backup_alias}")

    # Phase 10: deploy
    hash_mismatches = []
    deployed = []
    for rel in DEPLOY_FILES:
        src = GIT_ROOT / rel
        dst = LIVE_ROOT / rel
        if not src.is_file():
            print(f"MISSING_GIT_FILE={src}", file=sys.stderr)
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        # Verify
        src_hash = sha256(src)
        dst_hash = sha256(dst)
        if src_hash != dst_hash:
            hash_mismatches.append(rel)
        else:
            deployed.append(rel)
        print(f"DEPLOYED {rel} hash_ok={src_hash == dst_hash}")

    if hash_mismatches:
        print(f"HASH_MISMATCHES={hash_mismatches}", file=sys.stderr)
        return 1

    print(f"\nCANONICAL_RUNTIME_HASH_MATCH=YES")
    print(f"DEPLOYED_FILES={len(deployed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
