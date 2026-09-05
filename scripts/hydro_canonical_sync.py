"""Operator entrypoint: source JSONL stdin/file -> canonical CRM."""
from __future__ import annotations
import argparse, json
from src.infrastructure.crm_connection import connect_crm
from src.services.hydro.models import source_row_to_object
from src.services.hydro.persistence_repository import HydroPersistenceRepository

class _RollbackConnection:
    def __init__(self, connection): self._connection = connection
    def __getattr__(self, name): return getattr(self._connection, name)
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): self._connection.rollback(); return False

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("input"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--limit", type=int); p.add_argument("--rollback", action="store_true"); p.add_argument("--commit", action="store_true")
    args = p.parse_args(); rows = [json.loads(x) for x in open(args.input, encoding="utf-8") if x.strip()]; rows = rows[:args.limit] if args.limit else rows
    objects = [source_row_to_object(row) for row in rows]; conn = connect_crm()
    try:
        if args.rollback: conn = _RollbackConnection(conn)
        result = HydroPersistenceRepository(conn).sync(objects, dry_run=args.dry_run or not args.commit)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
    finally: conn.close()
if __name__ == "__main__": raise SystemExit(main())
