"""Ручные категорийные возможности (MANUAL) поверх crm_manual_category_overrides.

Не создаёт параллельную модель: пишем в существующую таблицу ручных
переопределений (уникальность procurement_id + category_code), а read-model
таблицы/карточки объединяет её с автоматическими возможностями.

Ручная запись:
  * источник MANUAL, автор (reviewed_by), время (reviewed_at), комментарий;
  * медаль не наследуется — статус UNSCORED (manual_candidate_level='UNSCORED');
  * авто-анализ её не перезаписывает (живёт отдельно от opportunities).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

MANUAL_SOURCE = "MANUAL"
UNSCORED = "UNSCORED"
# Режим хранится в expected_role (проверка справочника), а НЕ в
# commercial_entry_point (это другая ось: DIRECT_SUPPLY/SUPPLIER/...).
_ROLES = {"EMBEDDED_MATERIAL", "PRIMARY_SUPPLY", "CONSUMABLE",
          "OBJECT_OF_RESEARCH", "AUXILIARY_CONTEXT", "ABSENT", "UNKNOWN"}
_MODE_TO_ROLE = {
    "EMBEDDED_MATERIAL": "EMBEDDED_MATERIAL",
    "DIRECT_SUPPLY": "PRIMARY_SUPPLY",
    "DESIGN_REQUIREMENT": "OBJECT_OF_RESEARCH",
}


def _connect() -> Any:
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    return psycopg2.connect(**require_crm_db_connect_kwargs())


def list_categories(db: Any = None) -> List[Dict[str, Any]]:
    """Действующий справочник категорий (реальный, без выдумывания)."""
    sql = """SELECT category_code, category_name FROM crm_product_categories
             WHERE COALESCE(is_active, true) ORDER BY category_name"""
    if db is not None:
        rows = db.execute_query(sql) or []
        return [dict(r) for r in rows]
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def list_subcategories(category_code: str, db: Any = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT s.subcategory_code, COALESCE(s.subcategory_name, s.subcategory_code) AS subcategory_name
        FROM crm_product_subcategories s
        JOIN crm_product_categories c ON c.id = s.category_id
        WHERE c.category_code = %s AND COALESCE(s.is_active, true)
        ORDER BY 2
    """
    if db is not None:
        rows = db.execute_query(sql, (category_code,)) or []
        return [dict(r) for r in rows]
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (category_code,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def list_manual_categories(db: Any, procurement_id: int) -> List[Dict[str, Any]]:
    """Ручные категории закупки (для merge в read-model)."""
    return [
        dict(r) for r in (
            db.execute_query(
                """
                SELECT m.category_code, m.subcategory_code, m.commercial_entry_point,
                       m.manual_reason, m.reviewed_by, m.reviewed_at,
                       m.manual_candidate_level,
                       c.category_name
                FROM crm_manual_category_overrides m
                LEFT JOIN crm_product_categories c ON c.category_code = m.category_code
                WHERE m.procurement_id = %s
                """,
                (int(procurement_id),),
            ) or []
        )
    ]


def add_manual_category(
    procurement_id: int, category_code: str, *, subcategory_code: Optional[str] = None,
    mode: str = "EMBEDDED_MATERIAL", comment: Optional[str] = None,
    author: str = "operator",
) -> Dict[str, Any]:
    """Добавить ручную категорию. Возвращает {ok, action, ...}."""
    cat = str(category_code or "").strip()
    if not cat:
        return {"ok": False, "action": "category_required"}
    mode = str(mode or "").strip().upper()
    role = _MODE_TO_ROLE.get(mode, "EMBEDDED_MATERIAL")
    if role not in _ROLES:
        role = "EMBEDDED_MATERIAL"
    entry = "DIRECT_SUPPLY" if mode == "DIRECT_SUPPLY" else "UNKNOWN"
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id FROM crm_manual_category_overrides
                   WHERE procurement_id=%s AND category_code=%s""",
                (int(procurement_id), cat),
            )
            if cur.fetchone() is not None:
                return {"ok": False, "action": "already_exists", "category_code": cat}
            cur.execute(
                """INSERT INTO crm_manual_category_overrides
                   (procurement_id, category_code, subcategory_code, opportunity_status,
                    expected_role, commercial_entry_point, expected_volume, priority,
                    research_action, manual_candidate_level, manual_reason,
                    reviewed_by, reviewed_at)
                   VALUES (%s,%s,%s,'POSSIBLE',%s,%s,'HIGH',1.0,
                           'METADATA_ONLY',NULL,%s,%s,NOW())
                   RETURNING id""",
                (int(procurement_id), cat, subcategory_code, role, entry,
                 comment or "manual category added by operator", author),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()
        return {"ok": True, "action": "inserted", "id": new_id,
                "category_code": cat, "mode": mode}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "action": "error", "error": str(exc)}
    finally:
        conn.close()


def remove_manual_category(procurement_id: int, category_code: str) -> Dict[str, Any]:
    """Обратимое удаление ручной категории (только MANUAL-хранилище)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM crm_manual_category_overrides
                   WHERE procurement_id=%s AND category_code=%s""",
                (int(procurement_id), str(category_code)),
            )
            deleted = cur.rowcount
        conn.commit()
        return {"ok": deleted > 0, "action": "deleted", "deleted": deleted}
    finally:
        conn.close()


_MEDALS = ("GOLD", "SILVER", "BRONZE", "WOOD")


def set_manual_medal(
    procurement_id: int, category_code: str, medal: str, *, author: str = "operator"
) -> Dict[str, Any]:
    """Быстрая смена медали категории (ручное решение пользователя).

    Пишет в MANUAL-хранилище; авто-классификация не меняется. Медаль группы
    пересчитывается по действующему контракту best-medal.
    """
    med = str(medal or "").strip().upper()
    if med not in _MEDALS:
        return {"ok": False, "action": "invalid_medal", "medal": medal}
    cat = str(category_code or "").strip()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO crm_manual_category_overrides
                   (procurement_id, category_code, opportunity_status, expected_role,
                    commercial_entry_point, expected_volume, priority, research_action,
                    manual_candidate_level, manual_reason, reviewed_by, reviewed_at)
                   VALUES (%s,%s,'POSSIBLE','EMBEDDED_MATERIAL','UNKNOWN','HIGH',1.0,
                           'METADATA_ONLY',%s,'manual medal change',%s,NOW())
                   ON CONFLICT (procurement_id, category_code) DO UPDATE SET
                       manual_candidate_level = EXCLUDED.manual_candidate_level,
                       manual_reason = EXCLUDED.manual_reason,
                       reviewed_by = EXCLUDED.reviewed_by,
                       reviewed_at = NOW(),
                       updated_at = NOW()""",
                (int(procurement_id), cat, med, author),
            )
        conn.commit()
        return {"ok": True, "action": "medal_set", "category_code": cat, "medal": med}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "action": "error", "error": str(exc)}
    finally:
        conn.close()
