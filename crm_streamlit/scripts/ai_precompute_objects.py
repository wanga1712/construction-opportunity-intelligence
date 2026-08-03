"""Background AI pre-computation for CRM object cards.

This script is intentionally conservative: it runs one instance at a time,
processes a small batch, writes append-only JSONL labels/scores, and exits.
Run it from Task Scheduler every 10-30 minutes while the desktop worker is on.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from src.services.db_bootstrap import connect_databases  # noqa: E402
from src.services.object_ai_classifier import classify_item_with_ai  # noqa: E402
from src.services.object_ai_classification_store import load_ai_classifications, save_ai_classification  # noqa: E402
from src.services.object_ai_prompts import MODEL_VERSION  # noqa: E402
from src.services.object_ai_scores import load_object_ai_scores, save_object_ai_score  # noqa: E402
from src.services.object_category_labels import (  # noqa: E402
    apply_object_category_labels,
    load_category_labels,
    object_label_keys,
    save_category_label,
)
from src.services.object_lifecycle import is_awarded, is_lost_for_sales_window  # noqa: E402
from src.services.objects_service import ObjectsService, filter_objects  # noqa: E402


DATA_DIR = ROOT / "data" / "ai_shadow"
LOCK_PATH = DATA_DIR / "ai_precompute.lock"
LOG_PATH = DATA_DIR / "ai_precompute.log"
_MODEL_VERSION = MODEL_VERSION


def _log(message: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _acquire_lock(max_age_sec: int = 7200) -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            row = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            age = time.time() - float(row.get("started_at") or 0)
            if age < max_age_sec:
                _log(f"skip: another worker is running, age={age:.0f}s")
                return False
        except Exception:
            pass
    LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "started_at": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


def _release_lock() -> None:
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except Exception:
        pass


def _has_row(item, rows: dict) -> bool:
    return any(key in rows for key in object_label_keys(item))


def _has_current_ai_row(item, rows: dict) -> bool:
    row = next((rows.get(key) for key in object_label_keys(item) if rows.get(key)), None)
    return bool(row and row.get("model_version") == _MODEL_VERSION)


def _candidate_score(item, labels: dict, scores: dict) -> int:
    score = 0
    if not is_awarded(item):
        score += 80
    if item.doc_matches or item.matched_files:
        score += 60
    if not _has_row(item, labels):
        score += 40
    if not _has_row(item, scores):
        score += 30
    if item.end_date:
        score += 10
    score += min(int(item.doc_matches or 0), 20)
    score += min(int(item.info_score or 0), 20)
    return score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--overwrite-user", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not _acquire_lock():
        return 0

    started = time.time()
    try:
        _log(f"start limit={args.limit} max_seconds={args.max_seconds}")
        _, tender_db, crm_db, _ = connect_databases()
        svc = ObjectsService(tender_db=tender_db, crm_db=crm_db)
        if not svc.load_sync(force=True):
            _log(f"load failed: {svc.last_error}")
            return 2

        labels = load_category_labels()
        scores = load_object_ai_scores()
        db_ai = load_ai_classifications(crm_db)
        user_keys = {
            key for key, row in labels.items()
            if row.get("source") == "user"
        }
        items = filter_objects(svc.all_objects())
        candidates = []
        for item in items:
            if is_lost_for_sales_window(item):
                continue
            keys = object_label_keys(item)
            if any(key in user_keys for key in keys) and not args.overwrite_user:
                continue
            needs = args.overwrite_user or not (
                _has_row(item, labels)
                and _has_row(item, scores)
                and _has_current_ai_row(item, db_ai)
                and int(item.ai_priority_score or 0) > 0
            )
            if needs:
                candidates.append(item)
        candidates.sort(key=lambda item: _candidate_score(item, labels, scores), reverse=True)
        candidates = candidates[: max(0, args.limit)]
        _log(f"selected={len(candidates)} model={_MODEL_VERSION}")

        ok = failed = changed = 0
        for idx, item in enumerate(candidates, 1):
            if time.time() - started > args.max_seconds:
                _log("stop: max_seconds reached")
                break
            before = item.segment
            try:
                result = classify_item_with_ai(item)
                if not args.dry_run:
                    save_category_label(item, result["label"], source="ai_background")
                    save_object_ai_score(item, result, source="ai_background")
                    save_ai_classification(item, result, source="ai_background", crm_db=crm_db)
                    apply_object_category_labels([item])
                changed += int(item.segment != before)
                ok += 1
                _log(
                    f"ok {idx}/{len(candidates)} num={item.contract_number or '-'} "
                    f"segment={result.get('segment')} priority={result.get('priority_score')}"
                )
            except Exception as exc:
                failed += 1
                _log(f"fail {idx}/{len(candidates)} num={item.contract_number or '-'}: {exc}")

        _log(f"done ok={ok} changed={changed} failed={failed}")
        return 0 if failed == 0 else 1
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
