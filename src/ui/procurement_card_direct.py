"""Вкладки карточки закупки для режима «Прямая поставка».

Разделы: Смета / Товар и поставка / Участник / Обеспечение / Дополнительно.
Каждая запись имеет один основной раздел, источник и полный текст (без потерь).
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src.services.direct_estimate_table import build_estimate
from src.services.direct_requirement_classifier import PRODUCT_GROUPS, classify

SOURCE_LABELS = {
    "spec": "Смета",
    "tech": "Технические параметры",
    "requirements": "Таблица требований",
    "terms": "Срок поставки",
    "sections.participant": "Документация · участник",
    "sections.product": "Документация · товар",
    "sections.participation": "Документация · участие",
    "sections.security": "Документация · обеспечение",
    "sections.national": "Документация · нацрежим",
}
PRICE_SOURCE_LABELS = {
    "document": "из документа",
    "computed": "расчёт: сумма ÷ кол-во",
    "nmck_share": "ориентировочно из НМЦК",
}
_PAGE_LIMIT = 40


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _money(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    text = "{:,.2f}".format(number).replace(",", " ").replace(".", ",")
    return "%s ₽" % text


def _table(columns: List[str], rows: List[List[str]]) -> str:
    head = "".join("<th>%s</th>" % _esc(c) for c in columns)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in row) for row in rows)
    return ('<div class="pc-scroll"><table class="pc-table"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>' % (head, body))


def build_state(extraction: Dict[str, Any], dossier: Dict[str, Any]) -> Dict[str, Any]:
    """Разложить извлечённые данные по разделам и собрать сметную таблицу."""
    classified = classify(extraction, dossier)
    nmck = (dossier.get("money_and_dates") or {}).get("initial_price")
    estimate = build_estimate(extraction, nmck=nmck)
    return {"classified": classified, "estimate": estimate, "extraction": extraction,
            "dossier": dossier, "nmck": nmck}


def tab_titles(state: Dict[str, Any]) -> List[str]:
    """Заголовки вкладок с реальными количествами отображаемых записей."""
    counts = state["classified"]["counts"]
    estimate_count = len(state["estimate"]["rows"])
    return [
        "Смета (%d)" % estimate_count,
        "Товар и поставка (%d)" % (counts["product"] + counts["delivery"] + counts["national"]),
        "Требования к участнику (%d)" % counts["participant"],
        "Обеспечение (%d)" % counts["security"],
        "Дополнительно (%d)" % counts["additional"],
    ]


def _records(state: Dict[str, Any], section: str) -> List[Dict[str, Any]]:
    return state["classified"]["buckets"].get(section) or []


def _filtered(records: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle:
        return records
    return [r for r in records
            if needle in str(r.get("text") or "").lower()
            or needle in str(r.get("param") or "").lower()]


def _source_line(record: Dict[str, Any]) -> str:
    source = SOURCE_LABELS.get(str(record.get("source")), str(record.get("source") or ""))
    file_name = record.get("source_file")
    mandatory = record.get("mandatory")
    chips = ['<span class="pc-chip">%s</span>' % _esc(source)]
    if file_name:
        chips.append('<span class="pc-chip">%s</span>' % _esc(file_name))
    if mandatory is True:
        chips.append('<span class="pc-chip bad">обязательное</span>')
    elif mandatory is False:
        chips.append('<span class="pc-chip ok">дополнительное</span>')
    return " ".join(chips)


def _record_block(record: Dict[str, Any]) -> None:
    title = str(record.get("param") or record.get("text") or "")[:120]
    variants = record.get("variants") or []
    if record.get("deadline"):
        title = "Срок поставки: не позднее %s" % record["deadline"]
    elif record.get("duration_value"):
        title = "Срок поставки: в течение %s %s" % (record["duration_value"],
                                                   record.get("duration_unit") or "")
    with st.expander(title or "(без названия)", expanded=False):
        st.markdown('<div class="pc-muted">%s</div>' % _source_line(record),
                    unsafe_allow_html=True)
        st.markdown(_esc(record.get("text") or record.get("param") or ""),
                    unsafe_allow_html=True)
        sources = record.get("sources") or []
        if len(sources) > 1:
            st.markdown('<div class="pc-note">Та же формулировка встречается в документах: %s'
                        '</div>' % _esc(", ".join(str(s) for s in sources if s)),
                        unsafe_allow_html=True)
        if variants:
            st.markdown('<div class="pc-muted">Другие формулировки этого же срока (%d):</div>'
                        % len(variants), unsafe_allow_html=True)
            for variant in variants:
                st.markdown("- %s" % _esc(variant), unsafe_allow_html=True)


def _record_list(state: Dict[str, Any], section: str, hint: str,
                 key_prefix: str, label: str) -> None:
    records = _records(state, section)
    if not records:
        st.info("В этом разделе пока нет извлечённых данных.")
        return
    query = st.text_input("Поиск по разделу", key="%s_search" % key_prefix,
                          placeholder=hint, label_visibility="collapsed")
    found = _filtered(records, query)
    show_all = st.checkbox("Показать все записи (%d)" % len(found), key="%s_all" % key_prefix,
                           value=False)
    limit = len(found) if show_all else _PAGE_LIMIT
    st.markdown('<div class="pc-muted">Показано %d из %d · поиск ищет по полному тексту записи</div>'
                % (min(limit, len(found)), len(found)), unsafe_allow_html=True)
    st.markdown('<div class="pc-sect">%s</div>' % _esc(label), unsafe_allow_html=True)
    for record in found[:limit]:
        _record_block(record)


def _security_facts(records: List[Dict[str, Any]]) -> Tuple[List[int], List[float]]:
    money: List[int] = []
    percent: List[float] = []
    for record in records:
        text = str(record.get("text") or "")
        for match in re.finditer(r"(\d[\d\s\u00a0]{3,})(?:\s*\([^)]*\))?\s*руб", text, re.I):
            value = int(re.sub(r"\D", "", match.group(1)))
            if value >= 1000:
                money.append(value)
        for match in re.finditer(r"(\d{1,2}(?:[.,]\d+)?)\s*%", text):
            percent.append(float(match.group(1).replace(",", ".")))
    return sorted(set(money), reverse=True), sorted(set(percent), reverse=True)


def render_security(state: Dict[str, Any]) -> None:
    records = _records(state, "security")
    money, percent = _security_facts(records)
    if money or percent:
        cols = st.columns(max(1, min(4, len(money) + len(percent))))
        index = 0
        for value in money[:3]:
            with cols[index % len(cols)]:
                st.markdown('<div class="pc-card"><div class="pc-muted">Сумма обеспечения '
                            '(из документов)</div><div class="pc-badge">%s</div></div>'
                            % _money(value), unsafe_allow_html=True)
            index += 1
        for value in percent[:2]:
            with cols[index % len(cols)]:
                st.markdown('<div class="pc-card"><div class="pc-muted">Процент (из документов)'
                            '</div><div class="pc-badge">%s %%</div></div>'
                            % str(value).replace(".", ","), unsafe_allow_html=True)
            index += 1
        st.markdown('<div class="pc-note">Значения взяты из текста документов; суммы и проценты '
                    'не пересчитываются друг из друга.</div>', unsafe_allow_html=True)
    _record_list(state, "security", "например: независимая гарантия, обеспечительный платёж",
                 "sec", "Детальные требования по обеспечению")


def render_participant(state: Dict[str, Any]) -> None:
    _record_list(state, "participant", "например: лицензия, СРО, опыт, РНП",
                 "part", "Требования к участнику")


def render_additional(state: Dict[str, Any]) -> None:
    st.markdown('<div class="pc-muted">Особые условия, ответственность, оплата и всё, что не '
                'относится к товару, поставке, участнику и обеспечению.</div>',
                unsafe_allow_html=True)
    _record_list(state, "additional", "например: штраф, оплата, расторжение",
                 "add", "Дополнительные условия")
    unclassified = _records(state, "unclassified")
    if unclassified:
        st.markdown('<div class="pc-sect">Не классифицировано (%d)</div>' % len(unclassified),
                    unsafe_allow_html=True)
        st.markdown('<div class="pc-note">Требования, для которых правило не дало уверенного '
                    'раздела. Оставлены видимыми намеренно.</div>', unsafe_allow_html=True)
        for record in unclassified[:_PAGE_LIMIT]:
            _record_block(record)


def render_product_delivery(state: Dict[str, Any]) -> None:
    product = _records(state, "product")
    delivery = _records(state, "delivery")
    query = st.text_input("Поиск по требованиям", key="pd_search",
                          placeholder="например: оперативная память, монтаж, гарантия")
    st.markdown('<div class="pc-sect">1. Требования к товару</div>', unsafe_allow_html=True)
    if not product:
        st.info("Технические требования в документах не найдены.")
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for record in _filtered(product, query):
        by_group.setdefault(record.get("group") or "other", []).append(record)
    for key, title, _markers in PRODUCT_GROUPS:
        items = by_group.get(key)
        if not items:
            continue
        with st.expander("%s (%d)" % (title, len(items)), expanded=(key == "processor")):
            rows = []
            for record in items[:_PAGE_LIMIT]:
                rows.append([_esc(record.get("param") or ""),
                             _esc(record.get("value") or ""),
                             _esc(record.get("unit") or ""),
                             _esc(SOURCE_LABELS.get(str(record.get("source")), ""))
                             + (" · " + _esc(record.get("source_file"))
                                if record.get("source_file") else "")])
            st.markdown(_table(["Параметр", "Значение", "Ед. изм.", "Источник"], rows),
                        unsafe_allow_html=True)
            if len(items) > _PAGE_LIMIT:
                st.markdown('<div class="pc-note">Показано %d из %d — уточните поиск.</div>'
                            % (_PAGE_LIMIT, len(items)), unsafe_allow_html=True)
    st.markdown('<div class="pc-sect">2. Требования к поставке</div>', unsafe_allow_html=True)
    if not delivery:
        st.info("Условия поставки в документах не найдены.")
    else:
        for record in _filtered(delivery, query):
            _record_block(record)


def _totals_block(state: Dict[str, Any]) -> None:
    totals = state["estimate"]["totals"]
    cells = [("Позиций", str(totals["positions"]), "")]
    if totals.get("total_units") is not None:
        cells.append(("Единиц", str(totals["total_units"]).rstrip("0").rstrip("."),
                      totals.get("unit") or ""))
    if totals.get("total_sum") is not None:
        cells.append(("Сумма известных позиций", _money(totals["total_sum"]),
                      "документальные суммы" if totals.get("complete") else "часть позиций"))
    cells.append(("НМЦК", _money(totals.get("nmck")), "реестр"))
    if totals.get("nmck_diff") is not None:
        cells.append(("Расхождение с НМЦК", _money(totals["nmck_diff"]), "только по полным данным"))
    html_cells = "".join(
        '<div class="pc-tile"><div class="cap">%s</div><b>%s</b><span class="sub">%s</span></div>'
        % (_esc(cap), _esc(value), _esc(sub)) for cap, value, sub in cells)
    st.markdown('<div class="pc-tiles">%s</div>' % html_cells, unsafe_allow_html=True)


def render_estimate(state: Dict[str, Any], procurement_id: int) -> None:
    rows = state["estimate"]["rows"]
    if not rows:
        st.info("Смета не распознана: в документах нет таблицы состава закупки. "
                "Сырые строки сметы остаются в данных закупки.")
    else:
        table_rows = []
        for row in rows:
            price = row.get("unit_price")
            price_cell = _money(price) if price else "—"
            if price and row.get("unit_price_source") in (PRICE_SOURCE_LABELS):
                price_cell += ' <span class="pc-note">(%s)</span>' % _esc(
                    PRICE_SOURCE_LABELS[row["unit_price_source"]])
            table_rows.append([
                str(row["index"]), _esc(row["name"]), _esc(row.get("okpd") or "—"),
                _esc(row.get("registry") or "—"),
                ("%g" % row["qty"]) if row.get("qty") else "—",
                _esc(row.get("unit") or "—"), price_cell,
                _money(row.get("sum")) if row.get("sum") else "—",
                _esc(row.get("source_file") or ""),
            ])
        st.markdown(_table(["№", "Наименование", "ОКПД2", "Реестр РЭП", "Кол-во",
                            "Ед. изм.", "Цена за ед.", "Сумма", "Источник"], table_rows),
                    unsafe_allow_html=True)
        _totals_block(state)
    notes = list(state["estimate"].get("skipped") or []) + \
        ["не показана колонка — %s" % c for c in (state["estimate"].get("columns_not_shown") or [])]
    if notes:
        with st.expander("Что не попало в таблицу и почему (%d)" % len(notes), expanded=False):
            for note in notes:
                st.markdown("- %s" % _esc(note), unsafe_allow_html=True)
    _render_tkp(state, procurement_id)


def _render_tkp(state: Dict[str, Any], procurement_id: int) -> None:
    from src.services.direct_document_extractor import build_tkp_request

    st.markdown('<div class="pc-sect">Запрос ТКП поставщику</div>', unsafe_allow_html=True)
    st.markdown('<div class="pc-note">Собирается из структурированных данных: позиции сметы, '
                'технические требования, условия поставки, гарантия и сертификаты. Требования '
                'к участнику и обеспечение в запрос поставщику не включаются.</div>',
                unsafe_allow_html=True)
    key = "tkp_text_%s" % procurement_id
    if st.button("Сформировать запрос ТКП", key="tkp_btn_%s" % procurement_id):
        delivery_texts = [r.get("text") for r in _records(state, "delivery")]
        st.session_state[key] = build_tkp_request(
            state["extraction"], state["dossier"],
            delivery_lines=delivery_texts,
            estimate_rows=state["estimate"]["rows"])
    text = st.session_state.get(key)
    if text:
        st.code(text, language=None)
        st.download_button("Скачать файлом .txt", data=text.encode("utf-8"),
                           file_name="tkp_%s.txt" % procurement_id, mime="text/plain",
                           key="tkp_dl_%s" % procurement_id)
