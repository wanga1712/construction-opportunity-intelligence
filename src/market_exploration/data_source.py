"""Data source adapters for Market Exploration (read-only production DB and in-memory)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Protocol, Set


class MarketExplorationDataSourceProtocol(Protocol):
    """Protocol for accessing procurement market data."""

    def load_procurements_data(self, window_days: Optional[int] = 365) -> List[Dict[str, Any]]: ...
    def get_source_snapshot_id(self) -> str: ...


class InMemoryMarketExplorationDataSource:
    """In-memory data source for unit tests and offline simulations."""

    def __init__(self, procurements: List[Dict[str, Any]], snapshot_id: str = "in_memory_snap") -> None:
        self._procurements = procurements
        self._snapshot_id = snapshot_id

    def load_procurements_data(self, window_days: Optional[int] = 365) -> List[Dict[str, Any]]:
        if window_days is None:
            return list(self._procurements)

        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        filtered = []
        for p in self._procurements:
            p_date_str = p.get("published_date") or p.get("publish_date") or p.get("created_at")
            if p_date_str:
                try:
                    p_date = datetime.fromisoformat(str(p_date_str).replace("Z", "+00:00"))
                    if p_date < cutoff:
                        continue
                except Exception:
                    pass
            filtered.append(p)
        return filtered

    def get_source_snapshot_id(self) -> str:
        return self._snapshot_id


class PostgresMarketExplorationDataSource:
    """Read-only PostgreSQL adapter querying production procurement data and research status."""

    def __init__(self, connection_factory: Callable[[], Any], default_snapshot_name: str = "prod_db") -> None:
        self._connection_factory = connection_factory
        self._default_snapshot_name = default_snapshot_name

    def load_procurements_data(self, window_days: Optional[int] = 365) -> List[Dict[str, Any]]:
        """Loads procurements data with joined research status and document metadata (READ-ONLY)."""
        conn = self._connection_factory()
        try:
            # Enforce read-only transaction on connection
            if hasattr(conn, "set_session"):
                conn.set_session(readonly=True, autocommit=True)

            with conn.cursor() as cur:
                # 1. Base query checking crm_procurements
                sql = """
                    SELECT 
                        p.id as procurement_id,
                        COALESCE(p.title, p.auction_name, '') as auction_name,
                        COALESCE(p.okpd2_code, p.okpd_code, '') as okpd_code,
                        COALESCE(p.initial_price, p.lot_price, 0.0) as lot_price,
                        p.publication_date,
                        COALESCE(p.customer_name, '') as customer_name,
                        COALESCE(p.region, '') as region
                    FROM crm_procurements p
                """
                params: List[Any] = []
                if window_days is not None:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
                    sql += " WHERE (p.publication_date IS NULL OR p.publication_date >= %s)"
                    params.append(cutoff)

                sql += " ORDER BY p.id DESC LIMIT 5000;"

                try:
                    cur.execute(sql, tuple(params))
                    rows = cur.fetchall()
                except Exception:
                    # Fallback to procurements table if crm_procurements has different name
                    conn.rollback()
                    fallback_sql = "SELECT id, COALESCE(auction_name, title, ''), COALESCE(okpd_code, ''), COALESCE(lot_price, 0.0), publication_date, '', '' FROM procurements ORDER BY id DESC LIMIT 5000;"
                    cur.execute(fallback_sql)
                    rows = cur.fetchall()

                # 2. Gather research completion status from document tables if available
                researched_map: Dict[int, Dict[str, Any]] = {}
                try:
                    cur.execute("""
                        SELECT 
                            q.procurement_id,
                            q.status,
                            COUNT(f.id) as doc_count,
                            COALESCE(SUM(f.file_size), 0) as total_bytes
                        FROM document_processing_queue q
                        LEFT JOIN document_files f ON f.queue_id = q.id
                        GROUP BY q.procurement_id, q.status;
                    """)
                    for r_row in cur.fetchall():
                        pid = int(r_row[0])
                        researched_map[pid] = {
                            "status": str(r_row[1]),
                            "doc_count": int(r_row[2]),
                            "total_bytes": int(r_row[3]),
                        }
                except Exception:
                    # Table might be in separate document_intelligence db or empty
                    pass

                results: List[Dict[str, Any]] = []
                for r in rows:
                    pid = int(r[0])
                    res_info = researched_map.get(pid, {})
                    is_researched = res_info.get("status") in ("COMPLETED", "PROCESSED", "SUCCESS")

                    results.append({
                        "procurement_id": pid,
                        "auction_name": str(r[1]),
                        "okpd_code": str(r[2]),
                        "lot_price": float(r[3] or 0.0),
                        "published_date": r[4].isoformat() if r[4] and hasattr(r[4], "isoformat") else str(r[4] or ""),
                        "customer_name": str(r[5]),
                        "region": str(r[6]),
                        "is_researched": is_researched,
                        "research_status": "RESEARCHED" if is_researched else "UNRESEARCHED",
                        "document_count": res_info.get("doc_count", 0),
                        "estimated_size_bytes": res_info.get("total_bytes", 0),
                    })

                return results
        finally:
            conn.close()

    def get_source_snapshot_id(self) -> str:
        """Returns deterministic hash/identifier for current database state."""
        return f"{self._default_snapshot_name}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
