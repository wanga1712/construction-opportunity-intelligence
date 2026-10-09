#!/usr/bin/env python3
"""Bounded document admission for ACTIVE construction projects (PROJECT LIFECYCLE V1).

Dry-run by default. Applies only with --apply, and never in bulk: the batch is
bounded (default 20 active project procurements) per WIP PROJECT_LIFECYCLE_V1 §26.

Admits EMBEDDED_MATERIAL opportunities whose project is still active by
project_end_date and which carry a positive category signal — even when the
procurement is awarded and the submission deadline has expired. Already
downloaded documents are never re-queued (ALREADY_DOWNLOADED).
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]

from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env")

from src.services.commercial_routing_v3.queue_producer import (
    CommercialRoutingV3QueueProducer,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PROJECT_LIFECYCLE_V1 bounded active-project document admission"
    )
    parser.add_argument("--apply", action="store_true", help="Persist queue rows (default dry-run)")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    producer = CommercialRoutingV3QueueProducer(enabled=True)
    result = producer.populate_active_project_documents(
        batch_size=args.batch_size,
        dry_run=not args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
