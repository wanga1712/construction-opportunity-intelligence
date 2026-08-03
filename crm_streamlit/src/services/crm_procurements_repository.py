"""Чтение crm_procurements для страницы V2."""
from __future__ import annotations

import streamlit as st
from typing import Optional


@st.cache_data(ttl=300, show_spinner=False)
def load_torgi_cards(crm_db_key: str, grace_days: int = 14) -> list[dict]:
    """Загружает карточки вкладки «Идут торги» из crm_procurements."""
    from src.services.session_crm_db import get_crm_db
    db = get_crm_db()
    if not db:
        return []
    try:
        rows = db.execute_query("""
            SELECT
                id, contract_number, auction_name,
                initial_price, customer, delivery_region,
                okpd_code, okpd_name,
                end_date, delivery_end_date,
                tender_link, award_status,
                crm_updated_at
            FROM crm_procurements
            WHERE crm_stage = 'torgi'
            ORDER BY
                CASE award_status
                    WHEN 'submission_open' THEN 1
                    WHEN 'submission_closed_waiting_award' THEN 2
                    WHEN 'award_not_found' THEN 3
                    ELSE 4
                END,
                end_date DESC
            LIMIT 500
        """)
        return [dict(r) for r in rows]
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def load_razygranye_cards(crm_db_key: str) -> list[dict]:
    """Загружает карточки вкладки «Разыгранные» из crm_procurements."""
    from src.services.session_crm_db import get_crm_db
    db = get_crm_db()
    if not db:
        return []
    try:
        rows = db.execute_query("""
            SELECT
                id, contract_number, auction_name,
                initial_price, final_contract_price,
                customer, delivery_region,
                okpd_code, okpd_name,
                winner_name, winner_inn,
                contract_signed_at, execution_end_at,
                commercial_window_state,
                awarded_match_confidence,
                crm_updated_at
            FROM crm_procurements
            WHERE crm_stage = 'razygranye'
            ORDER BY contract_signed_at DESC NULLS LAST
            LIMIT 500
        """)
        return [dict(r) for r in rows]
    except Exception:
        return []


def load_settings(crm_db) -> dict:
    """Читает настройки CRM из crm_settings."""
    defaults = {"post_submission_grace_days": 14}
    if not crm_db:
        return defaults
    try:
        rows = crm_db.execute_query("SELECT key, value FROM crm_settings")
        out = {r["key"]: r["value"] for r in rows}
        out["post_submission_grace_days"] = int(
            out.get("post_submission_grace_days", 14)
        )
        return out
    except Exception:
        return defaults


def load_last_sync_info(crm_db) -> dict:
    """Информация о последнем sync-задании."""
    if not crm_db:
        return {}
    try:
        rows = crm_db.execute_query("""
            SELECT status, started_at, finished_at,
                   processed_count, updated_count,
                   awarded_count, not_found_count, error_count
            FROM crm_sync_jobs
            ORDER BY id DESC LIMIT 1
        """)
        return dict(rows[0]) if rows else {}
    except Exception:
        return {}


def save_grace_days(crm_db, days: int) -> None:
    if not crm_db:
        return
    try:
        crm_db.execute_update(
            "UPDATE crm_settings SET value=%(v)s, updated_at=now() WHERE key='post_submission_grace_days'",
            {"v": str(days)},
        )
    except Exception:
        pass


def trigger_manual_sync(crm_db) -> Optional[int]:
    """Создаёт запись sync-задания со статусом queued."""
    if not crm_db:
        return None
    try:
        rows = crm_db.execute_query("""
            SELECT id FROM crm_sync_jobs
            WHERE status IN ('queued','running')
            LIMIT 1
        """)
        if rows:
            return None  # уже идёт
        crm_db.execute_update("""
            INSERT INTO crm_sync_jobs (job_type, trigger_type, status)
            VALUES ('active_to_awarded', 'manual', 'queued')
        """)
        rows = crm_db.execute_query(
            "SELECT id FROM crm_sync_jobs ORDER BY id DESC LIMIT 1"
        )
        return rows[0]["id"] if rows else None
    except Exception:
        return None
