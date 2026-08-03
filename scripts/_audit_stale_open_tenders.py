"""Audit open-tab leaks: awarded misclassified or stale tender dates."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from modules.crm.repositories.objects_index_repository import ObjectsIndexRepository  # noqa: E402
from src.services.db_bootstrap import connect_databases  # noqa: E402
from src.services.object_lifecycle import (
    delivery_days_left,
    is_awarded,
    is_lost_for_sales_window,
    tender_days_left,
)
from src.services.objects_mapper import index_row_to_item  # noqa: E402
from src.services.objects_service import _is_procurement_eligible, filter_objects  # noqa: E402


def main() -> int:
    _, tender, crm, _ = connect_databases()
    items = [index_row_to_item(r) for r in ObjectsIndexRepository(crm).load_all()]
    print("today", date.today(), "total", len(items))
    print(
        "awarded", sum(1 for o in items if is_awarded(o)),
        "not_awarded", sum(1 for o in items if not is_awarded(o)),
    )
    print(
        "eligible", sum(1 for o in items if _is_procurement_eligible(o)),
        "lost_window", sum(1 for o in items if is_lost_for_sales_window(o)),
    )

    for seg in (None, "social"):
        for stage in (None, "open", "awarded"):
            n = len(filter_objects(items, segment=seg, award_stage=stage))
            print(f"filter seg={seg or '*'} stage={stage or '*'} -> {n}")

    open_social = filter_objects(items, segment="social", award_stage="open")
    print("\n=== SOCIAL + OPEN ===", len(open_social))
    for item in open_social:
        print(
            f"end={item.end_date} del={item.delivery_end_date} "
            f"tleft={tender_days_left(item)} dleft={delivery_days_left(item)} "
            f"aw={is_awarded(item)} reg={item.registry_type} st={item.status} "
            f"docs={item.doc_matches} | {(item.name or '')[:80]}"
        )

    # Items user likely sees: social segment, in base contour, show as open in UI?
    base = filter_objects(items, segment="social")
    print("\n=== SOCIAL base (any stage split) ===", len(base))
    for item in base[:10]:
        print(
            f"end={item.end_date} del={item.delivery_end_date} "
            f"tleft={tender_days_left(item)} aw={is_awarded(item)} "
            f"reg={item.registry_type} st={item.status} | {(item.name or '')[:70]}"
        )

    if tender:
        stats = tender.execute_query(
            "SELECT status, COUNT(*) AS n FROM document_processing_queue GROUP BY 1 ORDER BY 2 DESC"
        )
        print("\n=== QUEUE STATUS ===")
        for row in stats:
            print(row if isinstance(row, dict) else {"status": row[0], "n": row[1]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
