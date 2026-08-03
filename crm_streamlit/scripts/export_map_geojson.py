#!/usr/bin/env python3
"""CLI: экспорт GeoJSON для отладки карты (geojson.io)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.services.map_export import MapFilters, fetch_map_objects, rows_to_geojson
from src.services.parking_db import ParkingDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description="Export parking map GeoJSON")
    parser.add_argument("-o", "--output", default="data/map_export.geojson")
    parser.add_argument("--min-floors", type=int, default=0)
    parser.add_argument("--uk-status", default="ALL", choices=["ALL", "DONE", "NO_UK", "HAS_UK"])
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    db = ParkingDatabase()
    if not db.connect():
        print(f"Error: {db.last_error}", file=sys.stderr)
        return 1

    rows = fetch_map_objects(
        db,
        MapFilters(min_floors=args.min_floors, uk_status=args.uk_status, limit=args.limit),
    )
    geojson = rows_to_geojson(rows)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(rows)} features → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
