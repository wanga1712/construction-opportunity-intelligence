"""WAVE 2A: HTTP redownload + parse/extract for NEEDED_BUT_LOCAL_MISSING_V2.

Consumes the immutable plan table `needed_local_missing_v2_plan` (never re-derives
membership from DOCUMENT_SELECTION_V3). Processes P0 first, then continues into P1
without pause. Every downloaded document is immediately parsed and its facts are
extracted/persisted through the normal parse-time hook.

HTTP goes through the shared server-wide EIS gate (HttpFileClient +
DownloadCoordinator), so per-request rate limiting is not bypassed.

CRM / medals / commercial queue / lifecycle are never written.

Launch on S13 with the worker venv and the daemon EnvironmentFiles, e.g.:
  /opt/tender_documents_research/.venv/bin/python \
      /opt/CRM_Streamlit/scripts/run_wave2a_http.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/tender_documents_research")
sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402

from document_processor.concurrency_manager import DownloadCoordinator  # noqa: E402
from document_processor.eis_rate_limit_guard import (  # noqa: E402
    EisRateLimitBlocked,
    EisRateLimited,
)
from document_processor.http_client import HttpFileClient, PermanentSourceMiss  # noqa: E402
from document_processor.parse_extractors import extract_and_persist  # noqa: E402
from document_processor.parse_utils import (  # noqa: E402
    get_rich_parser,
    parse_file_with_meta,
    supports_rich_meta,
)
from document_processor.parser_factory import ParserFactory  # noqa: E402
from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402

PLAN_VERSION = "NEEDED_BUT_LOCAL_MISSING_V2"
# WIP ACTIVE_NEED_HTTP_AND_PROMOTION_V1: only commercially-live procurements.
ALLOWED_BUCKETS = ("A_OPEN_CURRENT", "A_AWARDED_OBJECT")
REPORT_PATH = "/tmp/wave2a_report.json"
PROGRESS_PATH = "/tmp/wave2a_progress.json"
MAX_BLOCK_STREAK = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("wave2a")


def di_connect():
    return psycopg2.connect(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ.get("S13_DOCUMENT_DB_PASSWORD", ""),
    )


def load_categories(crm_cur, pids):
    """procurement_id -> list[category_code] from CURRENT opportunities (as in 1B)."""
    out = defaultdict(list)
    ordered = sorted(int(p) for p in pids)
    for start in range(0, len(ordered), 5000):
        chunk = ordered[start:start + 5000]
        crm_cur.execute(
            "SELECT procurement_id, commercial_category_code "
            "  FROM crm_procurement_category_opportunities "
            " WHERE status='CURRENT' AND procurement_id = ANY(%s)",
            (chunk,),
        )
        for pid, cat in crm_cur.fetchall():
            out[int(pid)].append(str(cat))
    return out


def safe_name(file_name, sid, ext):
    """Bound the on-disk name: Content-Disposition can exceed the 255-byte limit."""
    base = (file_name or f"doc_{sid}").replace("\n", " ").replace("\r", " ")
    for ch in ('/', '\\', '\x00'):
        base = base.replace(ch, "_")
    suffix = Path(base).suffix or (("." + ext) if ext else "")
    stem = Path(base).stem[:100].strip() or f"doc_{sid}"
    return f"{stem}{suffix}"


def download_one(client, task_dir, url, suggested):
    """Same ordering the daemon uses: direct first (EIS filestore bypasses proxy)."""
    task_dir.mkdir(parents=True, exist_ok=True)
    max_retries = max(1, int(os.getenv("MAX_DOWNLOAD_RETRIES", "2")))
    delay = float(os.getenv("DOWNLOAD_DELAY_SECONDS", "2.0"))
    for attempt in range(max_retries):
        try:
            path = client.try_download_direct(task_dir, url, suggested)
            if path:
                return path
        except (EisRateLimited, EisRateLimitBlocked, PermanentSourceMiss):
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("direct download attempt %d failed: %s", attempt + 1, exc)
        if attempt < max_retries - 1:
            time.sleep(delay * (attempt + 1))
    if os.getenv("DOCUMENT_PROXY_URL"):
        try:
            return client.try_download_with_proxy(task_dir, url, suggested)
        except (EisRateLimited, EisRateLimitBlocked, PermanentSourceMiss):
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("proxy download failed: %s", exc)
    return None


def write_progress(payload):
    try:
        with open(PROGRESS_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    run_start = time.strftime("%Y-%m-%d %H:%M:%S")
    di = di_connect()
    di.autocommit = False
    crm = psycopg2.connect(**require_crm_db_connect_kwargs())
    storage_root = Path(os.getenv("DOCUMENT_STORAGE_ROOT", "/data/tender-documents"))
    client = HttpFileClient(
        os.getenv("DOCUMENT_PROXY_URL"),
        os.getenv("DOCUMENT_PROXY_MODE", "endpoint"),
        log,
    )
    coord = DownloadCoordinator("tender_monitor")
    client.set_request_gate(coord.request_slot)
    pf = ParserFactory()

    cur = di.cursor()
    cur.execute(
        """SELECT p.id, p.source_document_id, p.procurement_id, p.url, p.priority,
                  p.extension, p.document_class, p.file_size_bytes, p.status, df.file_name,
                  p.lifecycle_bucket
             FROM needed_local_missing_v2_plan p
             LEFT JOIN document_files df ON df.id = p.source_document_id
            WHERE p.plan_version = %s
              AND p.status IN ('PLANNED', 'DOWNLOADED')
              AND p.lifecycle_bucket = ANY(%s)
            ORDER BY CASE p.priority WHEN 'P0' THEN 0 ELSE 1 END, p.id""",
        (PLAN_VERSION, list(ALLOWED_BUCKETS)),
    )
    rows = cur.fetchall()
    log.info("wave2a start: %d plan rows (A-only, P0 first)", len(rows))

    cur.execute(
        """SELECT count(*) FILTER (WHERE lifecycle_bucket NOT IN ('A_OPEN_CURRENT','A_AWARDED_OBJECT')
                                   AND status IN ('PLANNED','DOWNLOADED')) AS b_c,
                  count(DISTINCT procurement_id) FILTER (WHERE lifecycle_bucket = ANY(%s)
                                   AND status IN ('PLANNED','DOWNLOADED')) AS procs
             FROM needed_local_missing_v2_plan WHERE plan_version = %s""",
        (list(ALLOWED_BUCKETS), PLAN_VERSION),
    )
    b_c, active_procs = cur.fetchone()
    log.info("dry-run: RUNNER_ELIGIBLE_DOCS=%d RUNNER_B_DOCS=0 RUNNER_C_DOCS=0 "
             "EXCLUDED_PLANNED_B_OR_C=%d ACTIVE_PROCUREMENTS=%d",
             len(rows), b_c, active_procs or 0)
    if "--dry-run" in sys.argv:
        print(json.dumps({
            "RUNNER_ELIGIBLE_DOCS": len(rows),
            "RUNNER_B_DOCS": 0,
            "RUNNER_C_DOCS": 0,
            "EXCLUDED_PLANNED_B_OR_C": b_c,
            "ACTIVE_PROCUREMENTS": int(active_procs or 0),
        }))
        return 0

    cats = load_categories(crm.cursor(), {r[2] for r in rows if r[2] is not None})
    crm.close()

    counters = Counter()
    facts_by_ext = Counter()
    facts_by_class = Counter()
    procs_processed = set()
    procs_with_facts = set()
    procs_with_quantity = set()
    procs_with_value = set()
    procs_with_confirmed = set()
    block_streak = 0
    processed = 0

    def finalize():
        cur.execute(
            "SELECT count(*) FROM structured_entities WHERE created_at >= %s", (run_start,)
        )
        entities = int(cur.fetchone()[0] or 0)
        cur.execute(
            "SELECT count(*) FROM structured_attributes WHERE created_at >= %s", (run_start,)
        )
        attrs = int(cur.fetchone()[0] or 0)
        report = {
            "plan_version": PLAN_VERSION,
            "buckets": list(ALLOWED_BUCKETS),
            "run_start": run_start,
            "run_end": time.strftime("%Y-%m-%d %H:%M:%S"),
            "counters": dict(counters),
            "facts_by_ext": dict(facts_by_ext),
            "facts_by_doc_class": dict(facts_by_class),
            "entities_created": entities,
            "tech_attributes_created": attrs,
            "TECH_ATTRIBUTE_BINDING_V2_IN_RUNTIME": 1 if attrs else 0,
            "ACTIVE_PROCUREMENTS_TOTAL": int(active_procs or 0),
            "PROCUREMENTS_PROCESSED": len(procs_processed),
            "PROCUREMENTS_WITH_FACTS": len(procs_with_facts),
        }
        with open(REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print("WAVE2A_RESULT " + json.dumps(report, ensure_ascii=False), flush=True)
        log.info("wave2a done: %s", json.dumps(dict(counters), ensure_ascii=False))

    try:
        for (pid_row, sid, pid, url, prio, ext, cls, size, status, file_name, bucket) in rows:
            path = None
            if status == "DOWNLOADED":
                task_dir = storage_root / "wave2a" / str(pid)
                cand = sorted(task_dir.glob("*")) if task_dir.exists() else []
                path = cand[0] if cand else None
            if path is None:
                if not url:
                    cur.execute(
                        "UPDATE needed_local_missing_v2_plan SET status='FAILED',"
                        " error_message='no_url', updated_at=now() WHERE id=%s",
                        (pid_row,),
                    )
                    di.commit()
                    counters[prio + "_DOWNLOAD_FAILED"] += 1
                    counters[bucket + "_DOCS_FAILED"] += 1
                    continue
                task_dir = storage_root / "wave2a" / str(pid)
                counters[prio + "_HTTP_REQUESTED"] += 1
                try:
                    path = download_one(client, task_dir, url, safe_name(file_name, sid, ext))
                except EisRateLimitBlocked as exc:
                    block_streak += 1
                    log.warning("EIS blocked (%d/%d): %s", block_streak, MAX_BLOCK_STREAK, exc)
                    if block_streak >= MAX_BLOCK_STREAK:
                        log.warning("stopping wave2a: EIS block cascade")
                        break
                    time.sleep(300)
                    continue
                except EisRateLimited as exc:
                    log.warning("EIS rate limited, backing off: %s", exc)
                    time.sleep(60)
                    continue
                except PermanentSourceMiss as exc:
                    cur.execute(
                        "UPDATE needed_local_missing_v2_plan SET status='FAILED',"
                        " error_message=%s, updated_at=now() WHERE id=%s",
                        (("PERMANENT_SOURCE_MISS: " + str(exc))[:400], pid_row),
                    )
                    di.commit()
                    counters[prio + "_DOWNLOAD_FAILED"] += 1
                    counters[bucket + "_DOCS_FAILED"] += 1
                    continue
                if not path:
                    cur.execute(
                        "UPDATE needed_local_missing_v2_plan SET status='FAILED',"
                        " error_message='download_failed', updated_at=now() WHERE id=%s",
                        (pid_row,),
                    )
                    di.commit()
                    counters[prio + "_DOWNLOAD_FAILED"] += 1
                    counters[bucket + "_DOCS_FAILED"] += 1
                    continue
                block_streak = 0
                size_b = path.stat().st_size
                counters[prio + "_DOWNLOADED"] += 1
                counters[prio + "_BYTES_DOWNLOADED"] += size_b
                counters[bucket + "_DOCS_DOWNLOADED"] += 1
                cur.execute(
                    """UPDATE document_files
                          SET local_path=%s, local_deleted_at=NULL, download_status='COMPLETED',
                              file_size_bytes=%s, downloaded_at=now(), error_message=NULL
                        WHERE id=%s""",
                    (str(path), size_b, sid),
                )
                cur.execute(
                    """UPDATE needed_local_missing_v2_plan
                          SET status='DOWNLOADED', bytes_downloaded=%s, downloaded_at=now(),
                              updated_at=now() WHERE id=%s""",
                    (size_b, pid_row),
                )
                di.commit()

            parser = get_rich_parser(pf, path) if supports_rich_meta(path) else pf.get_parser(path)
            if parser is None:
                counters[prio + "_UNSUPPORTED"] += 1
            else:
                try:
                    text, meta = parse_file_with_meta(parser, path)
                except Exception as exc:  # noqa: BLE001
                    counters[prio + "_PARSE_FAILED"] += 1
                    log.warning("parse failed %s: %s", path.name, exc)
                    text, meta = None, None
                if text is not None:
                    counters[prio + "_PARSED"] += 1
                    found = 0
                    for cat in (cats.get(pid) or [None]):
                        res = extract_and_persist(
                            path, text, pid, path.name,
                            category_code=cat,
                            source_document_id=sid,
                            physical_key=str(path),
                            line_meta=meta,
                            track="EMBEDDED_MATERIAL",
                        )
                        found += int(res.get("embedded") or 0)
                        if cat is None:
                            found += int(res.get("facts") or 0)
                    if found:
                        counters[prio + "_FACTS_FOUND"] += 1
                        counters[bucket + "_PROCUREMENTS_WITH_FACTS_SEEN"] += 1
                        facts_by_ext[ext or "?"] += found
                        facts_by_class[cls or "OTHER"] += found
                        procs_with_facts.add(pid)
                    else:
                        counters[prio + "_NO_FACTS"] += 1
            cur.execute(
                "UPDATE needed_local_missing_v2_plan SET status='PROCESSED',"
                " processed_at=now(), updated_at=now() WHERE id=%s",
                (pid_row,),
            )
            di.commit()
            counters[bucket + "_DOCS_PROCESSED"] += 1
            procs_processed.add(pid)
            processed += 1
            if processed % 50 == 0:
                write_progress({
                    "processed": processed,
                    "total": len(rows),
                    "counters": dict(counters),
                    "procurements_processed": len(procs_processed),
                    "procurements_with_facts": len(procs_with_facts),
                })
    finally:
        finalize()
        di.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
