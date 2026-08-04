"""Карточка закупки для вкладок «Идут торги» и «Разыгранные»."""
from __future__ import annotations

from datetime import date
from typing import Optional

import streamlit as st

_LEVEL_COLORS = {
    "Gold":   ("#d4a017", "#d4a01722"),
    "Silver": ("#7c8da1", "#7c8da122"),
    "Bronze": ("#b36b2c", "#b36b2c22"),
    "Wood":   ("#8c6b4f", "#8c6b4f22"),
}

_STATUS_ICON = {
    "submission_open":                 "🟢",
    "submission_closed_waiting_award": "🟡",
    "award_not_found":                 "🔴",
}

_COMMERCIAL_WINDOW = {
    "contractor_selected_supply_open":        "Подрядчик выбран · поставщик не определён",
    "contractor_selected_supply_uncertain":   "Подрядчик выбран · поставка под вопросом",
    "supplier_detected":                      "Поставщик обнаружен",
    "supplier_selected":                      "Поставщик выбран",
    "commercial_window_closed":               "Коммерческое окно закрыто",
}

_CARD_CSS = """
<style>
.crm-card-topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 6px;
}
.crm-badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .03em;
}
.crm-status-chip {
    font-size: 12px;
    color: #888;
    white-space: nowrap;
}
.crm-section-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .08em;
    color: #999;
    text-transform: uppercase;
    margin: 10px 0 3px 0;
}
.crm-participants {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    font-size: 13px;
}
.crm-participant-ok   { color: #22c55e; }
.crm-participant-no   { color: #f87171; }
.crm-participant-unkn { color: #94a3b8; }
.crm-check-row {
    font-size: 13px;
    color: #555;
}
.crm-footer-row {
    font-size: 11px;
    color: #aaa;
    margin-top: 8px;
}
.crm-other-cats {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
}
.crm-other-cat-chip {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    background: #f1f5f9;
    color: #64748b;
}
</style>
"""


def _score_to_level(score: int) -> str:
    if score >= 20: return "Gold"
    if score >= 14: return "Silver"
    if score >= 8:  return "Bronze"
    return "Wood"


def _fmt_price(val) -> str:
    if val is None: return "—"
    try:
        n = float(val)
        if n >= 1_000_000_000: return f"{n/1_000_000_000:.2f} млрд ₽"
        if n >= 1_000_000:     return f"{n/1_000_000:.1f} млн ₽"
        return f"{int(n):,} ₽".replace(",", " ")
    except Exception: return str(val)


def _fmt_date(val) -> str:
    if val is None: return "—"
    try:
        if isinstance(val, date): return val.strftime("%d.%m.%Y")
        return str(val)[:10]
    except Exception: return str(val)


def _days_left(end_date) -> Optional[int]:
    if end_date is None: return None
    try:
        if not isinstance(end_date, date):
            from datetime import datetime
            end_date = datetime.strptime(str(end_date)[:10], "%Y-%m-%d").date()
        return (end_date - date.today()).days
    except Exception: return None


