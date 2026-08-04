"""Полная карточка объекта — детальный вид с trust-логикой."""
from __future__ import annotations

from datetime import date
from typing import Optional

import streamlit as st

from src.ui.components.analytics_v2.card_trust import (
    resolve_level, submission_status, fmt_price, fmt_date,
    STAGE_LABEL, STAGE_DESCRIPTION, STAGE_ORDER,
    participant_source_label, days_left, deadline_penalty,
    required_submission_days,
)

_CARD_CSS = """
<style>
.crm-card-topbar {
    display: flex; justify-content: space-between;
    align-items: center; flex-wrap: wrap;
    gap: 6px; margin-bottom: 6px;
}
.crm-badge {
    display: inline-block; padding: 3px 14px; border-radius: 999px;
    font-size: 12px; font-weight: 700; letter-spacing: .03em;
}
.crm-status-chip { font-size: 12px; color: #888; white-space: nowrap; }
.crm-section-label {
    font-size: 10px; font-weight: 700; letter-spacing: .08em;
    color: #999; text-transform: uppercase; margin: 12px 0 4px 0;
}
.crm-participants { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; }
.crm-participant-ok   { color: #22c55e; }
.crm-participant-no   { color: #f87171; }
.crm-participant-unkn { color: #94a3b8; }
.crm-participant-src  { font-size: 11px; color: #94a3b8; }
.crm-check-row { font-size: 13px; color: #555; line-height: 1.7; }
.crm-footer-row { font-size: 11px; color: #aaa; margin-top: 10px; }
.crm-other-cats { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
.crm-other-cat-chip {
    font-size: 11px; padding: 2px 8px; border-radius: 4px;
    background: #f1f5f9; color: #64748b;
}
.crm-stage-bar { display: flex; gap: 4px; flex-wrap: wrap; margin: 8px 0; }
.crm-stage-chip { font-size: 10px; padding: 2px 10px; border-radius: 4px; font-weight: 600; }
.crm-stage-done { background: #dcfce7; color: #166534; }
.crm-stage-curr { background: #dbeafe; color: #1d4ed8; }
.crm-stage-todo { background: #f1f5f9; color: #94a3b8; }
.crm-deadline-warn {
    background: #fee2e2; border: 1px solid #fca5a5;
    border-radius: 6px; padding: 8px 14px; font-size: 13px;
    color: #991b1b; font-weight: 600; margin: 6px 0;
}
.crm-signal-box {
    background: #fefce8; border: 1px solid #fde68a;
    border-radius: 6px; padding: 10px 14px; margin: 6px 0; font-size: 13px;
}
.crm-confirmed-box {
    background: #f0fdf4; border: 1px solid #86efac;
    border-radius: 6px; padding: 10px 14px; margin: 6px 0; font-size: 13px;
}
</style>
"""

_STAGE_CHIPS = [
    ("raw",               "RAW"),
    ("documents_loaded",  "ДОКУМЕНТЫ"),
    ("matches_found",     "СИГНАЛЫ"),
    ("ai_verified",       "ИИ ВЕРИФИЦИРОВАН"),
    ("ranked",            "РАНЖИРОВАН"),
    ("manager_confirmed", "ПОДТВЕРЖДЁН"),
]

_COMMERCIAL_WINDOW = {
    "contractor_selected_supply_open":      "Подрядчик выбран · поставщик не определён",
    "contractor_selected_supply_uncertain": "Подрядчик выбран · поставка под вопросом",
    "supplier_detected":                    "Поставщик обнаружен",
    "supplier_selected":                    "Поставщик выбран",
    "commercial_window_closed":             "Коммерческое окно закрыто",
}


