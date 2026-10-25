#!/usr/bin/env python3
"""DIRECT_SUPPLY DEFERRED_ARCHIVE: extract archive members and persist strict facts."""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import psycopg2

CRM_ROOT = "/opt/CRM_Streamlit"
for path in (CRM_ROOT, "/opt/tender_documents_research", "/opt/CRM_Streamlit/scripts"):
    if path not in sys.path:
        sys.path.insert(0, path)

from direct_supply_phase2 import download, inventory  # noqa: E402
from document_processor.archive_extractor import ArchiveExtractor  # noqa: E402
from document_processor.direct_runtime import direct_facts  # noqa: E402
from document_processor.direct_template_registry import (  # noqa: E402
    normalize_file_format,
    resolve_direct_template,
)
from document_processor.embedded_persistence import persist_facts  # noqa: E402


def _di_conn():
    return psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def _persist_member(row: dict, member_path: Path) -> tuple[int, int]:
    fmt = normalize_file_format(member_path.suffix)
    template = resolve_direct_template(
        category_code=row["category"],
        opportunity_track="DIRECT_SUPPLY",
        document_class=row["document_class"],
        file_format=fmt,
    )
    if template is None:
        return 0, 0
    facts = direct_facts(
        member_path,
        procurement_id=row["procurement_id"],
        category_code=row["category"],
        document_name=member_path.name,
        source_document_id=row.get("document_file_id"),
        physical_key=row.get("physical_key"),
        document_class=row["document_class"],
    )
    facts = [f for f in facts if f.quantity_value is not None and f.unit_normalized]
    if not facts:
        return 0, 0
    snapshot = "\n".join(str(getattr(f, "source_quote", "") or "") for f in facts)
    conn = _di_conn()
    try:
        created, reused, _ = persist_facts(
            conn,
            procurement_id=row["procurement_id"],
            document_name=member_path.name,
            category_code=row["category"],
            facts=facts,
            source_text=snapshot,
            source_document_id=row.get("document_file_id"),
        )
        conn.commit()
        return int(created or 0), int(reused or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    items = [r for r in inventory(include_all=True)
             if r.get("classification") == "DEFERRED_ARCHIVE"]
    missing = [r for r in items if not Path(str(r.get("local_path") or "")).is_file()]
    if missing:
        print(f"DOWNLOAD_MISSING_ARCHIVES={len(missing)}")
        download(missing, apply=True)
    items = [r for r in inventory(include_all=True)
             if r.get("classification") == "DEFERRED_ARCHIVE"]

    logger = logging.getLogger("archive_persist")
    extractor = ArchiveExtractor(logger)
    created_total = reused_total = 0
    processed = []
    for row in items:
        archive_path = Path(str(row.get("local_path") or ""))
        if not archive_path.is_file():
            processed.append({**row, "result": "ARCHIVE_MISSING"})
            continue
        with tempfile.TemporaryDirectory(prefix="direct_archive_") as tmp:
            members = extractor.extract_recursive(archive_path, Path(tmp))
            if not members:
                processed.append({**row, "result": "NO_MEMBERS"})
                continue
            member_report = []
            for member in members:
                try:
                    created, reused = _persist_member(row, member)
                except Exception as exc:
                    member_report.append({
                        "member": str(member),
                        "result": f"ERROR:{type(exc).__name__}:{exc}",
                    })
                    continue
                created_total += created
                reused_total += reused
                member_report.append({
                    "member": str(member),
                    "created": created,
                    "reused": reused,
                })
            processed.append({
                "procurement_id": row["procurement_id"],
                "document_file_id": row.get("document_file_id"),
                "category": row["category"],
                "archive": archive_path.name,
                "members": member_report,
            })
    print(f"ARCHIVES={len(items)} CREATED={created_total} REUSED={reused_total}")
    print(processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
