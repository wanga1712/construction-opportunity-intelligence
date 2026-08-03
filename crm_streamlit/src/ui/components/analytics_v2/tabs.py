"""Вкладки рабочей области аналитического контура v2."""
from __future__ import annotations

from datetime import date
from typing import Optional

import streamlit as st

from src.ui.components.analytics_v2.card_feed import render_card_feed

_STATUS_LABEL = {
    "submission_open": ("🟢", "Подача заявок открыта"),
    "submission_closed_waiting_award": ("🟡", "Подача завершена · ожидается результат"),
    "award_not_found": ("🔴", "Результат не найден"),
}

_COMMERCIAL_WINDOW = {
    "contractor_selected_supply_open": "Подрядчик выбран · поставщик не определён",
    "contractor_selected_supply_uncertain": "Подрядчик выбран · поставка под вопросом",
    "supplier_detected": "Поставщик обнаружен",
    "supplier_selected": "Поставщик выбран",
    "commercial_window_closed": "Коммерческое окно закрыто",
}

_SCORE_LEVEL = {
    range(20, 999): ("Gold", "#d4a017"),
    range(14, 20): ("Silver", "#7c8da1"),
    range(8, 14): ("Bronze", "#b36b2c"),
    range(0, 8): ("Wood", "#8c6b4f"),
}


def _score_to_level(score: int) -> tuple[str, str]:
    for r, val in _SCORE_LEVEL.items():
        if score in r:
            return val
    return ("Wood", "#8c6b4f")


def _fmt_price(val) -> str:
    if val is None:
        return "—"
    try:
        n = int(float(val))
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f} млн ₽"
        return f"{n:,} ₽".replace(",", " ")
    except Exception:
        return str(val)


def _fmt_date(val) -> str:
    if val is None:
        return "—"
    try:
        if isinstance(val, date):
            return val.strftime("%d.%m.%Y")
        return str(val)[:10]
    except Exception:
        return str(val)


def _badge(level: str, color: str, category: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'background:{color}22;color:{color};font-size:12px;font-weight:700;">'
        f'{level} · {category}</span>'
    )


def _load_torgi(grace_days: int) -> tuple[list[dict], list[dict]]:
    """Загружает карточки «Идут торги» из crm_procurements."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        import os
        PG = dict(
            host=os.environ.get("CRM_DB_HOST", "10.8.0.7"),
            port=int(os.environ.get("CRM_DB_PORT", 5432)),
            user=os.environ.get("CRM_DB_USER", "postgres"),
            password=os.environ.get("CRM_DB_PASSWORD", "0IFz3_"),
            dbname="crm",
        )
        conn = psycopg2.connect(**PG)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, contract_number, auction_name,
                       initial_price, customer, delivery_region,
                       okpd_code, okpd_name, crm_category,
                       match_score, matched_keywords,
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
                        ELSE 4 END,
                    match_score DESC,
                    end_date DESC
                LIMIT 500
            """)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        active = [r for r in rows if r["award_status"] != "award_not_found"]
        not_found = [r for r in rows if r["award_status"] == "award_not_found"]
        return active, not_found
    except Exception as e:
        st.warning(f"Ошибка загрузки данных торгов: {e}")
        return [], []


def _load_razygranye() -> list[dict]:
    """Загружает карточки «Разыгранные» из crm_procurements."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        import os
        PG = dict(
            host=os.environ.get("CRM_DB_HOST", "10.8.0.7"),
            port=int(os.environ.get("CRM_DB_PORT", 5432)),
            user=os.environ.get("CRM_DB_USER", "postgres"),
            password=os.environ.get("CRM_DB_PASSWORD", "0IFz3_"),
            dbname="crm",
        )
        conn = psycopg2.connect(**PG)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, contract_number, auction_name,
                       initial_price, final_contract_price,
                       customer, delivery_region,
                       okpd_code, okpd_name, crm_category,
                       match_score,
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
        import os
        PG = dict(host=os.environ.get("CRM_DB_HOST","10.8.0.7"),
                  port=int(os.environ.get("CRM_DB_PORT",5432)),
                  user=os.environ.get("CRM_DB_USER","postgres"),
                  password=os.environ.get("CRM_DB_PASSWORD","0IFz3_"),
                  dbname="crm")
        conn = psycopg2.connect(**PG)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT status, started_at, finished_at
                FROM crm_sync_jobs ORDER BY id DESC LIMIT 1
            """)
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def _render_torgi_card(card: dict, idx: int) -> None:
    status = card.get("award_status", "submission_open")
    icon, label = _STATUS_LABEL.get(status, ("⚪", status))
    is_not_found = status == "award_not_found"
    score = card.get("match_score", 0) or 0
    level, color = _score_to_level(score)
    category = card.get("crm_category") or card.get("okpd_name") or "—"
    keywords = card.get("matched_keywords") or []

    with st.container(border=True):
        if is_not_found:
            st.warning(f"Результат не найден после окончания подачи ({_fmt_date(card.get('end_date'))})")

        left, right = st.columns([5, 1])
        with left:
            st.markdown(_badge(level, color, category), unsafe_allow_html=True)
            st.markdown(f'**{card.get("auction_name") or "—"}**')
            c1, c2, c3, c4 = st.columns(4)
            c1.caption(f'📍 {card.get("delivery_region") or "—"}')
            c2.caption(f'{icon} {label}')
            c3.caption(f'Подача до: {_fmt_date(card.get("end_date"))}')
            c4.caption(f'Обновлено: {_fmt_date(card.get("crm_updated_at"))}')
            st.caption(
                f'Заказчик: {card.get("customer") or "—"} · '
                f'НМЦК: {_fmt_price(card.get("initial_price"))}'
            )
            if keywords:
                st.caption("Совпадения: " + " · ".join(keywords[:5]))
        with right:
            st.button("Открыть", key=f"torgi_open_{idx}", use_container_width=True)
            st.button("☆", key=f"torgi_fav_{idx}", use_container_width=True)


