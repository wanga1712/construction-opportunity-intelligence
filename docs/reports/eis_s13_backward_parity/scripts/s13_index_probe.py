#!/usr/bin/env python3
"""Probe S13->S7 filename index. Prints aliases and timings only."""
from __future__ import annotations

from pathlib import Path

import psycopg2


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def walk_index(node: dict) -> tuple[bool, str]:
    used = False
    names: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        index_name = str(current.get("Index Name") or "")
        node_type = str(current.get("Node Type") or "")
        if index_name:
            names.append(index_name)
        if index_name == "idx_file_names_xml_file_name" or (
            "Index" in node_type and "file_name" in index_name
        ):
            used = True
        stack.extend(current.get("Plans") or [])
    return used, ",".join(names) if names else node.get("Node Type", "")


def main() -> int:
    env = load_env(Path("/opt/tendermonitor/database_work/db_credintials.env"))
    host = env["DB_HOST_TENDER"]
    local = host in {"127.0.0.1", "localhost", "::1"}
    print("BACKWARD_DB_HOST_ALIAS=" + ("S13_LOCAL_UNEXPECTED" if local else "S7"))
    print("BACKWARD_DB_NAME=" + env["DB_DATABASE_TENDER"])
    print("BACKWARD_DB_ROLE=" + env["DB_USER_TENDER"])
    conn = psycopg2.connect(
        host=host,
        port=env.get("DB_PORT_TENDER", "5432"),
        dbname=env["DB_DATABASE_TENDER"],
        user=env["DB_USER_TENDER"],
        password=env["DB_PASSWORD_TENDER"],
        connect_timeout=10,
    )
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    db = cur.fetchone()[0]
    print("S13_TO_S7_DB_CONNECTION=" + ("PASS" if (not local and db == "tender_monitor") else "FAIL"))
    cur.execute(
        "SELECT 1 FROM pg_indexes "
        "WHERE tablename='file_names_xml' AND indexname='idx_file_names_xml_file_name'"
    )
    present = cur.fetchone() is not None
    print("FILE_NAME_INDEX_PRESENT=" + ("YES" if present else "NO"))
    cur.execute("SELECT file_name FROM file_names_xml ORDER BY id DESC LIMIT 500")
    names = [row[0] for row in cur.fetchall()]
    print("EXPLAIN_BATCH_SIZE=" + str(len(names)))
    cur.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        "SELECT file_name FROM file_names_xml WHERE file_name = ANY(%s)",
        (names,),
    )
    plan = cur.fetchone()[0]
    root = plan[0] if isinstance(plan, list) else plan
    used, index_names = walk_index(root["Plan"])
    print("FILE_NAME_INDEX_USED=" + ("YES" if used else "NO"))
    print("EXPLAIN_INDEX_NAME=" + index_names)
    print("BACKWARD_FILENAME_LOOKUP_MS=" + str(root.get("Execution Time")))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