def render_card_detail(card: dict, session_key: str = "selected_procurement_id") -> None:
    st.markdown(_CARD_CSS, unsafe_allow_html=True)

    if st.button("← Назад к списку", key=f"cd_back_{card.get('id')}"):
        st.session_state.pop(session_key, None)
        st.rerun()

    st.markdown("---")

    # ── Разбираем поля ──
    level_label, color, bg, is_medal = resolve_level(card)
    stage       = card.get("processing_stage", "matches_found")
    category    = card.get("crm_category") or card.get("okpd_name") or "—"
    manager_ok  = stage == "manager_confirmed"
    end_date    = card.get("end_date")
    days        = days_left(end_date)
    price       = card.get("initial_price")
    req_days    = required_submission_days(price)
    expired, _, _ = deadline_penalty(card)
    icon, status_label, status_cls = submission_status(
        card.get("award_status", "submission_open"), end_date
    )
    title          = card.get("auction_name") or "—"
    region         = card.get("delivery_region") or "—"
    nmck           = fmt_price(price)
    customer       = card.get("customer")
    contractor     = card.get("contractor_name")
    contractor_inn = card.get("contractor_inn")
    keywords       = card.get("matched_keywords") or []
    signal         = card.get("signal_score") or card.get("match_score") or 0
    commercial     = card.get("commercial_score")
    cust_src       = card.get("customer_source")
    cust_conf      = card.get("customer_confidence")
    other_cats     = card.get("other_categories") or []

    # Строка статуса
    status_parts = [icon]
    award = card.get("award_status", "")
    if award == "submission_open":
        status_parts.append("ИДУТ ТОРГИ")
    elif award == "submission_closed_waiting_award":
        status_parts.append("ОЖИДАЕТСЯ РЕЗУЛЬТАТ")
    elif award == "awarded":
        status_parts.append("РАЗЫГРАН")
    else:
        status_parts.append(status_label)
    if end_date and days is not None:
        if days > 0:
            status_parts.append(f"ПОДАЧА ДО {fmt_date(end_date)} · ОСТАЛОСЬ {days} ДН.")
        elif days == 0:
            status_parts.append("ПОДАЧА ЗАВЕРШЕНА СЕГОДНЯ")
        else:
            status_parts.append(f"ПОДАЧА ЗАВЕРШЕНА {-days} ДН. НАЗАД")
    status_str = " · ".join(status_parts)

    with st.container(border=True):

        # ── Топ-бар: бейдж + статус ──
        medal_prefix = "🥇 " if is_medal else ""
        manager_suffix = " ✓" if manager_ok else ""
        st.markdown(
            f'<div class="crm-card-topbar">'
            f'<span class="crm-badge" style="background:{bg};color:{color};">'
            f'{medal_prefix}{level_label.upper()}{manager_suffix} · {category.upper()}</span>'
            f'<span class="crm-status-chip">{status_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Прогресс стадии ──
        curr_idx = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else 0
        chips = []
        for i, (sk, sl) in enumerate(_STAGE_CHIPS):
            cls = "crm-stage-done" if i < curr_idx else ("crm-stage-curr" if i == curr_idx else "crm-stage-todo")
            chips.append(f'<span class="crm-stage-chip {cls}">{sl}</span>')
        st.markdown(f'<div class="crm-stage-bar">{"".join(chips)}</div>', unsafe_allow_html=True)

        if not is_medal:
            st.caption(f"ℹ️ {STAGE_DESCRIPTION.get(stage, stage)}")

        # ── Предупреждение о дедлайне ──
        if expired:
            st.markdown(
                f'<div class="crm-deadline-warn">'
                f'⏰ ДЕДЛАЙН ИСТЕКАЕТ · осталось {days} дн. из {req_days} необходимых. '
                f'Медаль приостановлена автоматически.'
                f'</div>',
                unsafe_allow_html=True,
            )
        elif is_medal and days is not None and 0 < days <= req_days + 2:
            st.warning(
                f"⚠️ До окончания подачи {days} дн. — порог для этого контракта: {req_days} дн."
            )

        # ── Заголовок и локация ──
        st.markdown(f"**{title}**")
        st.caption(f"📍 {region}")

        # ── ПРЕДВАРИТЕЛЬНЫЕ СИГНАЛЫ / ТОВАРНАЯ ВОЗМОЖНОСТЬ ──
        if is_medal:
            st.markdown('<div class="crm-section-label">Товарная возможность</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="crm-confirmed-box">'
                f'Категория подтверждена: <b>{category}</b><br>'
                f'Коммерческий score: <b>{commercial}/100</b> · НМЦК: <b>{nmck}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown('<div class="crm-section-label">Предварительные поисковые сигналы</div>', unsafe_allow_html=True)
            if keywords:
                kw_str = " · ".join(keywords[:8])
                st.markdown(
                    f'<div class="crm-signal-box">'
                    f'Найдены слова: <b>{kw_str}</b><br>'
                    f'<span style="color:#92400e;">'
                    f'Категория ожидает подтверждения документами · Сигнальный балл: {signal}'
                    f'</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.caption(f"Ключевые слова не определены · Сигнальный балл: {signal}")
            st.caption(f"НМЦК: {nmck}")

        # ── УЧАСТНИКИ ──
        st.markdown('<div class="crm-section-label">Участники</div>', unsafe_allow_html=True)
        cust_label = participant_source_label(cust_src, cust_conf) if cust_src else (
            "подтверждён реестром закупки" if customer else "не определён"
        )

        def _p_html(label: str, org: Optional[str], src: str, found: bool) -> str:
            cls = "crm-participant-ok" if found else "crm-participant-unkn"
            mark = "✓" if found else "·"
            return (
                f'<span class="{cls}">{mark} {label}: '
                + (f'<b>{org}</b>' if org else 'не определён')
                + f'</span><span class="crm-participant-src"> [{src}]</span> '
            )

        p_html = (
            f'<div class="crm-participants">'
            + _p_html("Заказчик", customer, cust_label, bool(customer))
            + _p_html("Балансодержатель", None, "не определён", False)
            + _p_html("Проектировщик", None, "не определён", False)
        )
        if contractor:
            p_html += (
                f'<span class="crm-participant-ok">✓ Подрядчик: <b>{contractor}</b>'
                + (f' (ИНН {contractor_inn})' if contractor_inn else '')
                + '</span><span class="crm-participant-src"> [подтверждён реестром]</span> '
            )
        else:
            p_html += '<span class="crm-participant-no">✗ Подрядчик: не выбран</span> '
        p_html += '<span class="crm-participant-unkn">· Поставщик: —</span></div>'
        st.markdown(p_html, unsafe_allow_html=True)

        # ── ПРОВЕРКА ──
        st.markdown('<div class="crm-section-label">Проверка</div>', unsafe_allow_html=True)
        doc_status = "не загружены" if stage in ("raw", "matches_found") else "загружены"
        ai_status  = (
            "в очереди" if stage in ("raw", "documents_loaded", "matches_found")
            else ("завершён" if stage in ("ranked", "manager_confirmed") else "выполняется")
        )
        evidence_cnt = card.get("evidence_count") or "—"
        if commercial is not None:
            score_line = f"Коммерческий score: <b>{commercial}/100</b>"
        else:
            score_line = f"Сигнальный балл: <b>{signal}</b> · коммерческий score не рассчитан"
        st.markdown(
            f'<div class="crm-check-row">'
            f'Документов: — · Разобрано: — · Релевантных: — · '
            f'Evidence: {evidence_cnt} · ИИ-анализ: {ai_status}<br>'
            f'Статус обработки: {STAGE_DESCRIPTION.get(stage, stage)}<br>'
            f'{score_line}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── ДРУГИЕ КАТЕГОРИИ ──
        if other_cats:
            st.markdown('<div class="crm-section-label">Другие категории объекта</div>', unsafe_allow_html=True)
            chips_html = "".join(
                f'<span class="crm-other-cat-chip">{c}</span>' for c in other_cats
            )
            st.markdown(f'<div class="crm-other-cats">{chips_html}</div>', unsafe_allow_html=True)

        # ── Футер ──
        manager_str = " · ✓ Проверено менеджером" if manager_ok else ""
        if card.get("manager_note"):
            manager_str += f' · «{card["manager_note"]}»'
        st.markdown(
            f'<div class="crm-footer-row">'
            f'Обновлено: {fmt_date(card.get("crm_updated_at"))} · '
            f'Следующая проверка: завтра 11:00{manager_str}'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.divider()

        # ── Внутренние вкладки ──
        inner_tabs = st.tabs([
            "Обзор", "Материалы", "Документы", "Evidence",
            "Закупка", "Экспертиза", "Участники", "История",
            "ИИ и обучение", "Система",
        ])

        with inner_tabs[0]:
            _tab_obzor(card, is_medal, level_label, category, keywords, signal,
                       commercial, days, req_days, end_date, nmck, color, bg, expired)
        with inner_tabs[1]:
            _tab_materialy(card, is_medal, level_label, category, keywords, nmck)
        with inner_tabs[2]:
            _tab_dokumenty(card)
        with inner_tabs[3]:
            _tab_evidence(card, is_medal)
        with inner_tabs[4]:
            _tab_zakupka(card, nmck, customer, region, days, end_date)
        with inner_tabs[5]:
            _tab_ekspertiza(card)
        with inner_tabs[6]:
            _tab_uchastniki(card, customer, contractor, contractor_inn, cust_label)
        with inner_tabs[7]:
            _tab_istoriya(card)
        with inner_tabs[8]:
            _tab_ai(card, signal, commercial, is_medal, level_label, keywords,
                    manager_ok, expired, days, req_days)
        with inner_tabs[9]:
            _tab_sistema(card)

        st.divider()

        # ── Кнопки действий ──
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        b1.button("Открыть объект",  key=f"cd_obj_{card.get('id')}",      use_container_width=True)
        b2.button("☆ Следить",       key=f"cd_watch_{card.get('id')}",    use_container_width=True)
        b3.button("В работу",        key=f"cd_work_{card.get('id')}",     use_container_width=True, type="primary")
        if b4.button("↻ Пересчитать", key=f"cd_recalc_{card.get('id')}", use_container_width=True):
            from src.services.crm_profile_service import queue_reenrich
            ok = queue_reenrich(card.get("id", 0))
            st.toast("Добавлено в очередь" if ok else "Уже в очереди")
        b5.button("⬇ Скачать",       key=f"cd_dl_{card.get('id')}",      use_container_width=True)
        b6.button("→ Передать",      key=f"cd_fwd_{card.get('id')}",     use_container_width=True)


# ─── Вкладки ───────────────────────────────────────────────────────────────────

def _tab_obzor(card, is_medal, level, category, keywords, signal, commercial,
               days, req_days, end_date, nmck, color, bg, expired):
    col1, col2, col3 = st.columns(3)
    col1.metric("НМЦК", nmck)
    if is_medal and commercial is not None:
        col2.metric("Коммерческий score", f"{commercial}/100")
    else:
        col2.metric("Сигнальный балл", str(signal))
    col3.metric("Подача до", fmt_date(end_date))

    if card.get("delivery_end_date"):
        st.caption(f"Срок исполнения: {fmt_date(card.get('delivery_end_date'))}")
    if card.get("tender_link"):
        st.markdown(f"[🔗 Ссылка на торги]({card['tender_link']})")

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Следующее действие**")
        if expired:
            st.error(f"Дедлайн: осталось {days} дн. из {req_days} требуемых. Решение немедленно.")
        elif days is not None and days > 0:
            st.info(f"До окончания подачи {days} дней. Проверить категорию и выйти на заказчика.")
        elif days is not None and days <= 0:
            st.info("Торги завершены. Ожидать публикации результатов.")
    with col_b:
        st.markdown("**Риски**")
        risks = []
        if not is_medal:
            risks.append("⚠️ Медаль не присвоена — категория не подтверждена")
        if expired:
            risks.append(f"🔴 Критический дедлайн: {days} < {req_days} дн.")
        elif days is not None and 0 < days <= req_days + 2:
            risks.append(f"⚠️ Приближается порог: {days} дн., минимум {req_days}")
        if not card.get("customer"):
            risks.append("· Заказчик не определён")
        if risks:
            st.warning("\n".join(risks))
        else:
            st.success("Существенных рисков не выявлено")

    if is_medal:
        st.markdown("---")
        st.markdown("**Товарная возможность**")
        with st.container(border=True):
            st.markdown(
                f'<span style="background:{bg};color:{color};padding:2px 12px;'
                f'border-radius:999px;font-size:11px;font-weight:700;">{level.upper()}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**{category}**")
            if keywords:
                st.caption("Продукция: " + " · ".join(keywords[:5]))
            st.caption(f"Коммерческий score: {commercial}/100 · НМЦК: {nmck}")
    else:
        st.markdown("---")
        st.info(
            "Товарная возможность появится после разбора документов и ИИ-анализа.\n\n"
            + (f"Предварительный сигнал: **{', '.join(keywords[:4])}**" if keywords else "Сигналы не определены")
        )


def _tab_materialy(card, is_medal, level, category, keywords, nmck):
    if not is_medal:
        st.warning("Материалы и объёмы доступны только после ИИ-анализа (стадия AI_VERIFIED+).")
        st.caption(f"Предварительный сигнал: {', '.join(keywords) if keywords else '—'}")
        st.caption(f"НМЦК: {nmck}")
        return

    import pandas as pd
    df = pd.DataFrame([{
        "Уровень": level, "Категория": category,
        "Продукция": ", ".join(keywords[:3]) if keywords else "—",
        "Объём": "—", "Процентиль": "—",
    }])
    event = st.dataframe(df, use_container_width=True, hide_index=True,
                         on_select="rerun", selection_mode="single-row")
    selected = event.selection.rows if hasattr(event, "selection") else []
    if selected:
        st.markdown("---")
        b1, b2, b3, b4 = st.columns(4)
        b1.button("Evidence",         key=f"mat_ev_{card.get('id')}",  use_container_width=True)
        b2.button("Документы",        key=f"mat_doc_{card.get('id')}", use_container_width=True)
        b3.button("↻ Пересчитать",    key=f"mat_rc_{card.get('id')}", use_container_width=True)
        b4.button("Изменить уровень", key=f"mat_lv_{card.get('id')}", use_container_width=True)


def _tab_dokumenty(card):
    if card.get("tender_link"):
        st.markdown(f"[🔗 Открыть источник закупки]({card['tender_link']})")
    st.info("Документы появятся после запуска парсера для этой закупки")
    import pandas as pd
    df = pd.DataFrame([
        {"Файл": "Техническое задание",   "Тип": "ТЗ",     "Статус": "не загружен"},
        {"Файл": "Ведомость объёмов",      "Тип": "Смета",  "Статус": "не загружен"},
        {"Файл": "Проектная документация", "Тип": "Архив",  "Статус": "не загружен"},
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)
    b1, b2, b3 = st.columns(3)
    b1.button("⬇ Скачать всё",      key=f"doc_dl_{card.get('id')}", use_container_width=True, disabled=True)
    b2.button("↻ Обработать заново", key=f"doc_re_{card.get('id')}", use_container_width=True)
    b3.button("⚠ Проверить ошибки", key=f"doc_er_{card.get('id')}", use_container_width=True, disabled=True)


def _tab_evidence(card, is_medal):
    if not is_medal:
        st.warning("Evidence появится после ИИ-анализа документов (стадия AI_VERIFIED+).")
        st.caption(
            "Evidence — фрагменты из документов (таблицы смет, спецификации), "
            "подтверждающие объём материала и категорию."
        )
        return
    st.info("Evidence загружается из базы данных анализа")


def _tab_zakupka(card, nmck, customer, region, days, end_date):
    src  = card.get("source_table", "")
    law  = "44-ФЗ" if "44" in src else ("223-ФЗ" if "223" in src else "—")
    link = card.get("tender_link")
    days_str = (f"{days} дн." if days is not None and days >= 0 else "подача завершена")

    st.markdown(f"**Номер контракта:** {card.get('contract_number') or '—'}")
    st.markdown(f"**Заказчик:** {customer or '—'}")
    st.markdown(f"**Регион поставки:** {region}")
    st.markdown(f"**НМЦК:** {nmck}")
    st.markdown(f"**Закон:** {law}")
    st.markdown(f"**Публикация:** {fmt_date(card.get('start_date'))}")
    st.markdown(f"**Окончание подачи:** {fmt_date(end_date)} · Осталось: {days_str}")
    st.markdown(f"**ОКПД2:** {card.get('okpd_code') or '—'}")
    st.markdown(f"**Статус:** {card.get('award_status') or '—'}")

    st.markdown("---")
    b1, b2, b3 = st.columns(3)
    if link:
        b1.link_button("🔗 Источник", link, use_container_width=True)
    else:
        b1.button("🔗 Источник", key=f"zak_src_{card.get('id')}", use_container_width=True, disabled=True)
    b2.button("↻ Обновить",            key=f"zak_upd_{card.get('id')}", use_container_width=True)
    b3.button("Проверить разыгранные", key=f"zak_awd_{card.get('id')}", use_container_width=True)


def _tab_ekspertiza(card):
    st.info("Экспертиза привязывается к объекту через ИИ-матчинг. Данных пока нет.")
    st.markdown("**Положительное заключение:** не найдено")
    st.markdown("**Дата:** —")
    st.markdown("**Реестровый номер:** —")
    st.markdown("**Совпадение:** —")
    st.markdown("**Проектировщик:** —")
    b1, b2, b3 = st.columns(3)
    b1.button("Открыть заключение", key=f"eks_o_{card.get('id')}", use_container_width=True, disabled=True)
    b2.button("Подтвердить связь",  key=f"eks_c_{card.get('id')}", use_container_width=True, disabled=True)
    b3.button("Отклонить связь",    key=f"eks_r_{card.get('id')}", use_container_width=True, disabled=True)


def _tab_uchastniki(card, customer, contractor, contractor_inn, cust_label):
    st.markdown(f"**Заказчик:** {customer or '—'}")
    st.caption(f"Источник: {cust_label}")
    st.markdown("**Балансодержатель:** —")
    st.caption("Источник: не определён")
    st.markdown("**Проектировщик:** —")
    st.caption("Источник: не определён")
    if contractor:
        st.markdown(f"**Подрядчик:** {contractor}" + (f" (ИНН {contractor_inn})" if contractor_inn else ""))
        st.caption("Источник: подтверждён реестром закупки")
    else:
        st.markdown("**Подрядчик:** ещё не выбран")
    st.markdown("**Поставщик:** —")
    st.caption("Источник: не определён")


def _tab_istoriya(card):
    history = []
    for val, label in [
        (card.get("crm_created_at"), "Закупка добавлена в CRM (keyword match)"),
        (card.get("start_date"),     "Публикация торгов"),
        (card.get("crm_updated_at"), "Данные обновлены"),
        (card.get("end_date"),       "Ожидается завершение подачи"),
    ]:
        if val:
            history.append((fmt_date(val), label))

    if card.get("award_status") == "submission_closed_waiting_award":
        history.append((fmt_date(card.get("end_date")), "Подача завершена · ожидается результат"))
    elif card.get("award_status") == "awarded":
        history.append((fmt_date(card.get("contract_signed_at")), "Подрядчик выбран · контракт подписан"))

    if not history:
        st.info("История событий пуста")
        return

    for dt, event in sorted(set(history), key=lambda x: x[0] or ""):
        col1, col2 = st.columns([1, 3])
        col1.caption(dt)
        col2.markdown(event)

    st.caption("Цикл: Публикация → Идут торги → Подача завершена → Разыгранные")


def _tab_ai(card, signal, commercial, is_medal, level, keywords, manager_ok,
            expired, days, req_days):
    category = card.get("crm_category") or "—"

    st.markdown("**Классификация**")
    st.markdown(f"Метод: keyword matcher · Категория: {category}")
    st.markdown(f"Сигнальный балл: **{signal}** (из keyword match)")
    if expired:
        st.warning(f"Медаль приостановлена автоматически: дедлайн — осталось {days} дн. из {req_days}.")
    elif is_medal and commercial is not None:
        st.markdown(f"Коммерческий score: **{commercial}/100** · **{level.upper()}**")
    else:
        st.markdown("Коммерческий score: ещё не рассчитан")

    if is_medal and commercial is not None and not expired:
        st.markdown("---")
        st.markdown("**Детализация score**")
        deadline_score = 10 if not expired else 0
        score_rows = [
            ("Keywords match",     min(signal, 15), 15),
            ("Evidence",           0,  15),
            ("Quantity",           0,  15),
            ("Percentile",         0,  15),
            ("Participants",       0,  15),
            ("Stage",              0,  10),
            ("Deadline (динамик.)",deadline_score, 10),
            ("Completeness",       0,  10),
            ("Freshness",          0,   5),
            ("Commercial window",  0,  10),
        ]
        for label, val, max_val in score_rows:
            c1, c2 = st.columns([4, 1])
            c1.markdown(label)
            c2.markdown(f"**{val}/{max_val}**")
        total = sum(v for _, v, _ in score_rows)
        st.markdown(f"**Итог: {total}/100 · {level.upper()}**")
    else:
        st.info("ИИ-анализ ещё не выполнен. Score рассчитается после разбора документов.")

    st.markdown("---")
    st.text_area("Комментарий для модели",
                 placeholder="Уточнение для улучшения классификации...",
                 key=f"ai_note_{card.get('id')}")
    b1, b2, b3, b4 = st.columns(4)
    b1.button("↻ Пересчитать", key=f"ai_rc_{card.get('id')}",  use_container_width=True)
    if b2.button("✓ Подтвердить" + (" (уже)" if manager_ok else ""),
                 key=f"ai_cf_{card.get('id')}", use_container_width=True, type="primary"):
        _confirm_manager(card.get("id"))
    b3.button("✎ Исправить",   key=f"ai_fx_{card.get('id')}", use_container_width=True)
    b4.button("✗ Отклонить",   key=f"ai_rj_{card.get('id')}", use_container_width=True)


def _confirm_manager(procurement_id):
    try:
        import os, psycopg2
        PG = dict(
            host=os.environ.get("CRM_DB_HOST", "10.8.0.7"),
            port=int(os.environ.get("CRM_DB_PORT", 5432)),
            user=os.environ.get("CRM_DB_USER", "postgres"),
            password=os.environ.get("CRM_DB_PASSWORD", "0IFz3_"),
            dbname="crm",
        )
        conn = psycopg2.connect(**PG)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE crm_procurements
                SET processing_stage = 'manager_confirmed',
                    manager_confirmed_at = now(),
                    crm_updated_at = now()
                WHERE id = %s AND processing_stage IN ('ranked','manager_confirmed')
            """, (procurement_id,))
        conn.close()
        st.toast("✓ Отмечено менеджером")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Ошибка: {e}")


def _tab_sistema(card):
    st.markdown("**Системная информация**")
    stage = card.get("processing_stage", "—")
    fields = [
        ("ID в CRM",           card.get("id")),
        ("Стадия обработки",   stage),
        ("Описание стадии",    STAGE_DESCRIPTION.get(stage, "—")),
        ("Источник",           card.get("source_table")),
        ("ID в источнике",     card.get("source_id")),
        ("Номер контракта",    card.get("contract_number")),
        ("Сигнальный балл",    card.get("signal_score") or card.get("match_score")),
        ("Коммерческий score", card.get("commercial_score") or "не рассчитан"),
        ("Профиль ID",         card.get("crm_profile_id")),
        ("Ключевые слова",     ", ".join(card.get("matched_keywords") or [])),
        ("Подтверждён менедж.",card.get("manager_confirmed_at") or "нет"),
        ("Обновлено",          fmt_date(card.get("crm_updated_at"))),
    ]
    for label, val in fields:
        c1, c2 = st.columns([2, 3])
        c1.caption(label)
        c2.code(str(val or "—"), language=None)

    st.markdown("---")
    b1, b2, b3, b4 = st.columns(4)
    b1.button("Открыть JSON",  key=f"sys_js_{card.get('id')}", use_container_width=True)
    b2.button("SQL связи",     key=f"sys_sq_{card.get('id')}", use_container_width=True)
    b3.button("Логи",          key=f"sys_lg_{card.get('id')}", use_container_width=True)
    if b4.button("↻ В очередь", key=f"sys_q_{card.get('id')}", use_container_width=True):
        from src.services.crm_profile_service import queue_reenrich
        ok = queue_reenrich(card.get("id", 0))
        st.toast("Добавлено в очередь" if ok else "Уже в очереди")
