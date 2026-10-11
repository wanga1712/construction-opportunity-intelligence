#!/usr/bin/env python3
"""Classify local-artifact failures (no HTTP) and record extraction outcomes.

For each FAILED queue row whose selected document has a local artifact:
  parse -> hook (DIRECT/EMBEDDED by track) -> outcome
    FACTS_FOUND | NO_FACTS | CORRUPT | UNSUPPORTED | PARSE_FAILED
A technical failure is never silently turned into NO_FACTS.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

DOC_RUNTIME = os.getenv("DOC_RUNTIME_PATH", "/opt/tender_documents_research")
RUNTIME = Path(DOC_RUNTIME) if Path(DOC_RUNTIME).exists() else ROOT / "tender_documents_research"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from document_processor.embedded_persistence import record_outcome  # noqa: E402
from document_processor.parse_extractors import extract_and_persist  # noqa: E402
from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta  # noqa: E402
from document_processor.parser_factory import ParserFactory  # noqa: E402

LANE = os.getenv("CLASSIFY_LANE", "queue_v2_tier1")
DIRECT_CATS = {"computers", "lighting", "cable_support_systems"}
_ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z", ".001", ".002", ".003", ".004", ".007")
_MAGIC = {
    ".pdf": (b"%PDF",), ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".xlsx": (b"PK\x03\x04",), ".xlsm": (b"PK\x03\x04",), ".odt": (b"PK\x03\x04",),
    ".zip": (b"PK\x03\x04",), ".rar": (b"Rar!",), ".7z": (b"7z\xbc\xaf",),
    ".doc": (b"\xd0\xcf\x11\xe0",), ".xls": (b"\xd0\xcf\x11\xe0",),
}


def di_dsn() -> Dict[str, Any]:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def magic_ok(path: Path) -> bool:
    expected = _MAGIC.get(path.suffix.lower())
    if not expected:
        return True
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
        return any(head.startswith(sig) for sig in expected)
    except Exception:
        return False


def main() -> int:
    di = psycopg2.connect(**di_dsn())
    try:
        rows = query(
            di,
            "SELECT id, procurement_id, status, selected_documents, last_error"
            " FROM document_processing_queue WHERE queue_lane=%s AND status='FAILED' ORDER BY id",
            (LANE,),
        )
        factory = ParserFactory()
        counts: Dict[str, int] = {}
        for row in rows:
            qid, pid = int(row["id"]), int(row["procurement_id"])
            verdicts = []
            for entry in row.get("selected_documents") or []:
                sid = entry.get("source_document_id")
                cat = entry.get("category")
                track = "DIRECT" if cat in DIRECT_CATS else "EMBEDDED"
                doc = query(di, "SELECT file_name, local_path, local_deleted_at FROM document_files WHERE id=%s", (sid,))
                d = doc[0] if doc else None
                if not d or not d.get("local_path") or d.get("local_deleted_at") is not None:
                    verdicts.append((sid, "ARTIFACT_MISSING"))
                    continue
                p = Path(d["local_path"])
                if not p.exists():
                    verdicts.append((sid, "ARTIFACT_MISSING"))
                    continue
                if not magic_ok(p):
                    record_outcome(di, source_document_id=sid, procurement_id=pid,
                                   category_code=cat, track=track, document_name=d["file_name"],
                                   outcome="CORRUPT", reason="magic_bytes_mismatch")
                    verdicts.append((sid, "CORRUPT"))
                    continue
                # An archive is a container: its children are parsed during the
                # download task; the container itself is not a fact source.
                if p.name.lower().endswith(_ARCHIVE_SUFFIXES):
                    record_outcome(di, source_document_id=sid, procurement_id=pid,
                                   category_code=cat, track=track, document_name=d["file_name"],
                                   outcome="ARCHIVE_CONTAINER",
                                   reason="children_parsed_in_task; container yields no row facts")
                    verdicts.append((sid, "ARCHIVE_CONTAINER"))
                    continue
                parser = get_rich_parser(factory, p) if supports_rich_meta(p) else factory.get_parser(p)
                if parser is None:
                    record_outcome(di, source_document_id=sid, procurement_id=pid,
                                   category_code=cat, track=track, document_name=d["file_name"],
                                   outcome="UNSUPPORTED", reason=f"no_parser:{p.suffix}")
                    verdicts.append((sid, "UNSUPPORTED"))
                    continue
                try:
                    text, line_meta = ("", None)
                    if p.suffix.lower() not in {".xlsx", ".xlsm"}:
                        text, line_meta = parse_file_with_meta(parser, p)
                except Exception as exc:
                    record_outcome(di, source_document_id=sid, procurement_id=pid,
                                   category_code=cat, track=track, document_name=d["file_name"],
                                   outcome="PARSE_FAILED", reason=str(exc)[:200])
                    verdicts.append((sid, "PARSE_FAILED"))
                    continue
                try:
                    res = extract_and_persist(
                        p, text, pid, p.name, category_code=cat, source_document_id=sid,
                        physical_key=entry.get("physical_key"), track=track,
                        line_meta=line_meta,
                    )
                except Exception as exc:
                    record_outcome(di, source_document_id=sid, procurement_id=pid,
                                   category_code=cat, track=track, document_name=d["file_name"],
                                   outcome="PIPELINE_ERROR", reason=str(exc)[:200])
                    verdicts.append((sid, "PIPELINE_ERROR"))
                    continue
                created = int(res.get("embedded") or 0)
                outcome = "FACTS_FOUND" if created else "NO_FACTS"
                if created == 0:
                    record_outcome(di, source_document_id=sid, procurement_id=pid,
                                   category_code=cat, track=track, document_name=d["file_name"],
                                   outcome="NO_FACTS", reason="local_reprocess_no_table_facts")
                verdicts.append((sid, outcome))
                counts[outcome] = counts.get(outcome, 0) + 1
            summary = ",".join(f"{s}:{v}" for s, v in verdicts) or "NO_SELECTED_DOCS"
            with di.cursor() as cur:
                cur.execute(
                    "UPDATE document_processing_queue SET last_error=%s WHERE id=%s",
                    (f"LOCAL_CLASSIFIED:{summary}"[:400], qid),
                )
            di.commit()
            print(f"QUEUE {qid} pid={pid} -> {summary}")
        print(f"CLASSIFIED_ROWS={len(rows)}")
        print(f"VERDICTS={counts}")
        return 0
    finally:
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
