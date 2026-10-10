"""Mode-aware analytics table workspace (V1.2: navigable grid).

1C-like navigable table: left navigation (mode -> category -> subcategory ->
object -> region), free-text search, dense manager grid, deadline column and the
temporal submission-window bar. Read-only; inline editing is a later phase.
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.ui.components.rich_table import rich_table
from src.services.procurement_card_dossier_service import load_procurement_dossier
from src.services.analytics_table_workspace_service import (
    ALL_MODES,
    COLUMN_LABELS,
    DESIGN,
    DIRECT_SUPPLY,
    EMBEDDED_MATERIAL,
    OBJECT,
    MODE_LABELS,
    bucket_color,
    bucket_label,
    load_filter_options,
    load_workspace_rows,
)
from src.services.commercial_routing_v3.submission_window_temporal import (
    EXPIRED,
    TEMPORAL_UNKNOWN,
    format_seconds,
)

#: Типы закупок в фильтре: режимы не пересекаются, «в составе работ» — отдельный тип
#: (раньше он был спрятан внутри «Объект (проект)» вместе с проектными закупками).
_TYPE_OPTIONS = [ALL_MODES, DIRECT_SUPPLY, EMBEDDED_MATERIAL, DESIGN]
_TYPE_LABELS = {
    ALL_MODES: "Все",
    DIRECT_SUPPLY: "Прямая поставка",
    EMBEDDED_MATERIAL: "В составе работ",
    DESIGN: "Проект",
}
_ALL = "__all__"

_CSS = """
<style>
.tw-table{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px;
  font-variant-numeric:tabular-nums;background:#fff}
.tw-table thead th{position:sticky;top:0;z-index:2;background:#eef1f5;color:#3d4757;
  font-weight:600;text-align:left;padding:6px 8px;border-bottom:2px solid #cfd6df;
  white-space:nowrap}
.tw-table tbody td{padding:6px 8px;border-bottom:1px solid #eaeef3;vertical-align:top}
.tw-table tbody tr:nth-child(even){background:#fafbfc}
.tw-table tbody tr:hover{background:#eef6ff}
.tw-medal{font-weight:700;font-size:14px}
.tw-small{color:#7c848f;font-size:11px;line-height:1.25}
.tw-title{font-weight:600;color:#1f2733}
.tw-bar{position:relative;height:11px;border-radius:3px;background:#e6e9ee;
  overflow:hidden;margin:3px 0}
.tw-fill{height:100%}
.tw-mark{position:absolute;top:-2px;width:2px;height:15px;background:#39424e;opacity:.6}
.tw-pct{font-size:11px;color:#39424e;font-weight:600}
.tw-wrap{overflow:auto;max-height:74vh;border:1px solid #dfe4ea;border-radius:6px}
.tw-group{border:1px solid #dfe4ea;border-radius:10px;background:#fff;margin-bottom:8px}
.tw-gwin{padding:0 12px 8px 12px}
.tw-group>summary{cursor:pointer;padding:8px 12px;list-style:none;
  display:grid;grid-template-columns:auto minmax(0,1fr) auto 210px;gap:12px;align-items:center}
.tw-rb{min-width:0}
.tw-rb .tw-bar{width:200px;height:6px;margin:0 0 3px 0}
.tw-rb .tw-pct{font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (max-width:1280px){.tw-group>summary{grid-template-columns:auto minmax(0,1fr) auto}
  .tw-rb{grid-column:1 / -1}}
.tw-group>summary::-webkit-details-marker{display:none}
.tw-gtitle{font-weight:650;color:#141b24;font-size:13.5px;line-height:1.3;
  overflow-wrap:break-word;word-break:normal;min-width:0;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tw-group>summary,.tw-group>summary *{text-decoration:none}
.tw-gcap{min-width:0}
.tw-gmeta{color:#7c848f;font-size:11px;margin-top:2px}
.tw-gright{text-align:right;font-size:11.5px;color:#455163;white-space:nowrap}
.tw-gmedal{font-weight:700;font-size:13px}
.tw-inner{margin:0 0 6px 0}
.tw-inner thead th{background:#f6f8fb}
.tw-pagehead{display:flex;align-items:baseline;gap:10px;margin:0 0 6px 0}
.tw-ptitle{font-size:19px;font-weight:700;color:#141b24}
.tw-pmeta{font-size:12px;color:#7c848f}
.tw-paging{font-size:12px;color:#455163}
.tw-row{display:grid;grid-template-columns:58px minmax(0,1fr) 230px 250px;gap:10px;
  align-items:center;border:1px solid #dfe4ea;border-radius:10px;background:#fff;
  padding:7px 12px;margin-bottom:6px;text-decoration:none;color:inherit;cursor:pointer}
.tw-row:hover{background:#f2f7ff;border-color:#b9cdea}
.tw-rm{font-weight:700;font-size:13px}
.tw-rr{text-align:right;font-size:11.5px;color:#455163;white-space:nowrap}
.tw-rb .tw-bar{width:200px;height:6px;margin:0 0 3px 0}
.tw-rb .tw-pct{font-size:10.5px}
@media (max-width:1200px){ .tw-row{grid-template-columns:58px minmax(0,1fr) 200px} .tw-rb{display:none} }
</style>
"""


def _opt(options: List[Dict[str, Any]], label_key: str = "name"):
    codes = [_ALL] + [str(o["code"]) for o in options]
    labels = {_ALL: "Все"}
    for o in options:
        amount = o.get("amount")
        suffix = f" · {_short_amount(amount)}" if amount else ""
        labels[str(o["code"])] = f"{o.get(label_key) or o['code']} ({o.get('n', 0)}){suffix}"
    return codes, labels


def _short_amount(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f} млрд"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.0f} млн"
    if number >= 1_000:
        return f"{number / 1_000:.0f} тыс"
    return f"{number:.0f}"


def render_analytics_table_workspace_page(service) -> None:
    crm_db = getattr(service, "crm_db", None) if service is not None else None
    if crm_db is None:
        from src.services.db_bootstrap import connect_databases
        _radar, _tender, crm_db, _warn = connect_databases()
    _handle_row_action(crm_db)

    st.markdown(
        '<div class="tw-pagehead"><span class="tw-ptitle">Таблица закупок</span>'
        '<span class="tw-pmeta">режим → категория → подкатегория → объект</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _last = st.session_state.pop("tw_last_action", None)
    if _last:
        st.success(_last)
    options = load_filter_options(crm_db)


    top_search, top_edit = st.columns([4, 1])
    with top_search:
        search_text = st.text_input(
            "🔍 Поиск", placeholder="название, № закупки, заказчик",
            key="tw_search", label_visibility="collapsed",
        )
    with top_edit:
        st.toggle("✏️ Правка", value=False, disabled=True, key="tw_edit_mode", help="Редактирование — следующий этап")

    nav, main = st.columns([1, 4], gap="medium")
    with nav:
        selected_mode, category_code, subcategory_code, object_type, region, only_active = _render_navigation(options)
    with main:
        limit = st.slider("Строк", 50, 1000, 300, 50, key="tw_limit", label_visibility="collapsed")
        with st.spinner("Загрузка…"):
            result = load_workspace_rows(
                crm_db, selected_mode=selected_mode, category_code=category_code,
                subcategory_code=subcategory_code, object_type=object_type,
                region=region, search_text=search_text or None,
                only_active=only_active, limit=limit,
            )
        if result.get("error"):
            st.warning("Не удалось загрузить строки (read-only источник).")
            st.caption(str(result["error"]))
            return
        rows = result.get("rows") or []
        columns = result.get("columns") or []
        _render_selected_card(crm_db)
        _edit_pid = st.query_params.get("tw_catedit")
        if _edit_pid:
            try:
                _render_category_editor(crm_db, int(_edit_pid))
            except (TypeError, ValueError):
                pass
        # Пагинация ПО ЗАКУПКАМ: группа не разрывается между страницами.
        order_pids: List[Any] = []
        grouped: Dict[Any, List[Dict[str, Any]]] = {}
        for _r in rows:
            _pid = _r.get("procurement_id")
            if _pid not in grouped:
                grouped[_pid] = []
                order_pids.append(_pid)
            grouped[_pid].append(_r)
        _page_size = 50
        _total_pages = max(1, (len(order_pids) + _page_size - 1) // _page_size)
        _page = st.selectbox(
            "Страница", list(range(1, _total_pages + 1)),
            format_func=lambda p: f"стр. {p} из {_total_pages}",
            key="tw_page", label_visibility="collapsed",
        )
        _page_pids = order_pids[(_page - 1) * _page_size: _page * _page_size]
        _page_rows = [_r for _pid in _page_pids for _r in grouped[_pid]]
        st.caption(f"Найдено: {len(rows)} · тип: {_TYPE_LABELS.get(selected_mode, selected_mode)}")
        if not rows:
            st.info("Под выбранные фильтры строк нет.")
            return
        st.markdown(f'<div class="tw-wrap">{_render_table(columns, _page_rows)}</div>',
                    unsafe_allow_html=True)


_ACTIONS = ["", "✓ верно", "✗ не показывать", "★ приоритет"]


def _render_editor(crm_db, columns: List[str], rows: List[Dict[str, Any]]) -> None:
    """Native grid with a per-row action column (✓ / ✗ / ★)."""
    import pandas as pd
    from src.services.crm_ui_feedback_service import (
        apply_negative_rule,
        record_label,
        set_priority,
    )

    data = []
    for r in rows:
        item = {"Действие": ""}
        for col in columns:
            if col == "medal":
                # Подтверждённая медаль + отдельная пометка временного капа.
                _conf = r.get("medal_confirmed") or r.get("medal_current")
                _cap = (f" · окно: {r.get('medal_current')}"
                        if r.get("medal_capped_from") else "")
                item["Медаль"] = f"{_conf}{_cap}" + (
                    f" (initial {r.get('medal_initial')})" if r.get("medal_initial") else "")
            elif col == "temporal":
                t = r.get("temporal") or {}
                pct = t.get("window_consumed_ratio")
                item["Временное окно"] = (
                    f"{round(pct * 100)}% {bucket_label(t.get('temporal_bucket') or '')}"
                    + (f" · До {t.get('next_degrade_medal')}: {format_seconds(t.get('seconds_to_next_degrade'))}"
                       if t.get("next_degrade_medal") else "")
                ) if pct is not None else (bucket_label(t.get("temporal_bucket") or "") or "—")
            elif col == "deadline":
                item["Подача до"] = f"{r.get('deadline_text')}" + (
                    f" · {r.get('remaining_text')}" if r.get("remaining_text") else "")
            elif col == "purchase":
                item["Закупка"] = str(r.get("purchase_title"))[:120]
            elif col == "product":
                item["Товар"] = r.get("product_primary")
            elif col == "temporal":
                pass
            else:
                key = {
                    "customer": "customer", "price": "price_text", "documents": "documents_text",
                    "status": "status_text", "source": "source_text", "region": "region",
                    "object": "object_text", "works": "works_text", "context": "context_text",
                    "mode": "mode", "delivery": "delivery_text", "queue": "queue_text",
                }.get(col)
                label = COLUMN_LABELS.get(col, col)
                if col == "mode":
                    item[label] = MODE_LABELS.get(r.get("mode") or "", "—")
                else:
                    item[label] = r.get(key) if key else "—"
        data.append(item)

    df = pd.DataFrame(data)
    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Действие": st.column_config.SelectboxColumn(
                "Действие", options=_ACTIONS, required=False, width="small",
                help="✓ верно · ✗ больше такие не показывать · ★ приоритет",
            ),
        },
        key="tw_editor",
    )

    changed = [i for i in range(len(rows)) if str(edited.iloc[i]["Действие"] or "").strip()]
    if changed:
        if st.button(f"Применить к {len(changed)} строк(ам)", key="tw_apply_actions", type="primary"):
            who = st.session_state.get("user_name") or "operator"
            for i in changed:
                row = rows[i]
                action = str(edited.iloc[i]["Действие"]).strip()
                pid = row.get("procurement_id")
                cat = row.get("category_code")
                if action == "✓ верно":
                    record_label(crm_db, procurement_id=pid, category_code=cat,
                                 polarity="POSITIVE", created_by=who)
                elif action == "✗ не показывать" and cat:
                    apply_negative_rule(crm_db, procurement_id=pid, category_code=cat,
                                        title=row.get("purchase_title"), created_by=who)
                elif action == "★ приоритет":
                    set_priority(crm_db, procurement_id=pid,
                                 target_categories=[c for c in [cat] if c], requested_by=who)
            st.success(f"Применено: {len(changed)}")
            st.rerun()


def _render_labeling(crm_db, rows: List[Dict[str, Any]]) -> None:
    """Fast reference labelling: ✓ / ✗ (hide similar) / ★ priority."""
    from src.services.crm_ui_feedback_service import (
        apply_negative_rule,
        record_label,
        set_priority,
    )
    with st.expander("⚡ Разметка (эталон, обучение)", expanded=False):
        label_map = {
            f"№{r.get('purchase_meta') or ''} · {str(r.get('purchase_title'))[:70]} · {r.get('category_code') or '—'}": i
            for i, r in enumerate(rows)
        }
        pick = st.selectbox("Закупка", list(label_map), key="tw_label_pick")
        row = rows[label_map[pick]]
        pid = row.get("procurement_id")
        same = sorted({r.get("category_code") for r in rows
                       if r.get("procurement_id") == pid and r.get("category_code")})
        targets = st.multiselect("Категории (можно несколько)", same or [row.get("category_code")],
                                 default=same or [row.get("category_code")], key="tw_label_cats")
        c1, c2, c3 = st.columns(3)
        who = st.session_state.get("user_name") or "operator"
        if c1.button("✓ Верно", key="tw_lbl_ok", use_container_width=True):
            for cat in targets:
                record_label(crm_db, procurement_id=pid, category_code=cat,
                             polarity="POSITIVE", created_by=who)
            st.success(f"Подтверждено: {', '.join(t for t in targets if t)}")
        if c2.button("✗ Больше такие не показывать", key="tw_lbl_no", use_container_width=True):
            for cat in (targets or [row.get("category_code")]):
                if not cat:
                    continue
                res = apply_negative_rule(crm_db, procurement_id=pid, category_code=cat,
                                          title=row.get("purchase_title"), created_by=who)
                st.warning(f"{cat}: снято похожих {res['retired']} (фразы: {', '.join(res['phrases'])})")
            st.rerun()
        if c3.button("★ Приоритетный объект", key="tw_lbl_star", use_container_width=True):
            set_priority(crm_db, procurement_id=pid, target_categories=targets or [], requested_by=who)
            st.success("Отмечено приоритетным: поднимется в очереди вне общего бэклога.")


def _render_selected_card(crm_db: Any) -> None:
    """Карточка выбранной закупки (?tw_pid=ID) — инлайн над таблицей."""
    raw = st.query_params.get("tw_pid")
    if not raw:
        return
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return
    from src.ui.procurement_card_page import _render_dossier

    st.markdown('<a href="?" target="_self" style="font-size:12px;color:#2066b0;'
                'text-decoration:none">✕ закрыть карточку</a>', unsafe_allow_html=True)
    dossier = load_procurement_dossier(crm_db, pid)
    if not dossier.get("identity"):
        st.warning("Закупка не найдена.")
        return
    _render_dossier(dossier, crm_db)
    st.divider()


def _plain(column: str, row: Dict[str, Any]) -> str:
    """Текстовое значение ячейки для нативной selectable-таблицы."""
    mapping = {
        "medal": "medal_current", "product": "product_primary", "customer": "customer",
        "price": "price_text", "deadline": "deadline_text", "documents": "documents_text",
        "status": "status_text", "source": "source_text", "region": "region",
        "object": "object_text", "works": "works_text", "context": "context_text",
        "delivery": "delivery_text", "queue": "queue_text",
    }
    if column == "purchase":
        return str(row.get("purchase_title") or "—")
    if column == "mode":
        return MODE_LABELS.get(row.get("mode") or "", "—")
    return str(row.get(mapping.get(column, ""), "") or "—")


@st.dialog("Карточка закупки", width="large")
def _open_card(procurement_id: int, crm_db: Any) -> None:
    from src.ui.procurement_card_page import _render_dossier

    dossier = load_procurement_dossier(crm_db, int(procurement_id))
    if not dossier.get("identity"):
        st.warning("Закупка не найдена.")
        return
    _render_dossier(dossier, crm_db)


def _render_navigation(options: Dict[str, Any]):
    st.markdown("**Навигация**")
    cats = options.get("categories") or []
    cat_codes, cat_labels = _opt(cats)
    cat = st.selectbox("Категория", cat_codes, format_func=cat_labels.get, key="tw_cat")

    subs = [s for s in (options.get("subcategories") or []) if cat == _ALL or str(s.get("category_code")) == cat]
    sub_codes, sub_labels = _opt(subs)
    sub = st.selectbox("Подкатегория", sub_codes, format_func=sub_labels.get, key="tw_sub")

    type_label = st.segmented_control(
        "Тип", [_TYPE_LABELS[t] for t in _TYPE_OPTIONS],
        default=_TYPE_LABELS[ALL_MODES], key="tw_type",
    )
    selected_mode = next((t for t in _TYPE_OPTIONS if _TYPE_LABELS[t] == type_label), ALL_MODES)
    only_active = st.toggle(
        "Только актуальные", value=True, key="tw_only_active",
        help="Скрывать прямые поставки, где торги уже прошли",
    )

    objs = options.get("objects") or []
    obj_codes = [_ALL] + [str(o["name"]) for o in objs]
    obj_labels = {_ALL: "Все"}
    obj_labels.update({str(o["name"]): f"{o['name']} ({o.get('n', 0)})" for o in objs})
    obj = st.selectbox("Объект", obj_codes, format_func=obj_labels.get, key="tw_obj")

    regs = options.get("regions") or []
    reg_codes = [_ALL] + [str(r["name"]) for r in regs]
    reg_labels = {_ALL: "Все"}
    reg_labels.update({str(r["name"]): f"{r['name']} ({r.get('n', 0)})" for r in regs})
    reg = st.selectbox("Регион", reg_codes, format_func=reg_labels.get, key="tw_reg")

    return (
        selected_mode,
        None if cat == _ALL else cat,
        None if sub == _ALL else sub,
        None if obj == _ALL else obj,
        None if reg == _ALL else reg,
        only_active,
    )


def _load_manual_catalog(crm_db) -> Dict[str, Any]:
    """Реальные справочники для формы ручного добавления (без выдумывания)."""
    try:
        from src.services.manual_category_service import list_categories, list_subcategories
        cats = list_categories(crm_db)
    except Exception:  # noqa: BLE001
        cats = []
    cat_map = {c["category_code"]: c.get("category_name") or c["category_code"] for c in cats}
    sub_map: Dict[str, str] = {}
    subs_by_cat: Dict[str, List[str]] = {}
    for code in cat_map:
        try:
            subs = list_subcategories(code, crm_db)
        except Exception:  # noqa: BLE001
            subs = []
        subs_by_cat[code] = [s["subcategory_code"] for s in subs]
        for s in subs:
            sub_map[s["subcategory_code"]] = (
                f'{cat_map.get(code, code)} / {s.get("subcategory_name") or s["subcategory_code"]}'
            )
    return {"cats": list(cat_map), "cat_map": cat_map,
            "sub_map": sub_map, "subs_by_cat": subs_by_cat}


def _group_meta_html(head: Dict[str, Any]) -> str:
    deadline = head.get("deadline_text") or "—"
    remaining = head.get("remaining_text") or ""
    basis = str((head.get("temporal") or {}).get("window_basis") or "")
    basis_note = " (по плановым датам)" if basis == "DELIVERY" else ""
    return (
        f'<div class="tw-gright" style="text-align:left">'
        f'<b>{escape(str(head.get("price_text") or "—"))}</b> · '
        f'{escape(str(head.get("status_text") or "—"))} · до {escape(str(deadline))}{basis_note}'
        f'{" · " + escape(str(remaining)) if remaining else ""}</div>'
        f'<div class="tw-gwin">{_temporal_cell(head)}</div>'
    )


def _inner_table_html(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    inner_cols = [c for c in columns
                  if c in ("medal", "product", "mode", "context", "documents", "queue")]
    header = "".join(f"<th>{escape(COLUMN_LABELS.get(c, c))}</th>" for c in inner_cols)
    body = "".join(
        f'<tr data-pid="{r.get("procurement_id")}">' + f"<td>{_actions_cell(r)}</td>"
        + "".join(f"<td>{_cell(c, r)}</td>" for c in inner_cols) + "</tr>"
        for r in rows
    )
    return (f'<table class="tw-table tw-inner"><thead><tr><th>⚡</th>{header}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def _render_category_editor(crm_db, pid: int) -> None:
    """Редактор категорий закупки из предпросмотра (?tw_catedit=ID).

    AUTO-категории — только чтение (меняются через ✓/X), MANUAL — можно убрать.
    Добавление — то же MANUAL-хранилище.
    """
    from src.services.manual_category_service import (
        add_manual_category, list_categories, list_manual_categories,
        list_subcategories, remove_manual_category, set_manual_medal,
    )
    st.markdown(f"#### Категории закупки {pid}")
    st.markdown('<a href="?" target="_self" style="font-size:12px;color:#2066b0;'
                'text-decoration:none">✕ закрыть редактор</a>', unsafe_allow_html=True)
    auto = crm_db.execute_query(
        """SELECT DISTINCT commercial_category_code, current_effective_medal
           FROM crm_procurement_category_opportunities
           WHERE procurement_id=%s AND status='CURRENT'""", (int(pid),)) or []
    cat_names = {c["category_code"]: c.get("category_name") or c["category_code"]
                 for c in list_categories(crm_db)}
    # Одна строка на категорию: авто-медаль и (если есть) ручная — вместе, без дублей.
    auto_map = {a["commercial_category_code"]: a.get("current_effective_medal") for a in auto}
    manual_map = {m.get("category_code"): m for m in list_manual_categories(crm_db, pid)}
    codes = list(auto_map) + [c for c in manual_map if c not in auto_map]
    for code in codes:
        m = manual_map.get(code)
        c1, c2, c3 = st.columns([4, 2, 2])
        marks = f"авто {escape(str(auto_map.get(code) or '—'))}"
        if m:
            marks += (f" · вручную {escape(str(m.get('manual_candidate_level') or 'UNSCORED'))}"
                      f" ({escape(str(m.get('reviewed_by') or ''))})")
        c1.markdown(f"**{escape(str(cat_names.get(code, code)))}** · "
                    f"<span class='pc-muted'>{marks}</span>", unsafe_allow_html=True)
        med = c2.selectbox("Медаль", ["—", "GOLD", "SILVER", "BRONZE", "WOOD"],
                           key=f"tw_med_{pid}_{code}", label_visibility="collapsed")
        if med != "—" and c2.button("Сохранить", key=f"tw_medok_{pid}_{code}"):
            res = set_manual_medal(pid, code, med)
            st.session_state["tw_last_action"] = (
                f"{res.get('action')} · {code} · {med}"
                + (f" · {res.get('error')}" if res.get("error") else ""))
            st.rerun()
        if m and c3.button("Убрать ручную", key=f"tw_rm_{pid}_{code}"):
            remove_manual_category(pid, code)
            st.session_state["tw_last_action"] = f"Убрана ручная категория: {code}"
            st.rerun()
    if not codes:
        st.caption("Категорий нет.")
    with st.form(key=f"tw_editform_{pid}", clear_on_submit=True):
        st.caption("Добавить категорию (MANUAL / UNSCORED)")
        f1, f2, f3 = st.columns([3, 3, 2])
        cat = f1.selectbox("Категория", list(cat_names), format_func=cat_names.get,
                           key=f"tw_ec_{pid}")
        subs = {s["subcategory_code"]: (s.get("subcategory_name") or s["subcategory_code"])
                for s in list_subcategories(cat, crm_db)} if cat else {}
        sub = f2.selectbox("Подкатегория", ["—"] + list(subs),
                           format_func=lambda x: "—" if x == "—" else subs.get(x, x),
                           key=f"tw_es_{pid}")
        mode = f3.selectbox("Режим", ["EMBEDDED_MATERIAL", "DIRECT_SUPPLY", "DESIGN_REQUIREMENT"],
                            format_func=lambda m: {"EMBEDDED_MATERIAL": "В составе работ",
                                                   "DIRECT_SUPPLY": "Прямая поставка",
                                                   "DESIGN_REQUIREMENT": "Проект / влияние"}.get(m, m),
                            key=f"tw_em_{pid}")
        comment = st.text_input("Комментарий", key=f"tw_ecm_{pid}")
        if st.form_submit_button("＋ Добавить") and cat:
            res = add_manual_category(pid, cat, subcategory_code=(None if sub == "—" else sub),
                                      mode=mode, comment=comment or None)
            st.session_state["tw_last_action"] = (
                f"{res.get('action')} · {res.get('category_code')}"
                + (f" · {res.get('error')}" if res.get("error") else ""))
            st.rerun()
    st.divider()


def _render_group(crm_db, columns: List[str], rows: List[Dict[str, Any]],
                  catalog: Dict[str, Any]) -> None:
    """Компактный предпросмотр закупки: медаль, данные, сроки и шкала окна.

    Клик по строке открывает карточку закупки (?tw_pid=...). Категории и форма
    ручного добавления живут в карточке — здесь ничего не «вываливается».
    """
    from src.services.commercial_routing_v3.submission_window_temporal import MEDAL_RANK
    head = rows[0]
    pid = head.get("procurement_id")
    best = max((MEDAL_RANK.get(str(r.get("medal_confirmed") or r.get("medal_current") or "").upper(), -1)
                for r in rows), default=-1)
    _RANK_TO_MEDAL = {"GOLD": 3, "SILVER": 2, "BRONZE": 1, "WOOD": 0}
    best_label = next((m for m, r in _RANK_TO_MEDAL.items() if r == best), "—")
    deadline = head.get("deadline_text") or "—"
    st.markdown(
        f'<a class="tw-row" href="?tw_pid={pid}" target="_self">'
        f'<div class="tw-rm">{escape(best_label)}</div>'
        f'<div><div class="tw-gtitle">{escape(str(head.get("purchase_title") or "—"))}</div>'
        f'<div class="tw-gmeta">{escape(str(head.get("purchase_meta") or ""))} · '
        f'категорий: {len(rows)}</div></div>'
        f'<div class="tw-rr"><b>{escape(str(head.get("price_text") or "—"))}</b><br>'
        f'{escape(str(head.get("status_text") or "—"))} · до {escape(str(deadline))}</div>'
        f'<div class="tw-rb">{_temporal_cell(head)}</div>'
        f'</a>',
        unsafe_allow_html=True,
    )


def _render_table(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    """Группировка по закупке: заголовок закупки + вложенные категорийные строки."""
    from src.services.commercial_routing_v3.submission_window_temporal import MEDAL_RANK

    groups: Dict[Any, List[Dict[str, Any]]] = {}
    order: List[Any] = []
    for row in rows:
        pid = row.get("procurement_id")
        if pid not in groups:
            groups[pid] = []
            order.append(pid)
        groups[pid].append(row)

    # В заголовке закупки уже есть наименование/№/НМЦК/статус — не дублируем их
    # в каждой категорийной строке.
    # В строке категории — только индивидуальное. Общие сроки/статус/шкала
    # живут в заголовке закупки (не дублируются).
    inner_cols = [c for c in columns
                  if c in ("medal", "product", "mode", "context", "documents", "queue")]
    inner_header = "".join(f"<th>{escape(COLUMN_LABELS.get(c, c))}</th>" for c in inner_cols)
    medal_label = {3: "GOLD", 2: "SILVER", 1: "BRONZE", 0: "WOOD"}

    blocks: List[str] = []
    for pid in order:
        rr = groups[pid]
        head = rr[0]
        best = max(
            (MEDAL_RANK.get(str(x.get("medal_confirmed") or x.get("medal_current") or "").upper(), -1)
             for x in rr),
            default=-1,
        )
        best_label = medal_label.get(best, "—")
        meta = head.get("purchase_meta") or ""
        deadline = head.get("deadline_text") or "—"
        remaining = head.get("remaining_text") or ""
        basis = str((head.get("temporal") or {}).get("window_basis") or "")
        basis_note = " (по плановым датам)" if basis == "DELIVERY" else ""
        body = "".join(
            f'<tr data-pid="{pid}">'
            + f"<td>{_actions_cell(r)}</td>"
            + "".join(f"<td>{_cell(c, r)}</td>" for c in inner_cols)
            + "</tr>"
            for r in rr
        )
        blocks.append(
            f'<details class="tw-group">'
            f'<summary>'
            f'<div><a href="?tw_catedit={head.get("procurement_id")}" target="_self" '
            f'title="Изменить категории" style="text-decoration:none">'
            f'<span class="tw-gmedal">{escape(best_label)}</span></a></div>'
            f'<div><div class="tw-gtitle">{escape(str(head.get("purchase_title") or "—"))}</div>'
            f'<div class="tw-gmeta">{escape(str(meta))} · категорий: {len(rr)}</div></div>'
            f'<div class="tw-gright">{escape(str(head.get("price_text") or "—"))}<br>'
            f'{escape(str(head.get("status_text") or "—"))} · до {escape(str(deadline))}'
            f'{basis_note}'
            f'{" · " + escape(str(remaining)) if remaining else ""}'
            f'<br><a href="?tw_pid={head.get("procurement_id")}" target="_self" '
            f'style="font-size:11px;font-weight:600;color:#2066b0;text-decoration:none">'
            f'карточка ↗</a>'
            + ('<br><span class="pc-chip ok">очередь: успеет</span>'
               if head.get("queue_fits") is True else
               ('<br><span class="pc-chip bad">очередь: может не успеть</span>'
                if head.get("queue_fits") is False else ""))
            + (f'<div class="tw-small">{escape(str(head.get("queue_text")))}</div>'
               if head.get("queue_text") else "")
            + '</div>'
            f'<div class="tw-rb">{_temporal_cell(head)}</div>'
            f'</summary>'
            f'<div class="tw-gwin">{_temporal_detail(head)}</div>'
            f'<table class="tw-table tw-inner"><thead><tr><th>⚡</th>{inner_header}</tr></thead>'
            f"<tbody>{body}</tbody></table></details>"
        )
    return "".join(blocks)


def _actions_cell(row: Dict[str, Any]) -> str:
    pid = row.get("procurement_id")
    cat = str(row.get("category_code") or "")
    if not pid:
        return "—"

    def link(act: str, glyph: str, title: str) -> str:
        return (f'<a href="?tw_act={act}&tw_pid={pid}&tw_cat={escape(cat)}" '
                f'title="{escape(title)}" style="text-decoration:none;margin-right:5px">{glyph}</a>')

    return (link("ok", "✓", "Больше таких в этой категории")
            + link("no", "✗", "Больше не показывать такие в этой категории"))


def _render_history_panel(crm_db) -> None:
    """Timeline + exact model prompt for a chosen procurement."""
    from src.services.crm_procurement_history_service import load_history, load_model_prompt, timeline_lines

    with st.expander("🕘 История закупки / В модель уходит", expanded=False):
        pid_text = st.text_input("ID закупки", key="tw_hist_pid", placeholder="например 1020")
        try:
            pid = int(pid_text)
        except (TypeError, ValueError):
            st.caption("Введи ID закупки, чтобы увидеть историю и текст запроса в модель.")
            return
        history = load_history(crm_db, pid)
        for line in timeline_lines(history):
            st.markdown(f"- {line}")
        payload = load_model_prompt(crm_db, pid)
        st.markdown("**В модель уходит (model_input):**")
        if isinstance(payload.get("model_input"), dict):
            st.json(payload["model_input"])
        else:
            st.caption(f"model_input недоступен: {payload.get('result')}")
        if payload.get("prompt"):
            st.text_area("Текст промпта", payload["prompt"], height=320, key="tw_hist_prompt")
        else:
            st.caption("Промпт не отрендерился (нет model_input).")


def _handle_row_action(crm_db) -> None:
    """Apply a row link action (?tw_act=ok|no|star&tw_pid=..&tw_cat=..) then rerun."""
    act = st.query_params.get("tw_act")
    if not act:
        return
    try:
        pid = int(st.query_params.get("tw_pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    cat = st.query_params.get("tw_cat") or None
    if not pid:
        st.query_params.clear()
        return
    who = st.session_state.get("user_name") or "operator"
    rows = crm_db.execute_query("SELECT auction_name, okpd_code FROM crm_procurements WHERE id=%s", (pid,)) or []
    title = rows[0].get("auction_name") if rows else None
    from src.services.crm_ui_feedback_service import (
        apply_negative_rule,
        apply_positive_rule,
    )
    if act == "ok":
        res = apply_positive_rule(crm_db, procurement_id=pid, category_code=cat or "",
                                  title=title, created_by=who)
        st.session_state["tw_last_action"] = (
            f"✓ {cat}: больше таких в этой категории (фразы: {', '.join(res['phrases'])})")
    elif act == "no" and cat:
        res = apply_negative_rule(crm_db, procurement_id=pid, category_code=cat,
                                  title=title, created_by=who)
        st.session_state["tw_last_action"] = f"✗ {cat}: снято похожих {res['retired']}"
    st.query_params.clear()
    st.rerun()


def _cell(column: str, row: Dict[str, Any]) -> str:
    if column == "medal":
        return _medal_cell(row)
    if column == "temporal":
        return _temporal_cell(row)
    if column == "product":
        second = row.get("product_secondary")
        extra = f'<div class="tw-small">{escape(str(second))}</div>' if second else ""
        return f'<div class="tw-title">{escape(str(row.get("product_primary") or "—"))}</div>{extra}'
    if column == "deadline":
        remaining = row.get("remaining_text")
        sub = f'<div class="tw-small">{escape(str(remaining))}</div>' if remaining else ""
        return f'<div>{escape(str(row.get("deadline_text") or "—"))}</div>{sub}'
    if column == "purchase":
        meta = row.get("purchase_meta")
        sub = f'<div class="tw-small">{escape(str(meta))}</div>' if meta else ""
        pid = row.get("procurement_id")
        title = escape(str(row.get("purchase_title") or "—"))
        if pid:
            # Клик по строке-закупке открывает карточку (через query-параметр,
            # без компонентов и без checkbox-колонок).
            return (
                f'<a class="tw-title tw-open" href="?tw_pid={escape(str(pid))}" '
                f'target="_self" style="text-decoration:none;color:inherit">{title}</a>{sub}'
            )
        return f'<div class="tw-title">{title}</div>{sub}'
    text = {
        "customer": "customer", "price": "price_text", "documents": "documents_text",
        "status": "status_text", "source": "source_text", "region": "region",
        "object": "object_text", "works": "works_text", "context": "context_text",
        "mode": "mode", "delivery": "delivery_text", "queue": "queue_text",
    }.get(column)
    if text == "mode":
        return escape(MODE_LABELS.get(row.get("mode") or "", "—"))
    return escape(str(row.get(text) or "—"))


def _medal_cell(row: Dict[str, Any]) -> str:
    # Показываем подтверждённую медаль; если окно её ограничило — это отдельная пометка.
    current = escape(str(row.get("medal_confirmed") or row.get("medal_current") or "—"))
    initial = row.get("medal_initial")
    parts = []
    if initial:
        parts.append(f"initial {escape(str(initial))}")
    if row.get("medal_capped_from"):
        parts.append(f"окно: {escape(str(row.get('medal_current')))}")
    sub = f'<div class="tw-small">{" · ".join(parts)}</div>' if parts else ""
    return f'<div class="tw-medal">{current}</div>{sub}'


def _temporal_detail(row: Dict[str, Any]) -> str:
    """Подробности окна для раскрытой части — без повторения шкалы."""
    temporal = row.get("temporal") or {}
    bucket = temporal.get("temporal_bucket") or TEMPORAL_UNKNOWN
    if bucket == TEMPORAL_UNKNOWN:
        return '<div class="tw-small">Временное окно не определено</div>'
    parts = []
    nxt = temporal.get("next_degrade_medal")
    if nxt:
        parts.append(f"До {escape(str(nxt))}: "
                     f"{escape(format_seconds(temporal.get('seconds_to_next_degrade')))}")
    else:
        parts.append(f"До окончания: "
                     f"{escape(format_seconds(temporal.get('seconds_to_deadline')))}")
    if nxt and str(nxt).upper() != "WOOD" and temporal.get("seconds_to_wood") is not None:
        parts.append(f"До WOOD: {escape(format_seconds(temporal.get('seconds_to_wood')))}")
    return '<div class="tw-small">' + " · ".join(parts) + "</div>"


def _temporal_cell(row: Dict[str, Any]) -> str:
    temporal = row.get("temporal") or {}
    bucket = temporal.get("temporal_bucket") or TEMPORAL_UNKNOWN
    color = bucket_color(bucket)
    ratio = temporal.get("window_consumed_ratio")

    if bucket == TEMPORAL_UNKNOWN:
        return '<div class="tw-small">Срок неизвестен</div>'

    if temporal.get("window_basis") == "DEADLINE_ONLY":
        lines = [
            f'<div class="tw-bar"><div class="tw-fill" style="width:100%;background:{color};opacity:.45"></div></div>',
            f'<div class="tw-pct">{escape(bucket_label(bucket))}</div>',
        ]
        next_medal = temporal.get("next_degrade_medal")
        if next_medal:
            lines.append(
                f'<div>До {escape(str(next_medal))}: {escape(format_seconds(temporal.get("seconds_to_next_degrade")))}</div>'
            )
        else:
            lines.append(f'<div>До окончания: {escape(format_seconds(temporal.get("seconds_to_deadline")))}</div>')
        if next_medal and str(next_medal).upper() != "WOOD" and temporal.get("seconds_to_wood") is not None:
            lines.append(f'<div class="tw-small">До WOOD: {escape(format_seconds(temporal.get("seconds_to_wood")))}</div>')
        return "".join(lines)

    pct = 100.0 if bucket == EXPIRED else round(float(ratio or 0.0) * 100)
    tooltip = (
        f"Окно подачи использовано: {pct}%\n"
        f"Начало: {temporal.get('submission_start_at') or '—'}\n"
        f"Окончание: {temporal.get('submission_deadline_at') or '—'}\n"
        "40%: SILVER cap · 60%: BRONZE cap · 80%: WOOD cap"
    )
    markers = "".join(
        f'<span class="tw-mark" style="left:{int(pos * 100)}%"></span>' for pos in (0.40, 0.60, 0.80)
    )
    bar = (
        f'<div class="tw-bar" title="{escape(tooltip)}">'
        f'<div class="tw-fill" style="width:{pct}%;background:{color}"></div>{markers}</div>'
    )
    if bucket == EXPIRED:
        return bar + '<div class="tw-small">100% · EXPIRED · Подача завершена</div>'

    lines = [f'<div class="tw-pct">{pct}% · {escape(bucket_label(bucket))}</div>']
    next_medal = temporal.get("next_degrade_medal")
    if next_medal:
        lines.append(
            f'<div>До {escape(str(next_medal))}: {escape(format_seconds(temporal.get("seconds_to_next_degrade")))}</div>'
        )
    else:
        lines.append(f'<div>До окончания: {escape(format_seconds(temporal.get("seconds_to_deadline")))}</div>')
    wood = temporal.get("seconds_to_wood")
    if next_medal and str(next_medal).upper() != "WOOD" and wood is not None:
        lines.append(f'<div class="tw-small">До WOOD: {escape(format_seconds(wood))}</div>')
    return bar + "".join(lines)
