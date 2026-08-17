"""
Подключение к PostgreSQL nspd_parking_parser (кадастр, УК, паркинг).
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import psycopg2
from dotenv import load_dotenv
from loguru import logger
from psycopg2.extras import RealDictCursor

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class ParkingDbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


def _load_parking_env() -> None:
    """Подхватить PARKING_DB_* или .env из nspd_parking_parser."""
    env_file = _PROJECT_ROOT / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)

    nspd_root = os.environ.get("NSPD_SOURCE_ROOT", "").strip()
    if not nspd_root:
        sibling = _PROJECT_ROOT.parent / "nspd_parking_parser"
        if sibling.is_dir():
            nspd_root = str(sibling)
    if nspd_root:
        nspd_env = Path(nspd_root) / ".env"
        if nspd_env.is_file():
            load_dotenv(nspd_env, override=False)


def get_parking_config() -> ParkingDbConfig:
    _load_parking_env()
    url = os.environ.get("PARKING_DATABASE_URL", "").strip()
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        # postgres URI; password comes from the environment, not this comment
        from urllib.parse import urlparse

        p = urlparse(url)
        return ParkingDbConfig(
            host=p.hostname or "localhost",
            port=p.port or 5432,
            database=(p.path or "/").lstrip("/"),
            user=p.username or "",
            password=p.password or "",
        )

    return ParkingDbConfig(
        host=(
            os.environ.get("PARKING_DB_HOST")
            or os.environ.get("CRM_DB_HOST")
            or os.environ.get("DB_HOST", "localhost")
        ),
        port=int(
            os.environ.get("PARKING_DB_PORT")
            or os.environ.get("CRM_DB_PORT")
            or os.environ.get("DB_PORT", "5432")
        ),
        database=os.environ.get("PARKING_DB_NAME") or os.environ.get("NSPD_ROS_DB_NAME") or os.environ.get("DB_NAME", "nspd_parking"),
        user=os.environ.get("PARKING_DB_USER") or os.environ.get("CRM_DB_USER") or os.environ.get("DB_USER", ""),
        password=os.environ.get("PARKING_DB_PASSWORD") or os.environ.get("CRM_DB_PASSWORD") or os.environ.get("DB_PASSWORD", ""),
    )


class ParkingDatabase:
    """Тонкая обёртка над psycopg2 для карты и УК."""

    def __init__(self) -> None:
        self._conn: Optional[Any] = None
        self._config: Optional[ParkingDbConfig] = None
        self.last_error: Optional[str] = None

    @property
    def config(self) -> ParkingDbConfig:
        if self._config is None:
            self._config = get_parking_config()
        return self._config

    def connect(self) -> bool:
        self.last_error = None
        try:
            if self._conn and not self._conn.closed:
                return True
            cfg = self.config
            if not cfg.user or not cfg.host:
                self.last_error = "PARKING_DB_* не заданы (см. .env.example)"
                return False
            self._conn = psycopg2.connect(
                host=cfg.host,
                port=cfg.port,
                dbname=cfg.database,
                user=cfg.user,
                password=cfg.password,
                connect_timeout=10,
            )
            return True
        except Exception as e:
            logger.error(f"Parking DB: {e}")
            self.last_error = str(e)
            self._conn = None
            return False

    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed

    def query_all(self, sql: str, params: Optional[tuple] = None) -> list[dict]:
        if not self.connect():
            return []
        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params or ())
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Parking query: {e}")
            self.last_error = str(e)
            return []

    def query_one(self, sql: str, params: Optional[tuple] = None) -> Optional[dict]:
        rows = self.query_all(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
        self._conn = None