def _render_razygranye_card(card: dict, idx: int) -> None:
    window_label = _COMMERCIAL_WINDOW.get(card.get("commercial_window_state") or "", "—")
    score = card.get("match_score", 0) or 0
    level, color = _score_to_level(score)
    category = card.get("crm_category") or "—"

    init = card.get("initial_price")
    final = card.get("final_contract_price")
    economy = ""
    try:
        if init and final:
            pct = round((float(init) - float(final)) / float(init) * 100, 1)
            economy = f" (−{pct}%)"
    except Exception:
        pass

    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(_badge(level, color, category), unsafe_allow_html=True)
            st.markdown(f'**{card.get("auction_name") or "—"}**')
            c1, c2, c3 = st.columns(3)
            c1.caption(f'📍 {card.get("delivery_region") or "—"}')
            c2.caption(f'Контракт: {_fmt_date(card.get("contract_signed_at"))}')
            c3.caption(f'Срок исполнения: {_fmt_date(card.get("execution_end_at"))}')
            winner = card.get("winner_name") or "—"
            inn = card.get("winner_inn") or ""
            st.caption(
                f'Победитель: {winner}{(" (ИНН " + inn + ")") if inn else ""} · '
                f'Цена: {_fmt_price(final)}{economy}'
            )
            st.caption(f'Коммерческое окно: {window_label}')
        with right:
            st.button("Открыть", key=f"razygr_open_{idx}", use_container_width=True)
            st.button("☆", key=f"razygr_fav_{idx}", use_container_width=True)


def _render_torgi_tab() -> None:
    col_set, col_sync = st.columns([2, 3])
    with col_set:
        grace_label = st.selectbox(
            "Показывать после завершения подачи",
            [f"{i} {'день' if i == 1 else 'дня' if 2 <= i <= 4 else 'дней'}" for i in range(1, 31)],
            index=13,
            key="torgi_grace_days",
        )
    grace_days = int(grace_label.split()[0])

    with col_sync:
        sync_info = _load_sync_info()
        if sync_info:
            last = _fmt_date(sync_info.get("finished_at"))
            status = sync_info.get("status", "")
            st.caption(f"Последнее обновление: {last} · Статус: {status}")
        else:
            st.caption("История синхронизации пуста")
        if st.button("↻ Обновить данные", key="torgi_sync_btn"):
            st.cache_data.clear()
            st.info("Кэш очищен, данные перезагружаются...")

    active, not_found = _load_torgi(grace_days)

    if not active and not not_found:
        st.info("Нет активных торгов. Данные ещё не синхронизированы или профиль не настроен.")
        return

    st.caption(f"Найдено: {len(active) + len(not_found)} закупок")

    for idx, card in enumerate(active):
        _render_torgi_card(card, idx)

    if not_found:
        with st.expander(f"Не выясненные · результат не найден ({len(not_found)})"):
            for idx, card in enumerate(not_found, start=len(active)):
                _render_torgi_card(card, idx)


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
        col_sync = st.columns([3, 2])
        with col_sync[1]:
            if st.button("↻ Обновить данные", key="razygr_sync_btn"):
                st.cache_data.clear()
                st.info("Кэш очищен...")

        cards = _load_razygranye()
        if not cards:
            st.info("Нет разыгранных закупок в базе.")
        else:
            st.caption(f"Найдено: {len(cards)} записей")
            for idx, card in enumerate(cards):
                _render_razygranye_card(card, idx)
