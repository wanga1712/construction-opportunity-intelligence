"""Helper to render AI / Categories tab in CRM compact card."""
import streamlit as st
import json
from datetime import datetime

_AI_STATE_LABELS = {
    "UNASSESSED": ("🔘", "AI-классификация ещё не выполнена"),
    "INCOMPLETE":  ("⚠️", "AI-оценка неполная / результат не сохранён"),
    "FAILED":      ("❌", "Ошибка выполнения AI-оценки"),
    "ASSESSED":    ("✅", "AI-оценка выполнена"),
}


def render_ai_tab(crm_db, procurement_id: int, proposed_route: str,
                  proposed_obj_type: str, proposed_proc_type: str,
                  ai_reasons: str, eff_opps: list,
                  ai_status: str = "ASSESSED") -> None:
    st.markdown("### 🤖 Классификация AI и категории возможностей")

    icon, label = _AI_STATE_LABELS.get(ai_status, ("🔘", ai_status))

    # Show AI state banner for non-ASSESSED states
    if ai_status == "UNASSESSED":
        st.warning(f"{icon} **{label}**")
        st.caption("Объект ещё не прошёл AI-классификацию. Маршрут, тип объекта и категории недоступны.")
        _render_edit_section(crm_db, procurement_id, eff_opps)
        return

    if ai_status == "INCOMPLETE":
        st.error(f"{icon} **{label}**")
        st.caption(
            "AI завершил обработку, но normalized_result не был сохранён. "
            "Это указывает на ошибку в pipeline. Требуется повторная оценка."
        )
        _render_edit_section(crm_db, procurement_id, eff_opps)
        return

    if ai_status == "FAILED":
        st.error(f"{icon} **{label}**")
        st.caption("AI-оценка завершилась с ошибкой. Требуется повторная оценка.")
        _render_edit_section(crm_db, procurement_id, eff_opps)
        return

    # ASSESSED — show full data
    st.markdown(
        f"**Маршрут (Route):** `{proposed_route}`<br>"
        f"**Тип объекта:** `{proposed_obj_type}`<br>"
        f"**Способ закупки:** `{proposed_proc_type}`<br>"
        f"**ИИ Обоснование:** {ai_reasons}",
        unsafe_allow_html=True
    )

    st.markdown("#### Список возможностей (Category Opportunities):")
    if not eff_opps:
        st.info("✓ AI-оценка выполнена. Целевые категории не обнаружены.")
    else:
        # Таблица категорий
        table_rows = []
        for opp in eff_opps:
            table_rows.append({
                "Категория":   opp.get("category_code"),
                "Подкатегория": opp.get("subcategory_code") or "—",
                "Статус":      opp.get("opportunity_status"),
                "Роль":        opp.get("expected_role"),
                "Вход":        opp.get("commercial_entry_point"),
                "Объем":       opp.get("expected_volume"),
                "Приоритет":   opp.get("priority"),
                "Action":      opp.get("research_action"),
            })
        st.table(table_rows)

    _render_edit_section(crm_db, procurement_id, eff_opps)