def render_torgi_card(card: dict, idx: int) -> None:
    """Полная карточка торгов по макету §14.3."""
    st.markdown(_CARD_CSS, unsafe_allow_html=True)

    score   = card.get("match_score") or 0
    level   = _score_to_level(score)
    color, bg = _LEVEL_COLORS.get(level, ("#8c6b4f", "#8c6b4f22"))
    category = card.get("crm_category") or card.get("okpd_name") or "—"
    status   = card.get("award_status", "submission_open")
    icon     = _STATUS_ICON.get(status, "⚪")
    end_date = card.get("end_date")
    days     = _days_left(end_date)
    keywords = card.get("matched_keywords") or []

    # Строка статуса
    status_parts = [icon]
    if status == "submission_open":
        status_parts.append("ИДУТ ТОРГИ")
    elif status == "submission_closed_waiting_award":
        status_parts.append("ОЖИДАЕТСЯ РЕЗУЛЬТАТ")
    else:
        status_parts.append("РЕЗУЛЬТАТ НЕ НАЙДЕН")
    if end_date:
        status_parts.append(f"ПОДАЧА ДО {_fmt_date(end_date)}")
    if days is not None and days >= 0:
        status_parts.append(f"ОСТАЛОСЬ {days} ДН.")
    elif days is not None and days < 0:
        status_parts.append(f"ПОДАЧА ЗАВЕРШЕНА {-days} ДН. НАЗАД")
    status_str = " · ".join(status_parts)

    with st.container(border=True):
        # ── Топ-бар: бейдж + статус ──
        st.markdown(
            f'<div class="crm-card-topbar">'
            f'<span class="crm-badge" style="background:{bg};color:{color};">'
            f'{level.upper()} · {category.upper()}</span>'
            f'<span class="crm-status-chip">{status_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Заголовок и локация ──
        title = card.get("auction_name") or "—"
        region = card.get("delivery_region") or "—"
        st.markdown(f"**{title}**")
        st.caption(f"📍 {region}")

        # ── ТОВАРНАЯ ВОЗМОЖНОСТЬ ──
        st.markdown('<div class="crm-section-label">Товарная возможность</div>', unsafe_allow_html=True)
        if keywords:
            st.markdown(
                f"Совпадения по запросу: **{' · '.join(keywords[:6])}**"
            )
        else:
            st.caption("Ключевые слова не определены")

        nmck = _fmt_price(card.get("initial_price"))
        kw_str = f"Рейтинг совпадения: **{score}** · НМЦК: **{nmck}**"
        st.caption(kw_str)

        # ── УЧАСТНИКИ ──
        st.markdown('<div class="crm-section-label">Участники</div>', unsafe_allow_html=True)
        customer = card.get("customer") or None
        contractor = card.get("contractor_name") or None

        def _p(label: str, val) -> str:
            if val:
                return f'<span class="crm-participant-ok">✓ {label}: найден</span>'
            return f'<span class="crm-participant-unkn">· {label}: неизвестен</span>'

        st.markdown(
            f'<div class="crm-participants">'
            f'{_p("Заказчик", customer)}'
            f'<span class="crm-participant-unkn">· Балансодержатель: —</span>'
            f'<span class="crm-participant-unkn">· Проектировщик: —</span>'
            f'<span class="crm-participant-no">✗ Подрядчик: не выбран</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── ПРОВЕРКА (из БД если есть, иначе заглушка) ──
        st.markdown('<div class="crm-section-label">Проверка</div>', unsafe_allow_html=True)
        st.markdown(
            '<span class="crm-check-row">'
            'Документов: — · Разобрано: — · Релевантных: — · Evidence: — · '
            'ИИ-анализ: ожидается'
            '</span>',
            unsafe_allow_html=True,
        )

        # ── ДРУГИЕ КАТЕГОРИИ ОБЪЕКТА ──
        other_cats = card.get("other_categories") or []
        if other_cats:
            st.markdown('<div class="crm-section-label">Другие категории объекта</div>', unsafe_allow_html=True)
            chips = "".join(
                f'<span class="crm-other-cat-chip">{c}</span>'
                for c in other_cats
            )
            st.markdown(f'<div class="crm-other-cats">{chips}</div>', unsafe_allow_html=True)

        # ── Футер ──
        updated = card.get("crm_updated_at")
        updated_str = _fmt_date(updated) if updated else "—"
        st.markdown(
            f'<div class="crm-footer-row">Обновлено: {updated_str} · '
            f'Следующая проверка: завтра 11:00</div>',
            unsafe_allow_html=True,
        )

        st.divider()

        # ── Внутренние вкладки карточки ──
        inner_tabs = st.tabs([
            "Обзор", "Материалы", "Документы", "Evidence",
            "Закупка", "Экспертиза", "Участники", "История", "ИИ"
        ])

        with inner_tabs[0]:  # Обзор
            c1, c2, c3 = st.columns(3)
            c1.metric("НМЦК", nmck)
            c2.metric("Рейтинг", f"{score} / 30")
            c3.metric("Подача до", _fmt_date(end_date))
            if card.get("delivery_end_date"):
                st.caption(f"Срок исполнения: {_fmt_date(card.get('delivery_end_date'))}")
            if card.get("tender_link"):
                st.markdown(f"[🔗 Ссылка на торги]({card['tender_link']})")

        with inner_tabs[1]:  # Материалы
            st.info("Анализ материалов будет доступен после подключения ИИ-модуля")

        with inner_tabs[2]:  # Документы
            st.info("Список документов закупки появится после парсинга тендера")

        with inner_tabs[3]:  # Evidence
            st.info("Evidence-блок: подтверждения объёмов из документации")

        with inner_tabs[4]:  # Закупка
            st.markdown(f"**Номер контракта:** {card.get('contract_number') or '—'}")
            st.markdown(f"**Заказчик:** {customer or '—'}")
            st.markdown(f"**Регион поставки:** {region}")
            st.markdown(f"**НМЦК:** {nmck}")
            if card.get("tender_link"):
                st.markdown(f"**Ссылка:** [{card['tender_link']}]({card['tender_link']})")

        with inner_tabs[5]:  # Экспертиза
            st.info("Данные экспертизы появятся после привязки к объекту")

        with inner_tabs[6]:  # Участники
            st.markdown(f"**Заказчик:** {customer or '—'}")
            ct = card.get("contractor_name")
            ct_inn = card.get("contractor_inn")
            if ct:
                st.markdown(f"**Подрядчик:** {ct}" + (f" (ИНН {ct_inn})" if ct_inn else ""))
            else:
                st.caption("Подрядчик ещё не выбран")

        with inner_tabs[7]:  # История
            st.caption("История изменений статусов закупки")
            st.info("Пока нет событий")

        with inner_tabs[8]:  # ИИ
            st.info("ИИ-анализ закупки: совместимость материалов, прогноз победителя")

        st.divider()

        # ── Кнопки действий ──
        b1, b2, b3, b4, b5 = st.columns(5)
        b1.button("Открыть объект", key=f"tc_open_{idx}", use_container_width=True)
        b2.button("☆ Следить", key=f"tc_watch_{idx}", use_container_width=True)
        b3.button("В работу", key=f"tc_work_{idx}", use_container_width=True, type="primary")
        if b4.button("↻ Пересчитать", key=f"tc_reenrich_{idx}", use_container_width=True):
            from src.services.crm_profile_service import queue_reenrich
            ok = queue_reenrich(card.get("id", 0))
            st.toast("Добавлено в очередь" if ok else "Уже в очереди")
        b5.button("⬇ Скачать", key=f"tc_dl_{idx}", use_container_width=True)


def render_razygranye_card(card: dict, idx: int) -> None:
    """Карточка разыгранной закупки."""
    st.markdown(_CARD_CSS, unsafe_allow_html=True)

    score    = card.get("match_score") or 0
    level    = _score_to_level(score)
    color, bg = _LEVEL_COLORS.get(level, ("#8c6b4f", "#8c6b4f22"))
    category = card.get("crm_category") or "—"
    window   = _COMMERCIAL_WINDOW.get(card.get("commercial_window_state") or "", "Статус коммерческого окна не определён")

    init  = card.get("initial_price")
    final = card.get("final_contract_price")
    economy = ""
    try:
        if init and final:
            pct = round((float(init) - float(final)) / float(init) * 100, 1)
            economy = f" (−{pct}%)"
    except Exception:
        pass

    with st.container(border=True):
        st.markdown(
            f'<div class="crm-card-topbar">'
            f'<span class="crm-badge" style="background:{bg};color:{color};">'
            f'{level.upper()} · {category.upper()}</span>'
            f'<span class="crm-status-chip">✅ РАЗЫГРАН · КОНТРАКТ {_fmt_date(card.get("contract_signed_at"))}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown(f"**{card.get('auction_name') or '—'}**")
        st.caption(f"📍 {card.get('delivery_region') or '—'}")

        st.markdown('<div class="crm-section-label">Результат торгов</div>', unsafe_allow_html=True)
        winner    = card.get("winner_name") or "—"
        winner_inn = card.get("winner_inn") or ""
        st.markdown(
            f"Победитель: **{winner}**"
            + (f" (ИНН {winner_inn})" if winner_inn else "")
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Цена контракта", _fmt_price(final) + economy)
        c2.metric("НМЦК", _fmt_price(init))
        c3.metric("Срок исполнения", _fmt_date(card.get("execution_end_at")))

        st.markdown('<div class="crm-section-label">Коммерческое окно</div>', unsafe_allow_html=True)
        st.caption(window)

        st.markdown(
            f'<div class="crm-footer-row">Обновлено: {_fmt_date(card.get("crm_updated_at"))}</div>',
            unsafe_allow_html=True,
        )

        st.divider()

        inner_tabs = st.tabs(["Обзор", "Закупка", "Участники", "История", "ИИ"])

        with inner_tabs[0]:
            if card.get("tender_link"):
                st.markdown(f"[🔗 Ссылка на торги]({card['tender_link']})")
            st.caption(f"Номер: {card.get('contract_number') or '—'}")

        with inner_tabs[1]:
            st.markdown(f"**Заказчик:** {card.get('customer') or '—'}")
            st.markdown(f"**НМЦК:** {_fmt_price(init)}")
            st.markdown(f"**Цена контракта:** {_fmt_price(final)}{economy}")

        with inner_tabs[2]:
            st.markdown(f"**Победитель:** {winner}" + (f" (ИНН {winner_inn})" if winner_inn else ""))
            if card.get("contractor_name"):
                st.markdown(f"**Подрядчик в реестре:** {card['contractor_name']}")

        with inner_tabs[3]:
            st.info("История изменений")

        with inner_tabs[4]:
            st.info("ИИ-анализ: прогноз поставки материалов")

        st.divider()

        b1, b2, b3, b4 = st.columns(4)
        b1.button("Открыть объект", key=f"rc_open_{idx}", use_container_width=True)
        b2.button("☆ Следить", key=f"rc_watch_{idx}", use_container_width=True)
        b3.button("В работу", key=f"rc_work_{idx}", use_container_width=True, type="primary")
        if b4.button("↻ Пересчитать", key=f"rc_reenrich_{idx}", use_container_width=True):
            from src.services.crm_profile_service import queue_reenrich
            ok = queue_reenrich(card.get("id", 0))
            st.toast("Добавлено в очередь" if ok else "Уже в очереди")
