from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from database_work.database_connection import DatabaseManager


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "database_work" / "db_credintials.env")


def make_db() -> DatabaseManager:
    return DatabaseManager(
        {
            "tender_monitor": {
                "host": os.getenv("DB_HOST_TENDER"),
                "name": os.getenv("DB_DATABASE_TENDER"),
                "user": os.getenv("DB_USER_TENDER"),
                "password": os.getenv("DB_PASSWORD_TENDER"),
                "port": os.getenv("DB_PORT_TENDER"),
            },
            "product_catalog_2": {
                "host": os.getenv("DB_HOST_CATALOG"),
                "name": os.getenv("DB_DATABASE_CATALOG"),
                "user": os.getenv("DB_USER_CATALOG"),
                "password": os.getenv("DB_PASSWORD_CATALOG"),
                "port": os.getenv("DB_PORT_CATALOG"),
            },
        }
    )


def print_tables(db: DatabaseManager, db_name: str) -> None:
    print(f"\n--- DB {db_name}")
    rows = db.execute_query(
        db_name,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (
            table_name ILIKE '%user%'
            OR table_name ILIKE '%keyword%'
            OR table_name ILIKE '%phrase%'
            OR table_name ILIKE '%stop%'
            OR table_name ILIKE '%product%'
            OR table_name ILIKE '%profile%'
            OR table_name ILIKE '%setting%'
          )
        ORDER BY table_name
        """,
        fetch=True,
    ) or []
    for (table_name,) in rows:
        print(table_name)


def describe_table(db: DatabaseManager, db_name: str, table_name: str) -> None:
    rows = db.execute_query(
        db_name,
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
        fetch=True,
    ) or []
    if rows:
        print(f"\n{db_name}.{table_name}")
        for column_name, data_type in rows:
            print(f"  {column_name}: {data_type}")


def sample_table(db: DatabaseManager, db_name: str, table_name: str, limit: int = 10) -> None:
    try:
        rows = db.execute_query(
            db_name,
            f"SELECT * FROM {table_name} LIMIT {int(limit)}",
            fetch=True,
        ) or []
    except Exception as exc:
        print(f"\n{db_name}.{table_name}: sample error: {exc}")
        return
    if rows:
        print(f"\n{db_name}.{table_name} sample")
        for row in rows[:limit]:
            print(row)


def main() -> None:
    db = make_db()
    for db_name in ("product_catalog_2", "tender_monitor"):
        print_tables(db, db_name)

    interesting = [
        ("product_catalog_2", "products"),
        ("product_catalog_2", "document_stop_phrases"),
        ("product_catalog_2", "user_settings"),
        ("product_catalog_2", "user_keywords"),
        ("tender_monitor", "document_stop_phrases"),
        ("tender_monitor", "user_settings"),
        ("tender_monitor", "user_keywords"),
    ]
    for db_name, table_name in interesting:
        describe_table(db, db_name, table_name)
        sample_table(db, db_name, table_name, 12)


if __name__ == "__main__":
    main()