def _render_edit_section(crm_db, procurement_id: int, eff_opps: list) -> None:
    """Manual category override controls (always available regardless of AI state)."""
    st.markdown("---")
    st.markdown("#### 🛠️ Редактирование категорий")
    
    action = st.radio(
        "Выберите действие:",
        options=["Изменить/переопределить категорию", "Добавить новую категорию", "Удалить категорию"],
        key=f"cat_action_{procurement_id}"
    )
    
    user_name = "SuperUser"
    
    # Загрузим доступные категории из CRM для добавления
    try:
        active_cats = crm_db.execute_query("SELECT DISTINCT category_code FROM crm_product_categories")
        cat_options = [c["category_code"] for c in active_cats] if active_cats else ["lighting", "flooring", "drainage_water_management", "composites"]
    except Exception:
        cat_options = ["lighting", "flooring", "drainage_water_management", "composites"]

    if action == "Изменить/переопределить категорию":
        if not eff_opps:
            st.info("Нет категорий для изменения.")
            return
            
        selected_cat = st.selectbox(
            "Выберите категорию для редактирования:",
            options=[opp["category_code"] for opp in eff_opps],
            key=f"edit_cat_sel_{procurement_id}"
        )
        
        orig_opp = next((o for o in eff_opps if o["category_code"] == selected_cat), {})
        
        subcat = st.text_input("Подкатегория:", value=orig_opp.get("subcategory_code") or "", key=f"edit_sub_{procurement_id}")
        opp_status = st.selectbox(
            "Статус возможности:",
            options=["CONFIRMED_SOURCE", "LIKELY", "POSSIBLE", "UNLIKELY", "ABSENT", "MANUAL_REVIEW"],
            index=["CONFIRMED_SOURCE", "LIKELY", "POSSIBLE", "UNLIKELY", "ABSENT", "MANUAL_REVIEW"].index(orig_opp.get("opportunity_status", "POSSIBLE")),
            key=f"edit_status_{procurement_id}"
        )
        role = st.selectbox(
            "Роль категории:",
            options=["PRIMARY_SUPPLY", "EMBEDDED_MATERIAL", "CONSUMABLE", "OBJECT_OF_RESEARCH", "AUXILIARY_CONTEXT", "ABSENT", "UNKNOWN"],
            index=["PRIMARY_SUPPLY", "EMBEDDED_MATERIAL", "CONSUMABLE", "OBJECT_OF_RESEARCH", "AUXILIARY_CONTEXT", "ABSENT", "UNKNOWN"].index(orig_opp.get("expected_role", "PRIMARY_SUPPLY")),
            key=f"edit_role_{procurement_id}"
        )
        entry = st.selectbox(
            "Коммерческая точка входа:",
            options=["DIRECT_SUPPLY", "SUPPLIER", "SUB_CONTRACTOR", "CONTRACTOR_PARTNER", "NO_ENTRY", "UNKNOWN"],
            index=["DIRECT_SUPPLY", "SUPPLIER", "SUB_CONTRACTOR", "CONTRACTOR_PARTNER", "NO_ENTRY", "UNKNOWN"].index(orig_opp.get("commercial_entry_point", "DIRECT_SUPPLY")),
            key=f"edit_entry_{procurement_id}"
        )
        vol = st.selectbox(
            "Ожидаемый объем:",
            options=["HIGH", "MEDIUM", "LOW", "UNKNOWN"],
            index=["HIGH", "MEDIUM", "LOW", "UNKNOWN"].index(orig_opp.get("expected_volume", "UNKNOWN")),
            key=f"edit_vol_{procurement_id}"
        )
        prio = st.number_input("Приоритет (вес):", value=float(orig_opp.get("priority") or 1.0), key=f"edit_prio_{procurement_id}")
        res_action = st.selectbox(
            "Глубина исследования (Research Action):",
            options=["SKIP", "METADATA_ONLY", "LIGHT_RESEARCH", "PRIORITY_DOCS", "DEEP_RESEARCH"],
            index=["SKIP", "METADATA_ONLY", "LIGHT_RESEARCH", "PRIORITY_DOCS", "DEEP_RESEARCH"].index(orig_opp.get("research_action", "METADATA_ONLY")),
            key=f"edit_action_{procurement_id}"
        )
        
        reason = st.text_input("Причина изменения (обязательно):", key=f"edit_reason_{procurement_id}")
        
        if st.button("💾 Сохранить изменения", key=f"save_edit_btn_{procurement_id}"):
            if not reason.strip():
                st.error("⚠️ Укажите причину изменений!")
                return
                
            try:
                # 1. Запись в crm_manual_category_overrides
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_category_overrides (
                        procurement_id, category_code, subcategory_code, opportunity_status, expected_role,
                        commercial_entry_point, expected_volume, priority, research_action, manual_candidate_level,
                        manual_reason, reviewed_by, reviewed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, NOW())
                    ON CONFLICT (procurement_id, category_code) DO UPDATE SET
                        subcategory_code = EXCLUDED.subcategory_code,
                        opportunity_status = EXCLUDED.opportunity_status,
                        expected_role = EXCLUDED.expected_role,
                        commercial_entry_point = EXCLUDED.commercial_entry_point,
                        expected_volume = EXCLUDED.expected_volume,
                        priority = EXCLUDED.priority,
                        research_action = EXCLUDED.research_action,
                        manual_reason = EXCLUDED.manual_reason,
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = NOW(),
                        updated_at = NOW()
                    """,
                    (procurement_id, selected_cat, subcat or None, opp_status, role, entry, vol, prio, res_action, reason, user_name)
                )
                
                # 2. Пишем в аудит
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_assessments_audit (procurement_id, action_type, user_name, comment)
                    VALUES (%s, 'UPDATE_CATEGORY_OVERRIDE', %s, %s)
                    """,
                    (procurement_id, user_name, f"Изменена категория {selected_cat}: {reason}")
                )
                st.success("Категория обновлена!")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка сохранения: {e}")

    elif action == "Добавить новую категорию":
        new_cat = st.selectbox("Выберите новую категорию:", options=cat_options, key=f"new_cat_{procurement_id}")
        subcat = st.text_input("Подкатегория:", key=f"new_sub_{procurement_id}")
        opp_status = st.selectbox("Статус возможности:", options=["CONFIRMED_SOURCE", "LIKELY", "POSSIBLE", "UNLIKELY", "ABSENT", "MANUAL_REVIEW"], key=f"new_status_{procurement_id}")
        role = st.selectbox("Роль категории:", options=["PRIMARY_SUPPLY", "EMBEDDED_MATERIAL", "CONSUMABLE", "OBJECT_OF_RESEARCH", "AUXILIARY_CONTEXT", "ABSENT", "UNKNOWN"], key=f"new_role_{procurement_id}")
        entry = st.selectbox("Коммерческая точка входа:", options=["DIRECT_SUPPLY", "SUPPLIER", "SUB_CONTRACTOR", "CONTRACTOR_PARTNER", "NO_ENTRY", "UNKNOWN"], key=f"new_entry_{procurement_id}")
        vol = st.selectbox("Ожидаемый объем:", options=["HIGH", "MEDIUM", "LOW", "UNKNOWN"], key=f"new_vol_{procurement_id}")
        prio = st.number_input("Приоритет (вес):", value=1.0, key=f"new_prio_{procurement_id}")
        res_action = st.selectbox("Глубина исследования (Research Action):", options=["SKIP", "METADATA_ONLY", "LIGHT_RESEARCH", "PRIORITY_DOCS", "DEEP_RESEARCH"], key=f"new_action_{procurement_id}")
        reason = st.text_input("Причина добавления (обязательно):", key=f"new_reason_{procurement_id}")
        
        if st.button("➕ Добавить категорию", key=f"add_cat_btn_{procurement_id}"):
            if not reason.strip():
                st.error("⚠️ Укажите причину добавления категории!")
                return
                
            try:
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_category_overrides (
                        procurement_id, category_code, subcategory_code, opportunity_status, expected_role,
                        commercial_entry_point, expected_volume, priority, research_action, manual_reason, reviewed_by, reviewed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (procurement_id, category_code) DO UPDATE SET
                        subcategory_code = EXCLUDED.subcategory_code,
                        opportunity_status = EXCLUDED.opportunity_status,
                        expected_role = EXCLUDED.expected_role,
                        commercial_entry_point = EXCLUDED.commercial_entry_point,
                        expected_volume = EXCLUDED.expected_volume,
                        priority = EXCLUDED.priority,
                        research_action = EXCLUDED.research_action,
                        manual_reason = EXCLUDED.manual_reason,
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = NOW(),
                        updated_at = NOW()
                    """,
                    (procurement_id, new_cat, subcat or None, opp_status, role, entry, vol, prio, res_action, reason, user_name)
                )
                
                # Записываем в аудит
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_assessments_audit (procurement_id, action_type, user_name, comment)
                    VALUES (%s, 'ADD_CATEGORY', %s, %s)
                    """,
                    (procurement_id, user_name, f"Добавлена категория {new_cat}: {reason}")
                )
                st.success("Категория добавлена!")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка сохранения: {e}")

    elif action == "Удалить категорию":
        if not eff_opps:
            st.info("Нет категорий для удаления.")
            return
            
        del_cat = st.selectbox(
            "Выберите категорию для удаления:",
            options=[opp["category_code"] for opp in eff_opps],
            key=f"del_cat_sel_{procurement_id}"
        )
        reason = st.text_input("Причина удаления (обязательно):", key=f"del_reason_{procurement_id}")
        
        if st.button("🗑️ Удалить", key=f"del_cat_btn_{procurement_id}", type="primary"):
            if not reason.strip():
                st.error("⚠️ Укажите причину удаления!")
                return
                
            try:
                # Мягкое удаление: ставим статус ABSENT
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_category_overrides (
                        procurement_id, category_code, opportunity_status, expected_role, commercial_entry_point,
                        expected_volume, research_action, manual_reason, reviewed_by, reviewed_at
                    ) VALUES (%s, %s, 'ABSENT', 'ABSENT', 'NO_ENTRY', 'UNKNOWN', 'SKIP', %s, %s, NOW())
                    ON CONFLICT (procurement_id, category_code) DO UPDATE SET
                        opportunity_status = 'ABSENT',
                        expected_role = 'ABSENT',
                        commercial_entry_point = 'NO_ENTRY',
                        research_action = 'SKIP',
                        manual_reason = EXCLUDED.manual_reason,
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = NOW(),
                        updated_at = NOW()
                    """,
                    (procurement_id, del_cat, reason, user_name)
                )
                
                # Записываем в аудит
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_assessments_audit (procurement_id, action_type, user_name, comment)
                    VALUES (%s, 'DELETE_CATEGORY', %s, %s)
                    """,
                    (procurement_id, user_name, f"Удалена категория {del_cat}: {reason}")
                )
                st.success("Категория удалена!")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка удаления: {e}")
