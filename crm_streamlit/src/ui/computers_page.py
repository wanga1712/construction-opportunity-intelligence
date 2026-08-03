"""Компьютеры / ИТ: отбор по ОКПД-2 26.20*, карточки для поставщика из ТЗ."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

from src.services.computers_service import (
    computer_okpd_caption,
    load_computer_items,
    load_computer_cards,
    load_computer_tenders,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def render_computers_page(service) -> None:
    st.title("Компьютеры / ИТ")
    st.caption(computer_okpd_caption())
    st.info(
        "Категория объекта (школа/дорога) здесь не важна. "
        "В контур попадаем **только по ОКПД-2 26.20*** из `collection_codes_okpd`. "
        "Демон скачивает ТЗ и собирает карточку для запроса поставщику."
    )

    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
    with c1:
        region_query = st.text_input("Регион / название", key="computers_region")
    with c2:
        only_open = st.toggle("Только неразыгранные", value=False)
    with c3:
        # По умолчанию показываем 50, чтобы страница открывалась быстрее.
        limit = st.selectbox("Лимит", [50, 100, 200, 400], index=0, key="computers_limit")
    with c4:
        st.write("")
        refresh = st.button("↻ Обновить", use_container_width=True)
    item_category = st.selectbox(
        "Категория позиции",
        ["Все", "notebook", "desktop", "monoblock", "server", "mfu", "mouse", "keyboard", "monitor", "ups", "printer", "network", "software", "other"],
        index=0,
        key="computers_item_category",
    )

    st.markdown("### Демон ТЗ → карточка поставщику")
    st.caption(
        "Параллельно materials-демону. Парсинг PDF/DOCX/DOC/XLSX — движки из "
        "`/opt/tender_documents_research`. Отбор: ОКПД **26.20*** + только открытые "
        "реестры (не awarded). Если EIS на 7-м ещё догоняет дату — список может быть пуст."
    )
    d1, d2, d3 = st.columns([1, 1, 2])
    with d1:
        run_once = st.button("▶ Прогнать пакет сейчас", type="primary", use_container_width=True)
    with d2:
        batch_limit = st.number_input("Размер пакета", min_value=1, max_value=50, value=15)
    with d3:
        st.caption(
            "`crm-computer-tz-loop.service` (постоянный контур) · "
            "`python scripts/computer_tz_daemon.py --once --only-open --strict-tz-only`"
        )

    if run_once:
        with st.spinner("Демон: скачивание ТЗ и разбор моделью…"):
            try:
                cmd = [
                    sys.executable,
                    str(_PROJECT_ROOT / "scripts" / "computer_tz_daemon.py"),
                    "--once",
                    "--only-open",
                    "--limit",
                    str(int(batch_limit)),
                ]
                if not only_open:
                    cmd = [
                        sys.executable,
                        str(_PROJECT_ROOT / "scripts" / "computer_tz_daemon.py"),
                        "--once",
                        "--include-awarded",
                        "--limit",
                        str(int(batch_limit)),
                    ]
                proc = subprocess.run(
                    cmd,
                    cwd=str(_PROJECT_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=1200,
                )
                if proc.returncode == 0:
                    st.success("Пакет завершён")
                else:
                    st.error(f"exit {proc.returncode}")
                if proc.stdout:
                    st.code(proc.stdout[-3000:])
                if proc.stderr:
                    st.code(proc.stderr[-2000:])
            except Exception as exc:
                st.error(str(exc))

    if not service.tender_db:
        st.error("Tender DB недоступна")
        return

    try:
        rows = load_computer_tenders(
            service.tender_db,
            limit=int(limit),
            only_open=only_open,
            region_query=region_query or "",
        )
        if only_open and not rows:
            rows = load_computer_tenders(
                service.tender_db,
                limit=int(limit),
                only_open=False,
                region_query=region_query or "",
            )
            if rows:
                st.warning(
                    "По неразыгранным сейчас пусто — показаны последние закупки "
                    "включая разыгранные, чтобы не терять карточки."
                )
    except Exception as exc:
        st.error(f"Не удалось загрузить закупки по ОКПД: {exc}")
        return

    if refresh:
        st.rerun()

    cards = {}
    items_map = {}
    if service.crm_db and rows:
        try:
            cards = load_computer_cards(service.crm_db, [r.key for r in rows])
            items_map = load_computer_items(service.crm_db, [r.key for r in rows])
        except Exception as exc:
            st.warning(f"Карточки ТЗ: {exc}")

    if item_category != "Все":
        rows = [
            r for r in rows
            if any((x.get("category") or "").lower() == item_category for x in (items_map.get(r.key) or []))
        ]

    ready_n = sum(1 for r in rows if (cards.get(r.key) or {}).get("status") in ("ready", "partial"))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("По ОКПД 26.20*", len(rows))
    m2.metric("С карточкой ТЗ", ready_n)
    m3.metric("С ссылками на доки", sum(1 for r in rows if r.doc_count > 0))
    m4.metric("Без доков", sum(1 for r in rows if r.doc_count <= 0))

    if not rows:
        st.warning("Нет закупок с ОКПД 26.20* по фильтрам.")
        return

    for row in rows:
        card_row = cards.get(row.key) or {}
        status = card_row.get("status") or "—"
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(f"**{row.name}**")
                st.caption(
                    " · ".join(
                        filter(
                            None,
                            [
                                row.region,
                                row.status,
                                f"ОКПД {row.okpd_code}",
                                row.okpd_name,
                                f"НМЦК {row.initial_price:,.0f}" if row.initial_price else None,
                            ],
                        )
                    )
                )
                st.caption(
                    f"Заказчик: {row.customer_name or '—'} · "
                    f"доков: {row.doc_count} · карточка: {status}"
                )
            with right:
                if row.contract_number:
                    st.caption(row.contract_number)

            supplier = card_row.get("supplier_card") or {}
            if isinstance(supplier, str):
                try:
                    supplier = json.loads(supplier)
                except Exception:
                    supplier = {}
            if supplier:
                st.markdown(
                    f"**Решение:** {supplier.get('decision', '—')} · "
                    f"**Тип:** {supplier.get('equipment_type', '—')} · "
                    f"**Приоритет:** {supplier.get('priority', '—')}"
                )
                if supplier.get("recommended_config"):
                    st.write(f"Конфиг: {supplier.get('recommended_config')}")
                if supplier.get("supplier_request"):
                    with st.expander("Запрос поставщику", expanded=False):
                        st.write(supplier.get("supplier_request"))
                if supplier.get("must_have"):
                    must_have = [str(x) for x in (supplier.get("must_have") or [])[:12]]
                    st.caption("Must-have: " + ", ".join(must_have))
                if supplier.get("red_flags"):
                    red_flags = [str(x) for x in (supplier.get("red_flags") or [])[:8]]
                    st.warning("Флаги: " + "; ".join(red_flags))
                row_items = items_map.get(row.key) or []
                if row_items:
                    st.caption(
                        "Позиции: " + "; ".join(
                            f"{it.get('category')}: {it.get('qty') or '—'} {it.get('unit') or ''}".strip()
                            for it in row_items[:8]
                        )
                    )
            elif card_row.get("error_message"):
                st.error(card_row.get("error_message"))
