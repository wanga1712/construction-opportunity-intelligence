"""Экран «Паркинги и объекты» — карточки гидроизоляции в стиле SLDS.

Требование бизнеса: 16 новых полей показываются не плоской таблицей, а
секциями в стиле Salesforce Lightning:

    Техническое состояние: Дефектовка, Техрешение
    Коммерция:             КП, ТЗ, Торги 615-ПП

Каждое поле помечено происхождением данных: «Автозагрузка» (ночной синк NSPD)
или «Менеджер» (ручной ввод). Ручные значения живут в `manual_overrides` и
ночным загрузчиком не затираются.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

import streamlit as st

from src.services.hydro import card_fields as cf
from src.services.hydro.card_repository import HydroCardRepository, as_text, effective
from src.ui import hydro_source_status as hydro_status
from src.ui import system_health_slds as slds


def _section_title(text: str) -> str:
    return f'<div class="slds-card__title" style="font-size:16px;margin:2px 0 8px 0">{slds.esc(text)}</div>'

SOURCE_BADGE = "Автозагрузка"
MANUAL_BADGE = "Менеджер"
LEGEND = (
    f"{slds.badge(SOURCE_BADGE, 'neutral')} данные NSPD, обновляются ночным синком · "
    f"{slds.badge(MANUAL_BADGE, 'info')} ввод менеджера, синк их не затирает"
)
_BADGE_TONES = {
    "granted": "ok", "approved": "ok", "sent": "info", "draft": "neutral",
    "pending": "warn", "medium": "warn", "minor": "neutral",
    "rejected": "crit", "critical": "crit",
}


def _fmt_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-":
        try:
            return datetime.fromisoformat(text[:19]).strftime("%d.%m.%Y")
        except ValueError:
            return text
    return text


def _display(field: cf.HydroField, value: Any) -> str:
    if value in (None, "", [], {}):
        return '<span class="slds-empty">не заполнено</span>'
    if field.kind == "flag":
        return slds.badge("Да" if value else "Нет", "ok" if value else "neutral")
    if field.kind == "badge":
        key = str(value)
        return slds.badge(field.choice_labels.get(key, key), _BADGE_TONES.get(key, "neutral"))
    if field.kind == "money":
        try:
            return slds.esc(f"{float(value):,.0f} ₽".replace(",", " "))
        except (TypeError, ValueError):
            return slds.esc(str(value))
    if field.kind == "date":
        return slds.esc(_fmt_date(value))
    if field.kind == "url":
        return f'<a href="{slds.esc(value)}" target="_blank" rel="noopener">Открыть</a>'
    return slds.esc(as_text(value))


def _field_row(field: cf.HydroField, row: Mapping[str, Any]) -> str:
    value, is_manual = effective(row, field.key)
    badge = slds.badge(MANUAL_BADGE if is_manual else SOURCE_BADGE, "info" if is_manual else "neutral")
    hint = f'<div class="slds-svc__note">{slds.esc(field.hint)}</div>' if field.hint else ""
    return (
        '<div class="slds-svc"><span>'
        f'<span class="slds-label">{slds.esc(field.label)}</span>'
        f'<div class="slds-svc__name">{_display(field, value)}</div>{hint}</span>'
        f"<span>{badge}</span></div>"
    )


def _group_html(group: cf.HydroFieldGroup, row: Mapping[str, Any]) -> str:
    body = "".join(_field_row(field, row) for field in group.fields)
    return slds.card(group.title, body, footer=group.hint or "")


def _card_header(row: Mapping[str, Any]) -> None:
    address = row.get("address") or row.get("cadastral_number") or f"Объект {row.get('id')}"
    st.markdown(f"### {slds.esc(address)}", unsafe_allow_html=True)
    parts = [f"Кадастр {row.get('cadastral_number') or '—'}"]
    if row.get("uk_name"):
        parts.append(f"УК: {row['uk_name']} (ИНН {row.get('uk_inn') or '—'})")
    if row.get("area_total"):
        parts.append(f"{row['area_total']} м²")
    st.caption(" · ".join(parts))
    st.markdown(LEGEND, unsafe_allow_html=True)


def _edit_form(repo: HydroCardRepository, row: Mapping[str, Any]) -> None:
    """Правки менеджера по всем секциям — в одном месте, отдельно от источника."""
    editable = [f for f in cf.all_fields() if f.is_manual]
    with st.expander("✏️ Редактировать поля менеджера", expanded=False):
        with st.form(f"hydro_edit_{row['id']}"):
            values: dict[str, Any] = {}
            columns = st.columns(2)
            for index, field in enumerate(editable):
                if field.key in ("inspection_notes",):
                    continue
                current, _ = effective(row, field.key)
                with columns[index % 2]:
                    values[field.key] = _widget(field, current)
            notes_current, _ = effective(row, "inspection_notes")
            values["inspection_notes"] = st.text_area(
                "Заключение по дефектовке", value=as_text(notes_current)
            )
            if st.form_submit_button("💾 Сохранить поля менеджера", type="primary"):
                repo.save_overrides(row["id"], values)
                st.success("Сохранено: источник и загрузчик не затронуты.")
                st.rerun()


def _widget(field: cf.HydroField, current: Any) -> Any:
    key = f"hydro_edit_{field.key}"
    if field.kind == "badge":
        options = ["", *field.choices]
        index = options.index(str(current)) if str(current) in options else 0
        choice = st.selectbox(field.label, options, index=index, key=f"{key}_sel",
                              format_func=lambda v: field.choice_labels.get(v, "— не задано —") if v else "— не задано —")
        return choice
    if field.kind == "flag":
        return st.checkbox(field.label, value=bool(current), key=f"{key}_chk")
    placeholder = field.hint or ""
    return st.text_input(field.label, value=as_text(current), key=f"{key}_txt", placeholder=placeholder)


def _render_card(repo: HydroCardRepository, row: Mapping[str, Any]) -> None:
    _card_header(row)
    if st.button("⬅ К списку объектов", key="hydro_card_back"):
        st.session_state.pop("hydro_open_object", None)
        st.rerun()
    left, right = st.columns([7, 5])
    with left:
        for section in cf.SECTIONS:
            st.markdown(_section_title(section.title), unsafe_allow_html=True)
            for group in section.groups:
                st.markdown(_group_html(group, row), unsafe_allow_html=True)
    with right:
        st.markdown(_section_title(cf.SOURCE_SECTION.title), unsafe_allow_html=True)
        for group in cf.SOURCE_SECTION.groups:
            st.markdown(_group_html(group, row), unsafe_allow_html=True)
    _edit_form(repo, row)


def _render_kpis(repo: HydroCardRepository) -> None:
    view = hydro_status.describe(repo.source_health())
    tone = {"ok": "ok", "warn": "warn", "crit": "crit"}.get(str(view.get("tone")), "neutral")
    columns = st.columns(4)
    columns[0].markdown(slds.kpi_card("Объектов в CRM", f"{repo.total():,}".replace(",", " "),
                                      "канонический срез NSPD"), unsafe_allow_html=True)
    columns[1].markdown(slds.kpi_card("С правками менеджера", str(repo.manual_count()),
                                      "поля, которые синк не трогает"), unsafe_allow_html=True)
    columns[2].markdown(slds.kpi_card("Ночной синк", str(view.get("label") or "—"),
                                      hydro_status.slds_and_time((view.get("health") or {}).get("last_success_at")),
                                      tone=tone, value_tone=True), unsafe_allow_html=True)
    loaded = (view.get("health") or {}).get("rows_seen")
    columns[3].markdown(slds.kpi_card("Загружено записей",
                                      "—" if loaded is None else f"{int(loaded):,}".replace(",", " "),
                                      "последний успешный синк"), unsafe_allow_html=True)


def _render_list(repo: HydroCardRepository, rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        filled = sum(1 for f in cf.SECTIONS[0].groups[0].fields if effective(row, f.key)[0])
        badges = slds.badge(MANUAL_BADGE, "info") if row.get("manual_overrides") else slds.badge(SOURCE_BADGE, "neutral")
        body = (
            f'<div class="slds-svc"><span><span class="slds-svc__name">{slds.esc(row.get("address") or "—")}</span>'
            f'<div class="slds-svc__note">Кадастр {slds.esc(row.get("cadastral_number") or "—")}'
            f' · {slds.esc(row.get("uk_name") or "УК не привязана")}'
            f' · дефектовка заполнена на {filled} из {len(cf.SECTIONS[0].groups[0].fields)}</div></span>'
            f"<span>{badges}</span></div>"
        )
        left, right = st.columns([9, 2])
        with left:
            st.markdown(slds.card(f"Объект #{row.get('id')}", body), unsafe_allow_html=True)
        with right:
            if st.button("Открыть карточку", key=f"hydro_open_obj_{row.get('id')}", use_container_width=True):
                st.session_state["hydro_open_object"] = int(row["id"])
                st.rerun()


@st.cache_resource(show_spinner=False)
def _fallback_crm_db() -> Any:
    try:
        from src.services.db_bootstrap import connect_crm_database

        return connect_crm_database()
    except Exception:  # noqa: BLE001
        return None


def render_hydro_objects_screen(service: Any) -> None:
    """Экран «Паркинги и объекты»: KPI, статус синка, список и карточка объекта."""
    st.markdown(slds.SLDS_CSS, unsafe_allow_html=True)
    crm_db = getattr(service, "crm_db", None) or _fallback_crm_db()
    repo = HydroCardRepository(crm_db)
    if not repo.schema_available:
        st.error(
            "Канонические таблицы Hydro недоступны. Нужны миграции "
            "`src/migrations/hydro_*.sql` и доступ к CRM БД."
        )
        if repo.last_schema_error:
            st.caption(repo.last_schema_error)
        return

    view = hydro_status.describe(repo.source_health())
    st.markdown(hydro_status.ribbon(view), unsafe_allow_html=True)
    notice = hydro_status.alert(view)
    if notice:
        (st.error if notice[0] == "crit" else st.warning)(notice[1])
    _render_kpis(repo)

    open_id = st.session_state.get("hydro_open_object")
    if open_id:
        row = repo.get_object(open_id)
        if not row:
            st.session_state.pop("hydro_open_object", None)
            st.warning("Объект не найден.")
            return
        _render_card(repo, row)
        return

    controls = st.columns([4, 2, 2])
    query = controls[0].text_input("Поиск: адрес, кадастр или УК", key="hydro_obj_search")
    only_manual = controls[1].checkbox("Только с правками менеджера", key="hydro_obj_only_manual")
    limit = controls[2].selectbox("Показывать", [25, 50, 100], index=1, key="hydro_obj_limit")
    rows = repo.list_objects(text=query or None, only_manual=only_manual, limit=int(limit))
    st.markdown(_section_title(f"Объекты ({len(rows)})"), unsafe_allow_html=True)
    if not rows:
        st.info("Ничего не найдено. Запустите ночной синк или измените фильтр.")
        return
    _render_list(repo, rows)
