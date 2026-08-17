"""Динамическая загрузка профилей, подкатегорий и управление ключевыми словами."""
from __future__ import annotations

import logging
from typing import Optional

import psycopg2
import psycopg2.extras
import streamlit as st

from src.services.crm_db_runtime import require_crm_db_connect_kwargs

logger = logging.getLogger(__name__)


def _crm_conn():
    return psycopg2.connect(**require_crm_db_connect_kwargs())


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


@st.cache_data(ttl=120, show_spinner=False)
def load_profile_counts() -> dict[int, int]:
    """Количество активных закупок (crm_stage IN torgi/lidy/podgotovka) per profile_id."""
    try:
        conn = _crm_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT crm_profile_id, count(*) AS cnt
                FROM crm_procurements
                WHERE crm_stage IN ('torgi', 'lidy', 'podgotovka')
                  AND crm_profile_id IS NOT NULL
                GROUP BY crm_profile_id
            """)
            return {r["crm_profile_id"]: int(r["cnt"]) for r in cur.fetchall()}
    except Exception as exc:
        logger.error(f"load_profile_counts: {exc}")
        return {}
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


@st.cache_data(ttl=120, show_spinner=False)
def load_category_counts(profile_id: Optional[int] = None) -> dict[str, int]:
    """Количество активных закупок per crm_category (optionally filtered by profile)."""
    try:
        conn = _crm_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if profile_id:
                cur.execute("""
                    SELECT crm_category, count(*) AS cnt
                    FROM crm_procurements
                    WHERE crm_stage IN ('torgi', 'lidy', 'podgotovka')
                      AND crm_profile_id = %s
                      AND crm_category IS NOT NULL
                    GROUP BY crm_category
                """, (profile_id,))
            else:
                cur.execute("""
                    SELECT crm_category, count(*) AS cnt
                    FROM crm_procurements
                    WHERE crm_stage IN ('torgi', 'lidy', 'podgotovka')
                      AND crm_category IS NOT NULL
                    GROUP BY crm_category
                """)
            return {r["crm_category"]: int(r["cnt"]) for r in cur.fetchall()}
    except Exception as exc:
        logger.error(f"load_category_counts: {exc}")
        return {}
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


# ──────────────────────────────────────────────────────────────────────────────
# Иерархический фильтр категорий (CRM-FILTER-1)
# ──────────────────────────────────────────────────────────────────────────────

_CAT_DISPLAY_NAMES: dict[str, str] = {
    "uncategorized": "Без подтверждённой категории",
    "outdoor_lighting": "Наружное освещение",
    "indoor_lighting": "Внутреннее освещение",
    "emergency_lighting": "Аварийное освещение",
    "lighting": "Светотехника",
    "computers": "Компьютеры / IT",
    "monoblock": "Моноблоки",
    "laptop": "Ноутбуки",
    "server": "Серверы",
    "networking": "Сетевое оборудование",
    "education": "Образование",
    "education_kindergarten": "Детские сады",
    "education_school": "Школы",
    "waterproofing": "Гидроизоляция",
    "construction": "Строительство",
}


def _cat_display(code: str) -> str:
    """Display name for a category/subcategory code."""
    return _CAT_DISPLAY_NAMES.get(code, code)


@st.cache_data(ttl=30, show_spinner=False)
def load_category_hierarchy(stage: str = "torgi", filters: dict | None = None) -> dict:
    """
    Один batch-запрос для иерархической агрегации категорий.

    Counts НЕ учитывают текущий category selection — так видны альтернативные категории.

    Returns:
        {
          cat_code: {
            "display": str,
            "count": int,           # суммарный по всем подкатегориям + без подкатегорий
            "subcategories": {
              sub_code: {"display": str, "count": int}
            }
          }
        }
    """
    try:
        conn = _crm_conn()
        params: dict = {"stage": stage}
        extra_where = ""
        if filters:
            if filters.get("profile_id"):
                extra_where += " AND cp.crm_profile_id = %(profile_id)s"
                params["profile_id"] = filters["profile_id"]
            if filters.get("region") and filters["region"] not in ("Все регионы", None, ""):
                extra_where += " AND cp.delivery_region = %(region)s"
                params["region"] = filters["region"]

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                  COALESCE(cc.category, cp.crm_category, cp.object_type, 'uncategorized') AS cat,
                  cc.subcategory,
                  COUNT(DISTINCT cp.id) AS cnt
                FROM crm_procurements cp
                LEFT JOIN crm_category_candidates cc ON cc.procurement_id = cp.id
                WHERE cp.crm_stage = %(stage)s
                {extra_where}
                GROUP BY 1, 2
            """, params)
            rows = cur.fetchall()
        conn.close()

        hierarchy: dict = {}
        for row in rows:
            cat = row["cat"] or "uncategorized"
            sub = row["subcategory"]
            cnt = int(row["cnt"])

            if cat not in hierarchy:
                hierarchy[cat] = {
                    "display": _cat_display(cat),
                    "count": 0,
                    "subcategories": {},
                }
            hierarchy[cat]["count"] += cnt

            if sub:
                if sub not in hierarchy[cat]["subcategories"]:
                    hierarchy[cat]["subcategories"][sub] = {
                        "display": _cat_display(sub),
                        "count": 0,
                    }
                hierarchy[cat]["subcategories"][sub]["count"] += cnt

        return hierarchy
    except Exception as exc:
        logger.error("load_category_hierarchy(stage=%s): %s", stage, exc)
        return {}


def build_category_sql_filter(
    selected_cats: set,
    all_cats_in_hierarchy: set,
) -> tuple[str, dict]:
    """
    Возвращает (sql_fragment, params) для WHERE-условия фильтрации по категориям.

    Rules:
    - Пустой выбор → всё (безопасный fallback, не показываем пустую страницу)
    - Все выбраны → TRUE (без лишнего фильтра)
    - Частичный выбор → условие по списку
    """
    if not selected_cats:
        return "TRUE", {}
    if all_cats_in_hierarchy and selected_cats >= all_cats_in_hierarchy:
        return "TRUE", {}
    cats_list = sorted(selected_cats)
    sql = (
        "COALESCE(cc.category, cp.crm_category, cp.object_type, 'uncategorized')"
        " = ANY(%(selected_cats)s)"
    )
    return sql, {"selected_cats": cats_list}


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
