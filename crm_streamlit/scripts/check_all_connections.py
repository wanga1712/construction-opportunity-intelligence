"""Full connectivity check: HTTP + Radar + Tender + CRM + queue sample."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

import urllib.error
import urllib.request

from src.services.db_bootstrap import connect_databases  # noqa: E402


def check_http(url: str, *, timeout: float = 10.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            return 200 <= code < 400, f"HTTP {code} {url}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} {url}"
    except Exception as exc:
        return False, f"FAIL {url}: {exc}"


def _ok(db) -> bool:
    return bool(db and not db.is_offline_mode())


def main() -> int:
    ok_http, msg_http = check_http("http://127.0.0.1:8504/")
    print(msg_http)

    radar, tender, crm, warn = connect_databases()
    print(f"Radar: {'OK' if _ok(radar) else 'FAIL'}")
    print(f"Tender: {'OK' if _ok(tender) else 'FAIL'}")
    print(f"CRM: {'OK' if _ok(crm) else 'FAIL'}")
    if warn:
        print(f"Warn: {warn}")

    if _ok(tender):
        rows = tender.execute_query(
            "SELECT status, COUNT(*) AS n FROM document_processing_queue GROUP BY 1 ORDER BY 2 DESC LIMIT 6"
        )
        print("Queue:", [(r.get("status") if isinstance(r, dict) else r[0], r.get("n") if isinstance(r, dict) else r[1]) for r in (rows or [])])

    if _ok(crm):
        rows = crm.execute_query("SELECT COUNT(*) AS n FROM crm_objects_index")
        n = rows[0].get("n") if rows and isinstance(rows[0], dict) else (rows[0][0] if rows else 0)
        print(f"crm_objects_index: {n} rows")

    all_ok = ok_http and _ok(radar) and _ok(tender) and _ok(crm)
    print("RESULT:", "ALL_OK" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
