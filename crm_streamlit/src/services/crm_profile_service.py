"""Динамическая загрузка профилей, подкатегорий и управление ключевыми словами."""
from __future__ import annotations

import logging
import os
from typing import Optional

import psycopg2
import psycopg2.extras
import streamlit as st

logger = logging.getLogger(__name__)

_PG = dict(
    host=os.environ.get("CRM_DB_HOST", "10.8.0.7"),
    port=int(os.environ.get("CRM_DB_PORT", 5432)),
    user=os.environ.get("CRM_DB_USER", "postgres"),
    password=os.environ.get("CRM_DB_PASSWORD", "0IFz3_"),
    dbname="crm",
)


def _crm_conn():
    return psycopg2.connect(**_PG)


@st.cache_data(ttl=60, show_spinner=False)
def load_profiles() -> list[dict]:
    """Все активные профили поиска из crm_search_profiles."""
    try:
        conn = _crm_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT p.id, p.name, p.code,
                       count(r.id) as keyword_count
                FROM crm_search_profiles p
                LEFT JOIN crm_search_rules r
                    ON r.search_profile_id = p.id AND r.is_active = true
                GROUP BY p.id, p.name, p.code
                ORDER BY p.name
            """)
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error(f"load_profiles: {exc}")
        return []
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def load_subcategories(profile_id: Optional[int] = None) -> list[str]:
    """Уникальные подкатегории для профиля (или все если profile_id=None)."""
    try:
        conn = _crm_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if profile_id:
                cur.execute("""
                    SELECT DISTINCT subcategory FROM crm_search_rules
                    WHERE is_active = true AND subcategory IS NOT NULL
                      AND search_profile_id = %s
                    ORDER BY subcategory
                """, (profile_id,))
            else:
                cur.execute("""
                    SELECT DISTINCT subcategory FROM crm_search_rules
                    WHERE is_active = true AND subcategory IS NOT NULL
                    ORDER BY subcategory
                """)
            return [r["subcategory"] for r in cur.fetchall()]
    except Exception as exc:
        logger.error(f"load_subcategories: {exc}")
        return []
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def load_profile_keywords(profile_id: int) -> list[dict]:
    """Все ключевые слова профиля с подкатегорией и весом."""
    try:
        conn = _crm_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, subcategory, value, weight, is_active, notes
                FROM crm_search_rules
                WHERE search_profile_id = %s AND rule_type = 'include_keyword'
                ORDER BY subcategory NULLS LAST, weight DESC, value
            """, (profile_id,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error(f"load_profile_keywords: {exc}")
        return []
    finally:
        conn.close()


def upsert_profile(name: str, code: str) -> int:
    """Создаёт или возвращает id профиля по коду."""
    conn = _crm_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO crm_search_profiles (name, code)
            VALUES (%s, %s)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
        """, (name, code))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM crm_search_profiles WHERE code = %s", (code,))
        return cur.fetchone()[0]
    conn.close()


def seed_keywords(profile_id: int, rows: list[dict], replace_subcategory: Optional[str] = None) -> int:
    """
    Засевает ключевые слова профиля.
    rows: [{subcategory, keyword, weight}]
    replace_subcategory: если указан — сначала деактивирует все старые правила этой подкатегории.
    """
    conn = _crm_conn()
    conn.autocommit = False
    n = 0
    with conn.cursor() as cur:
        if replace_subcategory is not None:
            cur.execute("""
                UPDATE crm_search_rules SET is_active = false
                WHERE search_profile_id = %s AND subcategory = %s
            """, (profile_id, replace_subcategory))

        for row in rows:
            cur.execute("""
                INSERT INTO crm_search_rules
                    (scope, search_profile_id, rule_type, subcategory, value, weight, is_active, created_by)
                VALUES ('profile', %s, 'include_keyword', %s, %s, %s, true, 'upload')
                ON CONFLICT DO NOTHING
            """, (
                profile_id,
                row.get("subcategory") or None,
                row["keyword"],
                int(row.get("weight", 8)),
            ))
            n += 1
    conn.commit()
    conn.close()
    return n


def trigger_sync_refresh() -> None:
    """Сбрасывает кэш Streamlit + создаёт задание на пересев match_cache."""
    st.cache_data.clear()
    try:
        conn = _crm_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO crm_sync_jobs (job_type, trigger_type, status)
                VALUES ('match_cache_refresh', 'profile_upload', 'queued')
            """)
        conn.close()
    except Exception as exc:
        logger.warning(f"trigger_sync_refresh: {exc}")


def queue_reenrich(procurement_id: int) -> bool:
    """Ставит закупку в очередь ручного переобогащения."""
    try:
        conn = _crm_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            # Не дублируем если уже в очереди
            cur.execute("""
                SELECT id FROM crm_enrich_jobs
                WHERE procurement_id = %s AND status IN ('queued', 'running')
                LIMIT 1
            """, (procurement_id,))
            if cur.fetchone():
                return False
            cur.execute("""
                INSERT INTO crm_enrich_jobs (procurement_id, trigger_type, status)
                VALUES (%s, 'manual', 'queued')
            """, (procurement_id,))
        conn.close()
        return True
    except Exception as exc:
        logger.error(f"queue_reenrich: {exc}")
        return False
