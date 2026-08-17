"""Fail-closed schema presence checks. No runtime DDL.

Schema changes belong in src/migrations/* or explicit migration scripts only.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple


class SchemaNotReady(RuntimeError):
    """Required CRM relation/column is missing — capability unavailable."""

    def __init__(self, missing: Sequence[str]):
        self.missing = list(missing)
        super().__init__(f"SCHEMA_NOT_READY: {', '.join(self.missing)}")


def _cell(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def relation_exists(db, table_name: str, schema: str = "public") -> bool:
    if not db:
        return False
    try:
        fqn = f"{schema}.{table_name}" if "." not in table_name else table_name
        rows = db.execute_query(f"SELECT to_regclass(%(fqn)s) IS NOT NULL AS ok", {"fqn": fqn})
        if not rows:
            # positional fallback
            rows = db.execute_query("SELECT to_regclass(%s) IS NOT NULL", (fqn,))
        if not rows:
            return False
        return bool(_cell(rows[0]))
    except Exception:
        try:
            rows = db.execute_query(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s LIMIT 1
                """,
                (schema, table_name.split(".")[-1]),
            )
            return bool(rows)
        except Exception:
            return False


def require_relations(
    db,
    tables: Iterable[str],
    *,
    schema: str = "public",
) -> Tuple[bool, List[str]]:
    missing: List[str] = []
    for t in tables:
        name = t.split(".")[-1]
        sch = t.split(".")[0] if "." in t else schema
        if not relation_exists(db, name, schema=sch):
            missing.append(f"{sch}.{name}")
    return (len(missing) == 0, missing)


def require_relations_or_raise(db, tables: Iterable[str], *, schema: str = "public") -> None:
    ok, missing = require_relations(db, tables, schema=schema)
    if not ok:
        raise SchemaNotReady(missing)
