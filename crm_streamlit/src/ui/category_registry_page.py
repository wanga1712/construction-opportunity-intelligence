"""Category Registry Editor — Superuser UI.

Страница: Настройки → Товарные категории
Позволяет просматривать, редактировать и создавать категории product registry.
НЕ запускает AI reassessment автоматически.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import streamlit as st

from src.services.category_registry_service import (
    ALLOWED_DOC_TYPES,
    ALLOWED_ENTRY_POINTS,
    ALLOWED_EXTRACTION_FIELDS,
    ALLOWED_PROCUREMENT_TYPES,
    ALLOWED_ROLES,
    ALLOWED_ROUTES,
    bump_registry_version,
    count_stale_candidates,
    create_category,
    get_all_categories,
    get_category_by_code,
    get_current_registry_version,
    get_registry_history,
    get_subcategories_for,
    preview_stale_objects,
    update_category,
)

logger = logging.getLogger("category_registry_page")

# ─── Константы ────────────────────────────────────────────────────────────────

ROUTE_LABELS = {
    "CONSTRUCTION_BUILDING": "🏗️ Строительство зданий",
    "CONSTRUCTION_INFRASTRUCTURE": "🛣️ Инфраструктурное строительство",
    "DESIGN_ENGINEERING": "📐 Проектирование",
    "COMPUTERS_IT": "💻 Компьютеры и ИТ",
    "DIRECT_SUPPLY": "📦 Прямая поставка",
    "EXCLUDED": "🚫 Исключить",
}

ROLE_LABELS = {
    "PRIMARY_SUPPLY": "Основная поставка",
    "EMBEDDED_MATERIAL": "Встроенный материал",
    "CONSUMABLE": "Расходный материал",
    "OBJECT_OF_RESEARCH": "Объект исследования",
    "AUXILIARY_CONTEXT": "Вспомогательный контекст",
    "ABSENT": "Отсутствует",
    "UNKNOWN": "Неизвестно",
}

ENTRY_LABELS = {
    "DIRECT_SUPPLY": "Прямая поставка",
    "SUPPLIER": "Поставщик",
    "SUB_CONTRACTOR": "Субподрядчик",
    "CONTRACTOR_PARTNER": "Партнёр-подрядчик",
    "NO_ENTRY": "Нет входа",
    "UNKNOWN": "Неизвестно",
}

PROCUREMENT_LABELS = {
    "supply_only": "Только поставка",
    "works_with_embedded_materials": "Работы с материалами",
    "installation_only": "Только монтаж",
    "design_only": "Только проектирование",
    "construction_only": "Только строительство",
    "design_and_construction": "Проектирование + строительство",
    "specialized_turnkey_complex": "Специализированный комплекс",
    "service_only": "Только сервис",
    "unclear": "Неопределённо",
}

DOC_TYPE_LABELS = {
    "TECHNICAL_SPEC": "Техническое задание",
    "DESIGN_DOCUMENTATION": "Проектная документация",
    "BILL_OF_QUANTITIES": "Ведомость объёмов работ",
    "ESTIMATE": "Смета",
    "LOCAL_ESTIMATE": "Локальная смета",
    "SPECIFICATION": "Спецификация",
    "WORKING_DOCUMENTATION": "Рабочая документация",
    "EQUIPMENT_LIST": "Перечень оборудования",
    "PRICE_APPENDIX": "Ценовое приложение",
    "OTHER": "Прочее",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_crm_db():
    service = st.session_state.get("service")
    if service:
        return service.crm_db
    return None


def _badges(items: List[str], color: str = "#e0e0e0", text_color: str = "#333") -> str:
    if not items:
        return '<span style="color:#aaa">—</span>'
    badges = "".join(
        f'<span style="background:{color};color:{text_color};border-radius:4px;'
        f'padding:2px 7px;margin:1px 2px;font-size:12px;display:inline-block">{i}</span>'
        for i in items
    )
    return badges


def _signals_editor(label: str, key: str, initial: List[str]) -> List[str]:
    """Редактор списка строк (сигналы, aliases и т.д.)."""
    st.caption(label)
    text = st.text_area(
        label,
        value="\n".join(initial),
        height=120,
        key=key,
        label_visibility="collapsed",
        help="Каждый элемент на новой строке",
        placeholder="Один элемент на строку",
    )
    return [line.strip() for line in text.splitlines() if line.strip()]


def _doc_plan_editor(key: str, initial: List[Dict]) -> List[Dict]:
    """Редактор document_search_plan."""
    st.caption("Порядок поиска документов (doc_type + приоритет 0–100)")

    rows = initial or []
    # Привести к нужному формату
    norm = []
    for item in rows:
        if isinstance(item, dict):
            norm.append({
                "doc_type": item.get("doc_type", ""),
                "priority": int(item.get("priority", 50)),
                "reason": item.get("reason", ""),
            })

    result = []
    used_types = [r["doc_type"] for r in norm]
    remaining = [t for t in ALLOWED_DOC_TYPES if t not in used_types]

    # Показать существующие
    for idx, row in enumerate(norm):
        col_type, col_prio, col_del = st.columns([3, 1, 0.5])
        with col_type:
            dt = st.selectbox(
                "Тип",
                ALLOWED_DOC_TYPES,
                index=ALLOWED_DOC_TYPES.index(row["doc_type"]) if row["doc_type"] in ALLOWED_DOC_TYPES else 0,
                key=f"{key}_dt_{idx}",
                label_visibility="collapsed",
            )
        with col_prio:
            prio = st.number_input(
                "Приоритет",
                min_value=0, max_value=100,
                value=row["priority"],
                key=f"{key}_prio_{idx}",
                label_visibility="collapsed",
            )
        with col_del:
            if st.button("✕", key=f"{key}_del_{idx}", use_container_width=True):
                continue  # пропустить = удалить
        result.append({"doc_type": dt, "priority": prio, "reason": row.get("reason", "")})

    # Добавить новую строку
    if remaining:
        col_add, col_dt, col_prio = st.columns([0.7, 3, 1])
        with col_add:
            add = st.button("＋", key=f"{key}_add", use_container_width=True)
        with col_dt:
            new_type = st.selectbox(
                "Новый тип", remaining, key=f"{key}_new_dt", label_visibility="collapsed"
            )
        with col_prio:
            new_prio = st.number_input(
                "Приоритет", min_value=0, max_value=100, value=80,
                key=f"{key}_new_prio", label_visibility="collapsed"
            )
        if add:
            result.append({"doc_type": new_type, "priority": new_prio, "reason": ""})

    return sorted(result, key=lambda x: -x.get("priority", 0))


def _section_plan_editor(key: str, initial: List[Dict]) -> List[Dict]:
    """Редактор section_search_plan."""
    st.caption("Разделы документов для поиска")
    rows = initial or []
    result = []
    for idx, row in enumerate(rows):
        col_name, col_prio, col_del = st.columns([3, 1, 0.5])
        with col_name:
            name = st.text_input(
                "Раздел", value=row.get("section_name", ""),
                key=f"{key}_sec_name_{idx}", label_visibility="collapsed"
            )
        with col_prio:
            prio = st.number_input(
                "Приоритет", min_value=0, max_value=100, value=int(row.get("priority", 50)),
                key=f"{key}_sec_prio_{idx}", label_visibility="collapsed"
            )
        with col_del:
            if st.button("✕", key=f"{key}_sec_del_{idx}", use_container_width=True):
                continue
        if name:
            result.append({"section_name": name, "priority": prio})

    if st.button("＋ Добавить раздел", key=f"{key}_sec_add"):
        result.append({"section_name": "Новый раздел", "priority": 50})

    return result


# ─── Список категорий ─────────────────────────────────────────────────────────

def _render_category_list(crm_db):
    """Таблица всех категорий с действиями."""
    cats = get_all_categories(crm_db, include_inactive=True)
    reg_info = get_current_registry_version(crm_db)

    # ─ Header
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.subheader("📦 Товарные категории")
        st.caption(
            f"Registry v{reg_info['version']} · hash `{reg_info['hash'] or 'не рассчитан'}` · "
            f"{sum(1 for c in cats if c.get('is_active'))} активных из {len(cats)}"
        )
    with col_btn:
        st.write("")
        if st.button("➕ Новая категория", key="cat_new_btn", use_container_width=True, type="primary"):
            st.session_state["cat_editor_mode"] = "create"
            st.session_state["cat_editor_code"] = ""
            st.rerun()

    st.markdown("---")

    if not cats:
        st.info("Категорий пока нет.")
        return

    # ─ Таблица
    for cat in cats:
        active = cat.get("is_active", False)
        code = cat.get("category_code", "")
        name = cat.get("category_name", "")
        n_sub = len(get_subcategories_for(crm_db, cat["id"]))
        n_sigs = len(cat.get("positive_signals") or []) + len(cat.get("negative_contexts") or [])
        routes = cat.get("applicable_routes") or []
        ver = cat.get("registry_version", 1)
        upd = cat.get("updated_at")
        upd_str = str(upd)[:10] if upd else "—"

        bg = "#f8f9fa" if active else "#fff3f3"
        status_icon = "🟢" if active else "🔴"

        with st.container():
            st.markdown(
                f"""<div style="background:{bg};border:1px solid #e0e0e0;border-radius:8px;
                padding:10px 16px;margin-bottom:8px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <div>
                    <span style="font-weight:600;font-size:15px">{status_icon} {name}</span>
                    &nbsp;<code style="font-size:12px;color:#666">{code}</code>
                    &nbsp;<span style="font-size:12px;color:#888">v{ver} · {upd_str}</span>
                  </div>
                  <div style="font-size:12px;color:#555">
                    📋 {n_sub} подкат. · 🔍 {n_sigs} сигналов
                    · {' '.join(routes[:3]) if routes else '<span style=color:#bbb>все маршруты</span>'}
                  </div>
                </div></div>""",
                unsafe_allow_html=True,
            )
            col_edit, col_dup, col_toggle = st.columns([1, 1, 1])
            with col_edit:
                if st.button("✏️ Редактировать", key=f"cat_edit_{code}", use_container_width=True):
                    st.session_state["cat_editor_mode"] = "edit"
                    st.session_state["cat_editor_code"] = code
                    st.rerun()
            with col_dup:
                if st.button("📋 Дублировать", key=f"cat_dup_{code}", use_container_width=True):
                    st.session_state["cat_editor_mode"] = "create"
                    st.session_state["cat_editor_source"] = code
                    st.session_state["cat_editor_code"] = ""
                    st.rerun()
            with col_toggle:
                lbl = "⏸️ Деактивировать" if active else "✅ Активировать"
                if st.button(lbl, key=f"cat_toggle_{code}", use_container_width=True):
                    st.session_state["cat_toggle_pending"] = code
                    st.session_state["cat_toggle_state"] = not active
                    st.rerun()

    # ─ История версий
    with st.expander("📜 История изменений реестра"):
        history = get_registry_history(crm_db, 10)
        if not history:
            st.caption("История пуста")
        for h in history:
            v = h.get("version", "?")
            hsh = (h.get("registry_hash") or "")[:8]
            desc = h.get("change_description") or ""
            by = h.get("changed_by") or ""
            at = str(h.get("changed_at", ""))[:16]
            st.markdown(
                f"**v{v}** `{hsh}` — {desc or '—'} &nbsp;·&nbsp; *{by}* &nbsp;·&nbsp; {at}",
                unsafe_allow_html=True,
            )


# ─── Полный редактор категории ────────────────────────────────────────────────

def _render_editor(crm_db, mode: str, category_code: str):
    """
    mode: 'edit' | 'create'
    category_code: код редактируемой категории (пустой для создания)
    """
    # Загрузить существующую или взять шаблон
    existing: Dict[str, Any] = {}
    if mode == "edit" and category_code:
        existing = get_category_by_code(crm_db, category_code) or {}
    elif mode == "create" and st.session_state.get("cat_editor_source"):
        src = get_category_by_code(crm_db, st.session_state["cat_editor_source"]) or {}
        existing = dict(src)
        existing["category_code"] = ""
        existing["category_name"] = f"{src.get('category_name', '')} (копия)"
        existing["is_active"] = False
        existing.pop("id", None)

    title = "✏️ Редактировать категорию" if mode == "edit" else "➕ Новая категория"
    st.subheader(title)

    if st.button("← Назад к списку", key="cat_back"):
        _clear_editor_state()
        st.rerun()

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────────
    # Шаги в виде tabs (не wizard, а постоянно видимые секции)
    # ─────────────────────────────────────────────────────────────────────────
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        "1️⃣ Основное",
        "2️⃣ Сигналы",
        "3️⃣ Применимость",
        "4️⃣ Бизнес-роль",
        "5️⃣ Коммерческий вход",
        "6️⃣ Документы",
        "7️⃣ Разделы / Поиск",
        "8️⃣ Извлечение",
    ])

    # ── Tab 1: Основное ──────────────────────────────────────────────────────
    with t1:
        st.markdown("#### Идентификация")
        col_code, col_active = st.columns([3, 1])
        with col_code:
            new_code = st.text_input(
                "category_code *",
                value=existing.get("category_code", ""),
                key="cat_f_code",
                disabled=(mode == "edit"),
                help="Уникальный технический код (snake_case, не изменяется после создания)",
                placeholder="например: heating_hvac",
            )
        with col_active:
            new_active = st.checkbox(
                "Активна",
                value=bool(existing.get("is_active", False)),
                key="cat_f_active",
            )

        new_name = st.text_input(
            "Отображаемое название *",
            value=existing.get("category_name", ""),
            key="cat_f_name",
            placeholder="например: Радиаторы отопления",
        )
        new_desc = st.text_area(
            "Описание",
            value=existing.get("description", ""),
            key="cat_f_desc",
            height=80,
            placeholder="Краткое описание категории для пользователей и AI",
        )
        new_contour = st.selectbox(
            "Контур (contour_code)",
            ["procurement", "computers"],
            index=0 if existing.get("contour_code", "procurement") == "procurement" else 1,
            key="cat_f_contour",
            disabled=(mode == "edit"),
        )

    # ── Tab 2: Синонимы и сигналы ────────────────────────────────────────────
    with t2:
        col_ali, col_pos = st.columns(2)
        with col_ali:
            new_aliases = _signals_editor(
                "🏷️ Aliases / Синонимы",
                "cat_f_aliases",
                existing.get("aliases") or [],
            )
        with col_pos:
            new_pos = _signals_editor(
                "✅ Positive signals (прямые признаки категории)",
                "cat_f_pos",
                existing.get("positive_signals") or [],
            )

        st.markdown("---")
        new_neg = _signals_editor(
            "⚠️ Negative contexts (ложные контексты — НЕ конкурирующие виды работ)",
            "cat_f_neg",
            existing.get("negative_contexts") or [],
        )
        st.caption(
            "💡 Negative context — это текст, при котором данный термин НЕ означает нашу категорию. "
            "Например для LIGHTING: 'осветление воды' (не светильник). "
            "НЕ добавлять 'отопление' — это другая категория, не false positive для lighting."
        )

    # ── Tab 3: Применимость ──────────────────────────────────────────────────
    with t3:
        st.info(
            "🔍 Пустой список = применима КО ВСЕМ значениям. "
            "Заполните только если нужно ограничить."
        )
        new_routes = st.multiselect(
            "Допустимые route profiles",
            options=ALLOWED_ROUTES,
            default=existing.get("applicable_routes") or [],
            format_func=lambda x: ROUTE_LABELS.get(x, x),
            key="cat_f_routes",
        )
        new_obj_types = st.text_area(
            "Допустимые object_types (по одному на строку)",
            value="\n".join(existing.get("applicable_object_types") or []),
            height=80,
            key="cat_f_obj_types",
            placeholder="школа\nдорога\nмост\n(оставить пустым = все)",
        )
        new_proc_types = st.multiselect(
            "Допустимые procurement_types",
            options=ALLOWED_PROCUREMENT_TYPES,
            default=existing.get("applicable_procurement_types") or [],
            format_func=lambda x: PROCUREMENT_LABELS.get(x, x),
            key="cat_f_proc_types",
        )

    # ── Tab 4: Бизнес-роль ──────────────────────────────────────────────────
    with t4:
        new_default_role = st.selectbox(
            "Роль по умолчанию (default_role)",
            options=ALLOWED_ROLES,
            index=ALLOWED_ROLES.index(existing.get("default_role") or "EMBEDDED_MATERIAL"),
            format_func=lambda x: ROLE_LABELS.get(x, x),
            key="cat_f_default_role",
        )
        new_allowed_roles = st.multiselect(
            "Допустимые роли",
            options=ALLOWED_ROLES,
            default=existing.get("allowed_roles") or ["PRIMARY_SUPPLY", "EMBEDDED_MATERIAL"],
            format_func=lambda x: ROLE_LABELS.get(x, x),
            key="cat_f_allowed_roles",
        )

    # ── Tab 5: Коммерческий вход ─────────────────────────────────────────────
    with t5:
        new_entry_points = st.multiselect(
            "Коммерческие точки входа",
            options=ALLOWED_ENTRY_POINTS,
            default=existing.get("commercial_entry_points") or ["DIRECT_SUPPLY"],
            format_func=lambda x: ENTRY_LABELS.get(x, x),
            key="cat_f_entry_points",
        )

    # ── Tab 6: Документы ─────────────────────────────────────────────────────
    with t6:
        new_doc_plan = _doc_plan_editor("cat_f_doc", existing.get("document_search_plan") or [])

    # ── Tab 7: Разделы ──────────────────────────────────────────────────────
    with t7:
        new_sec_plan = _section_plan_editor("cat_f_sec", existing.get("section_search_plan") or [])

    # ── Tab 8: Извлечение ───────────────────────────────────────────────────
    with t8:
        new_extraction = st.multiselect(
            "Поля извлечения",
            options=ALLOWED_EXTRACTION_FIELDS,
            default=existing.get("extraction_fields") or [],
            key="cat_f_extraction",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Preview & Save
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🔍 Preview и сохранение")

    new_obj_types_list = [s.strip() for s in new_obj_types.splitlines() if s.strip()]

    # Собрать contract
    contract = {
        "category_code": new_code,
        "category_name": new_name,
        "description": new_desc,
        "is_active": new_active,
        "contour_code": new_contour,
        "aliases": new_aliases,
        "positive_signals": new_pos,
        "negative_contexts": new_neg,
        "applicable_routes": new_routes,
        "applicable_object_types": new_obj_types_list,
        "applicable_procurement_types": new_proc_types,
        "default_role": new_default_role,
        "allowed_roles": new_allowed_roles,
        "commercial_entry_points": new_entry_points,
        "document_search_plan": new_doc_plan,
        "section_search_plan": new_sec_plan,
        "extraction_fields": new_extraction,
    }

    with st.expander("📋 Полный contract (JSON preview)", expanded=False):
        st.json(contract)

    # ─ STALE preview
    reg_info = get_current_registry_version(crm_db)
    stale_cnt = count_stale_candidates(crm_db, reg_info["hash"])
    affected = preview_stale_objects(crm_db, reg_info["hash"], 5)

    col_info, col_save = st.columns([3, 1])
    with col_info:
        st.info(
            f"ℹ️ Registry сейчас: **v{reg_info['version']}** · hash `{reg_info['hash'] or 'пусто'}`  \n"
            f"После сохранения: **v{reg_info['version'] + 1}** · ~{stale_cnt} assessments станут STALE  \n"
            f"AI reassessment НЕ запускается автоматически."
        )
        if affected:
            st.caption("Примеры объектов, которые могут быть переоценены в будущем:")
            for obj in affected:
                name = (obj.get("auction_name") or "")[:70]
                st.caption(f"  • ID={obj.get('id')} {name}")

    # ─ Валидация
    errors = []
    if not new_code:
        errors.append("category_code обязателен")
    if not new_name:
        errors.append("Название обязательно")
    if mode == "create" and new_code:
        existing_check = get_category_by_code(crm_db, new_code)
        if existing_check:
            errors.append(f"category_code '{new_code}' уже существует")

    with col_save:
        st.write("")
        if errors:
            for e in errors:
                st.error(e)
        else:
            change_reason = st.text_input(
                "Причина изменения",
                key="cat_change_reason",
                placeholder="Например: добавлены сигналы для отопления",
            )
            if st.button("💾 Сохранить", key="cat_save_btn", type="primary", use_container_width=True):
                _save_category(crm_db, mode, existing.get("id"), contract, change_reason)


def _save_category(crm_db, mode: str, existing_id: Optional[int], contract: Dict, reason: str):
    """Сохранить категорию и обновить registry version."""
    try:
        code = contract["category_code"]
        if mode == "create":
            create_category(
                crm_db,
                category_code=code,
                category_name=contract["category_name"],
                contour_code=contract.get("contour_code", "procurement"),
                description=contract.get("description", ""),
                is_active=contract.get("is_active", False),
                aliases=contract.get("aliases"),
                positive_signals=contract.get("positive_signals"),
                negative_contexts=contract.get("negative_contexts"),
                applicable_routes=contract.get("applicable_routes"),
                applicable_object_types=contract.get("applicable_object_types"),
                applicable_procurement_types=contract.get("applicable_procurement_types"),
                default_role=contract.get("default_role", "EMBEDDED_MATERIAL"),
                allowed_roles=contract.get("allowed_roles"),
                commercial_entry_points=contract.get("commercial_entry_points"),
                document_search_plan=contract.get("document_search_plan"),
                section_search_plan=contract.get("section_search_plan"),
                extraction_fields=contract.get("extraction_fields"),
            )
            action = "создана"
        else:
            update_category(
                crm_db,
                existing_id,
                category_name=contract.get("category_name"),
                description=contract.get("description"),
                is_active=contract.get("is_active"),
                aliases=contract.get("aliases"),
                positive_signals=contract.get("positive_signals"),
                negative_contexts=contract.get("negative_contexts"),
                applicable_routes=contract.get("applicable_routes"),
                applicable_object_types=contract.get("applicable_object_types"),
                applicable_procurement_types=contract.get("applicable_procurement_types"),
                default_role=contract.get("default_role"),
                allowed_roles=contract.get("allowed_roles"),
                commercial_entry_points=contract.get("commercial_entry_points"),
                document_search_plan=contract.get("document_search_plan"),
                section_search_plan=contract.get("section_search_plan"),
                extraction_fields=contract.get("extraction_fields"),
            )
            action = "обновлена"

        # Bump registry version
        bump_result = bump_registry_version(
            crm_db,
            change_description=reason or f"Категория {code} {action}",
            changed_by="superuser",
            affected_codes=[code],
        )
        st.success(
            f"✅ Категория **{code}** {action}.  \n"
            f"Registry → **v{bump_result['version']}** · hash `{bump_result['hash']}`"
        )
        _clear_editor_state()
        st.rerun()

    except Exception as e:
        logger.error(f"save_category error: {e}")
        st.error(f"Ошибка сохранения: {e}")


def _handle_toggle(crm_db, code: str, new_state: bool):
    """Активировать/деактивировать категорию."""
    cat = get_category_by_code(crm_db, code)
    if not cat:
        st.error(f"Категория {code} не найдена")
        return
    update_category(crm_db, cat["id"], is_active=new_state)
    action = "активирована" if new_state else "деактивирована"
    bump_registry_version(
        crm_db,
        change_description=f"Категория {code} {action}",
        changed_by="superuser",
        affected_codes=[code],
    )
    st.success(f"Категория **{code}** {action}")
    st.session_state.pop("cat_toggle_pending", None)
    st.session_state.pop("cat_toggle_state", None)
    st.rerun()


def _clear_editor_state():
    for key in ("cat_editor_mode", "cat_editor_code", "cat_editor_source"):
        st.session_state.pop(key, None)


# ─── Главная точка входа ──────────────────────────────────────────────────────

def render_category_registry_page(service=None):
    """Основной entrypoint страницы."""
    st.markdown(
        "<style>.stTabs [data-baseweb='tab']{font-size:13px;padding:6px 12px}</style>",
        unsafe_allow_html=True,
    )

    crm_db = _get_crm_db()
    if not crm_db:
        st.error("CRM база данных недоступна.")
        return

    # Обработать отложенный toggle
    if "cat_toggle_pending" in st.session_state:
        code = st.session_state["cat_toggle_pending"]
        new_state = st.session_state["cat_toggle_state"]
        _handle_toggle(crm_db, code, new_state)
        return

    mode = st.session_state.get("cat_editor_mode")
    code = st.session_state.get("cat_editor_code", "")

    if mode in ("edit", "create"):
        _render_editor(crm_db, mode, code)
    else:
        _render_category_list(crm_db)
