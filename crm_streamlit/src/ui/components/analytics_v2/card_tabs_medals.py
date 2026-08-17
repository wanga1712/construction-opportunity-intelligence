"""Helper to render Medals tab in CRM compact card."""
import streamlit as st
import json
from datetime import datetime

_LEVEL_RANKS = {"GOLD": 4, "SILVER": 3, "BRONZE": 2, "WOOD": 1, None: 0}
_MEDAL_EMOJI  = {"GOLD": "🥇", "SILVER": "🥈", "BRONZE": "🥉", "WOOD": "🪵"}


def render_medals_tab(crm_db, procurement_id: int, eff_opps: list,
                      ai_cand_medal: str | None, ai_cand_score: float | None,
                      ai_reasons: str, ai_status: str = "ASSESSED") -> None:
    st.markdown("### 🏅 Сравнение и корректировка медалей")

    # ── State guard ────────────────────────────────────────────────────────
    if ai_status == "UNASSESSED":
        st.warning("🔘 **AI-оценка не выполнена. Медали недоступны.**")
        st.caption("После выполнения AI-классификации здесь появятся медали по категориям.")
        return

    if ai_status == "INCOMPLETE":
        st.error("⚠️ **AI-оценка неполная. Медали временно недоступны.**")
        st.caption("Результат AI не был сохранён. Требуется повторная оценка.")
        return

    if ai_status == "FAILED":
        st.error("❌ **AI-оценка завершилась с ошибкой. Медали недоступны.**")
        return

    # ── ASSESSED — show medals ─────────────────────────────────────────────
    # 1. AI-оценка (на уровне закупки)
    medal_disp  = _MEDAL_EMOJI.get(ai_cand_medal, "") + f" {ai_cand_medal}" if ai_cand_medal else "— (нет)"
    score_disp  = f"{ai_cand_score:.2f}/100" if ai_cand_score is not None else "—"
    st.markdown(
        f'<div style="background:#f1f5f9; padding: 10px; border-radius: 4px; font-size:13px; margin-bottom: 12px;">'
        f'🤖 <b>AI (procurement level):</b> <span style="font-weight:bold;">{medal_disp}</span>'
        f' ({score_disp})<br>'
        f'<i>Обоснование AI:</i> {ai_reasons}'
        f'</div>',
        unsafe_allow_html=True
    )

    # 2. Per-category medals
    st.markdown("#### Медали по категориям:")

    selected_medals: dict[str, str] = {}

    for idx, opp in enumerate(eff_opps):
        cat_code  = opp.get("category_code")
        opp_lvl   = opp.get("candidate_level")    # No "or WOOD" fallback
        opp_score = opp.get("candidate_score")

        lvl_disp  = (_MEDAL_EMOJI.get(opp_lvl, "") + f" {opp_lvl}") if opp_lvl else "— (нет)"
        scr_disp  = f"{opp_score:.2f}" if opp_score is not None else "—"

        col_cat, col_sel = st.columns([2, 1])
        with col_cat:
            st.markdown(f"**{cat_code}** ({opp.get('opportunity_status')} · {scr_disp} баллов)")
            st.caption(f"Текущая медаль: {lvl_disp}")
            if opp.get("manual_override"):
                st.caption(f"🖊 Ручной override: {opp.get('manual_reason') or '—'}")

        with col_sel:
            selected_medals[cat_code] = st.selectbox(
                f"Медаль для {cat_code}",
                options=["Использовать ИИ (без изменений)", "GOLD", "SILVER", "BRONZE", "WOOD"],
                index=0,
                key=f"medal_sel_{procurement_id}_{cat_code}_{idx}"
            )
            
    # 3. Текстовое поле обоснования (обязательно)
    reason = st.text_area(
        "Обоснование ручного переопределения (обязательно при изменении медали):",
        key=f"medal_reason_{procurement_id}"
    )
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("💾 Сохранить медали", key=f"save_medals_btn_{procurement_id}", use_container_width=True):
            # Проверяем, изменилось ли что-то
            any_changed = False
            for cat_code, val in selected_medals.items():
                if val != "Использовать ИИ (без изменений)":
                    any_changed = True
                    
            if any_changed and not reason.strip():
                st.error("⚠️ Укажите причину изменения оценки в текстовом поле!")
                return
                
            user_name = "SuperUser"
            
            try:
                # 1. Загружаем или создаем запись в crm_manual_overrides
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_overrides (procurement_id, business_relevance, overall_research_action, reviewed_by, reviewed_at, review_status)
                    VALUES (%s, 'HIGH', 'PRIORITY_DOCS', %s, NOW(), 'PENDING_REVIEW')
                    ON CONFLICT (procurement_id) DO UPDATE SET
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = NOW(),
                        review_status = 'PENDING_REVIEW',
                        updated_at = NOW()
                    """,
                    (procurement_id, user_name)
                )
                
                # 2. Сохраняем переопределения категорий
                for cat_code, val in selected_medals.items():
                    if val != "Использовать ИИ (без изменений)":
                        # Ищем категорию в eff_opps
                        orig_opp = next((o for o in eff_opps if o["category_code"] == cat_code), {})
                        
                        # Сохраняем в crm_manual_category_overrides
                        crm_db.execute_update(
                            """
                            INSERT INTO crm_manual_category_overrides (
                                procurement_id, category_code, subcategory_code, opportunity_status, expected_role,
                                commercial_entry_point, expected_volume, priority, research_action, manual_candidate_level,
                                manual_reason, reviewed_by, reviewed_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (procurement_id, category_code) DO UPDATE SET
                                manual_candidate_level = EXCLUDED.manual_candidate_level,
                                manual_reason = EXCLUDED.manual_reason,
                                reviewed_by = EXCLUDED.reviewed_by,
                                reviewed_at = NOW(),
                                updated_at = NOW()
                            """,
                            (
                                procurement_id, cat_code, orig_opp.get("subcategory_code"),
                                orig_opp.get("opportunity_status", "POSSIBLE"), orig_opp.get("expected_role", "PRIMARY_SUPPLY"),
                                orig_opp.get("commercial_entry_point", "DIRECT_SUPPLY"), orig_opp.get("expected_volume", "HIGH"),
                                float(orig_opp.get("priority") or 1.0), orig_opp.get("research_action", "METADATA_ONLY"),
                                val, reason, user_name
                            )
                        )
                
                # 3. Записываем в аудит
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_assessments_audit (procurement_id, action_type, user_name, original_value, corrected_value, comment)
                    VALUES (%s, 'UPDATE_MEDALS', %s, NULL, %s, %s)
                    """,
                    (procurement_id, user_name, json.dumps(selected_medals), reason)
                )
                
                # 4. Обновляем crm_procurements через раннер (вызовем его внутреннее обновление)
                # Вычислим лучшую эффективную медаль
                best_level = None
                for opp in eff_opps:
                    opp_lvl = selected_medals.get(opp["category_code"], opp.get("candidate_level"))
                    if opp_lvl == "Использовать ИИ (без изменений)":
                        opp_lvl = opp.get("candidate_level")
                    if level_ranks.get(opp_lvl, 0) > level_ranks.get(best_level, 0):
                        best_level = opp_lvl
                        
                crm_db.execute_update(
                    """
                    UPDATE crm_procurements SET
                        qualification_state = 'candidate',
                        candidate_level = %s,
                        manual_override = TRUE,
                        crm_updated_at = NOW()
                    WHERE id = %s
                    """,
                    (best_level, procurement_id)
                )
                
                st.success("Медали сохранены успешно!")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка сохранения: {e}")

    with col2:
        if st.button("❌ НЕ НАШ ПРОФИЛЬ", key=f"not_profile_btn_{procurement_id}", use_container_width=True, type="primary"):
            user_name = "SuperUser"
            try:
                # Ставим бизнес-релевантность OUT_OF_PROFILE
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_overrides (procurement_id, business_relevance, overall_research_action, reviewed_by, reviewed_at, review_status)
                    VALUES (%s, 'OUT_OF_PROFILE', 'SKIP', %s, NOW(), 'PENDING_REVIEW')
                    ON CONFLICT (procurement_id) DO UPDATE SET
                        business_relevance = 'OUT_OF_PROFILE',
                        overall_research_action = 'SKIP',
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = NOW(),
                        review_status = 'PENDING_REVIEW',
                        updated_at = NOW()
                    """,
                    (procurement_id, user_name)
                )
                
                # Добавляем во все категории в оверайдах статус ABSENT
                for opp in eff_opps:
                    cat_code = opp.get("category_code")
                    crm_db.execute_update(
                        """
                        INSERT INTO crm_manual_category_overrides (
                            procurement_id, category_code, opportunity_status, expected_role,
                            commercial_entry_point, expected_volume, research_action, manual_reason, reviewed_by, reviewed_at
                        ) VALUES (%s, %s, 'ABSENT', 'ABSENT', 'NO_ENTRY', 'UNKNOWN', 'SKIP', 'Отмечено вне профиля', %s, NOW())
                        ON CONFLICT (procurement_id, category_code) DO UPDATE SET
                            opportunity_status = 'ABSENT',
                            expected_role = 'ABSENT',
                            commercial_entry_point = 'NO_ENTRY',
                            research_action = 'SKIP',
                            manual_reason = 'Отмечено вне профиля',
                            reviewed_by = EXCLUDED.reviewed_by,
                            reviewed_at = NOW(),
                            updated_at = NOW()
                        """,
                        (procurement_id, cat_code, user_name)
                    )
                
                # Пишем в аудит
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_assessments_audit (procurement_id, action_type, user_name, comment)
                    VALUES (%s, 'MARK_OUT_OF_PROFILE', %s, 'Объект отмечен вне профиля')
                    """,
                    (procurement_id, user_name)
                )
                
                # Обновляем crm_procurements
                crm_db.execute_update(
                    """
                    UPDATE crm_procurements SET
                        qualification_state = 'out_of_profile',
                        candidate_level = NULL,
                        manual_override = TRUE,
                        crm_updated_at = NOW()
                    WHERE id = %s
                    """,
                    (procurement_id,)
                )
                
                st.success("Объект отмечен как вне профиля.")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка: {e}")
                
    with col3:
        if st.button("✓ Утвердить (APPROVED)", key=f"approve_btn_{procurement_id}", use_container_width=True):
            user_name = "SuperUser"
            try:
                # 1. Меняем статус на APPROVED в overrides
                crm_db.execute_update(
                    "UPDATE crm_manual_overrides SET review_status = 'APPROVED' WHERE procurement_id = %s",
                    (procurement_id,)
                )
                # 2. Обновляем аудит
                crm_db.execute_update(
                    """
                    INSERT INTO crm_manual_assessments_audit (procurement_id, action_type, user_name, comment, approved_for_training)
                    VALUES (%s, 'APPROVE_TRAINING', %s, 'Утверждено суперпользователем для обучения', TRUE)
                    """,
                    (procurement_id, user_name)
                )
                st.success("Успешно утверждено!")
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка утверждения: {e}")

