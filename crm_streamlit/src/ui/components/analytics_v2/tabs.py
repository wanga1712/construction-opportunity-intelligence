"""Вкладки рабочей области аналитического контура v2.

Layout внутри правой панели:
  - Список компактных карточек (card_compact)
  - При выборе: полный детейл ниже (card_detail) с кнопкой «Назад»
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.ui.components.analytics_v2.card_feed import render_card_feed
from src.ui.components.analytics_v2.card_compact import render_compact_card
from src.ui.components.analytics_v2.card_detail import render_card_detail

_SESSION_TORGI    = "selected_torgi_id"
_SESSION_RAZYGR   = "selected_razygr_id"


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _pg():
    return require_crm_db_connect_kwargs()


def _load_torgi() -> tuple[list[dict], list[dict]]:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, contract_number, auction_name,
                       initial_price, customer, delivery_region,
                       okpd_code, okpd_name, crm_category,
                       contractor_name, contractor_inn,
                       match_score, matched_keywords,
                       start_date, end_date, delivery_end_date,
                       tender_link, award_status,
                       crm_stage, crm_profile_id,
                       source_table, source_id,
                       crm_created_at, crm_updated_at, source_updated_at
                FROM crm_procurements
                WHERE crm_stage = 'torgi'
                ORDER BY
                    CASE award_status
                        WHEN 'submission_open' THEN 1
                        WHEN 'submission_closed_waiting_award' THEN 2
                        WHEN 'award_not_found' THEN 3
                        ELSE 4 END,
                    match_score DESC, end_date DESC
                LIMIT 500
            """)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        active    = [r for r in rows if r["award_status"] != "award_not_found"]
        not_found = [r for r in rows if r["award_status"] == "award_not_found"]
        return active, not_found
    except Exception as e:
        st.warning(f"Ошибка загрузки торгов: {e}")
        return [], []


def _load_razygranye() -> list[dict]:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, contract_number, auction_name,
                       initial_price, final_contract_price,
                       customer, delivery_region,
                       okpd_code, okpd_name, crm_category,
                       contractor_name, contractor_inn,
                       match_score, matched_keywords,
                       winner_name, winner_inn,
                       start_date, end_date,
                       contract_signed_at, execution_end_at,
                       commercial_window_state,
                       tender_link, award_status,
                       crm_stage, crm_profile_id,
                       source_table, source_id,
                       crm_created_at, crm_updated_at, source_updated_at
                FROM crm_procurements
                WHERE crm_stage = 'razygranye'
                ORDER BY contract_signed_at DESC NULLS LAST
                LIMIT 500
            """)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        st.warning(f"Ошибка загрузки разыгранных: {e}")
        return []


def _load_sync_info() -> dict:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT status, finished_at FROM crm_sync_jobs ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def _fmt_date(val) -> str:
    if val is None: return "—"
    try:
        if isinstance(val, date): return val.strftime("%d.%m.%Y")
        return str(val)[:10]
    except Exception: return str(val)


# ─── Торги-таб ────────────────────────────────────────────────────────────────

def _render_torgi_tab() -> None:
    # Панель настроек
    col_grace, col_sync = st.columns([2, 3])
    with col_grace:
        st.selectbox(
            "Показывать после завершения подачи",
            [f"{i} {'день' if i==1 else 'дня' if 2<=i<=4 else 'дней'}" for i in range(1, 31)],
            index=13, key="torgi_grace_days",
        )
    with col_sync:
        info = _load_sync_info()
        if info:
            st.caption(f"Последнее обновление: {_fmt_date(info.get('finished_at'))} · {info.get('status','')}")
        if st.button("↻ Обновить данные", key="torgi_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    active, not_found = _load_torgi()
    all_cards = active + not_found

    if not all_cards:
        st.info("Нет активных торгов. Настройте профили поиска в разделе ⚙️ Профили поиска.")
        return

    # Ищем выбранную карточку
    selected_id = st.session_state.get(_SESSION_TORGI)
    selected_card = next((c for c in all_cards if c["id"] == selected_id), None)

    # Список (всегда виден)
    st.caption(f"Найдено: {len(active) + len(not_found)} закупок"
               + (f" · выбрана #{selected_id}" if selected_id else ""))

    # Компактный список
    for idx, card in enumerate(active):
        render_compact_card(card, idx, session_key=_SESSION_TORGI)

    if not_found:
        with st.expander(f"Не выясненные · результат не найден ({len(not_found)})"):
            for idx, card in enumerate(not_found, start=len(active)):
                render_compact_card(card, idx, session_key=_SESSION_TORGI)

    # Детейл выбранной карточки
    if selected_card:
        st.markdown("---")
        render_card_detail(selected_card, session_key=_SESSION_TORGI)


# ─── Разыгранные-таб ──────────────────────────────────────────────────────────

def _render_razygranye_tab() -> None:
    col_hdr, col_sync = st.columns([3, 2])
    with col_sync:
        if st.button("↻ Обновить данные", key="razygr_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    cards = _load_razygranye()
    if not cards:
        st.info("Нет разыгранных закупок.")
        return

    selected_id   = st.session_state.get(_SESSION_RAZYGR)
    selected_card = next((c for c in cards if c["id"] == selected_id), None)

    st.caption(f"Найдено: {len(cards)} записей")

    for idx, card in enumerate(cards):
        render_compact_card(card, idx, session_key=_SESSION_RAZYGR)

    if selected_card:
        st.markdown("---")
        render_card_detail(selected_card, session_key=_SESSION_RAZYGR)


# ─── Главная функция ──────────────────────────────────────────────────────────

def render_tabs() -> None:
    """Лиды / Подготовка к торгам / Идут торги / Разыгранные."""
    tabs = st.tabs(["Лиды", "Подготовка к торгам", "Идут торги", "Разыгранные"])

    with tabs[0]:
        render_card_feed()

    with tabs[1]:
        st.info("Раздел будет подключён на следующем этапе")

    with tabs[2]:
        _render_torgi_tab()

    with tabs[3]:
        _render_razygranye_tab()
