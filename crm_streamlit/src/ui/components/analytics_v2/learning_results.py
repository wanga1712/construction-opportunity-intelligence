"""Additive rendering block for autonomous analysis traces and product findings."""
from __future__ import annotations

import streamlit as st
from typing import Any

def render_learning_results(crm_db: Any, procurement_id: int) -> None:
    """Render the Hunter-Auditor learning loop results in the card."""
    # Fetch latest trace
    traces = crm_db.execute_query(
        """
        SELECT hunter_run_id, auditor_run_id, consensus_state
        FROM crm_v3_autonomous_analysis_traces
        WHERE procurement_id = %s
        ORDER BY id DESC LIMIT 1
        """,
        (procurement_id,),
    )
    if not traces:
        # Show compact indicator if no trace exists
        st.info("Автономный анализ пока недоступен")
        return
    trace = traces[0]
    hunter_run_id = trace.get("hunter_run_id")
    auditor_run_id = trace.get("auditor_run_id")
    consensus = trace.get("consensus_state")

    # Fetch hunter result
    hunter_result = {}
    if hunter_run_id:
        hr = crm_db.execute_query(
            "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
            (hunter_run_id,),
        )
        if hr:
            hunter_result = hr[0].get("validated_model_result") or {}

    # Fetch auditor result
    auditor_result = {}
    if auditor_run_id:
        ar = crm_db.execute_query(
            "SELECT validated_model_result FROM crm_v3_model_inference_runs WHERE id = %s",
            (auditor_run_id,),
        )
        if ar:
            auditor_result = ar[0].get("validated_model_result") or {}

    # Fetch observations
    obs = crm_db.execute_query(
        """
        SELECT document_title, source_document_url, usefulness_label, download_status, parse_status
        FROM crm_v3_document_observations
        WHERE procurement_id = %s
        ORDER BY id ASC
        """,
        (procurement_id,),
    ) or []

    # Fetch product findings matching latest run_id
    products = []
    if hunter_run_id is not None:
        products = crm_db.execute_query(
            """
            SELECT category_code, product_type, product_name_normalized, brand, model,
                   quantity, unit, raw_description, evidence_text, document_name,
                   page, sheet, row_num, position_number
            FROM crm_v3_product_findings
            WHERE procurement_id = %s AND model_run_id = %s AND extractor_role = 'HUNTER'
            ORDER BY id ASC
            """,
            (procurement_id, hunter_run_id),
        ) or []

    with st.container(border=True):
        st.markdown("#### 🔍 АВТОНОМНЫЙ АНАЛИЗ")
        
        # Object sector & type
        obj_sector = hunter_result.get("object_sector") or "—"
        obj_type = hunter_result.get("object_type") or "—"
        obj_subtype = hunter_result.get("object_subtype") or "—"
        st.markdown(f"**Объект:** `{obj_sector}` &rarr; `{obj_type}` &rarr; `{obj_subtype}`")
        
        # Procurement mode
        mode = hunter_result.get("procurement_mode") or "—"
        st.markdown(f"**Режим закупки:** `{mode}`")
        
        # Categories
        cats = hunter_result.get("categories") or []
        st.markdown(f"**Наши категории:** {', '.join(f'`{c}`' for c in cats) if cats else '—'}")
        
        # Document coverage
        total_docs = len(obs)
        failed_docs = sum(1 for o in obs if o.get("usefulness_label") in ("DOWNLOAD_FAILED", "PARSE_FAILED"))
        if total_docs > 0:
            searched_docs = total_docs - failed_docs
            st.markdown(f"**Документы исследованы:** `{searched_docs} / {total_docs}`")
            if failed_docs > 0:
                st.markdown(f"⚠️ `{failed_docs}` документа не удалось прочитать  \n*Вывод неполный*")
        else:
            st.markdown("**Документы исследованы:** `0 / 0` (нет документов)")

        # Products
        st.markdown("**Найденные товары / материалы:**")
        if products:
            for idx, p in enumerate(products, 1):
                p_name = p.get("product_name_normalized") or p.get("product_type") or "Товар"
                brand = f" (Бренд: {p['brand']})" if p.get("brand") else ""
                model = f" (Модель: {p['model']})" if p.get("model") else ""
                qty = f" &nbsp; **{p['quantity']}** {p['unit']}" if p.get("quantity") is not None else ""
                
                doc_name = p.get("document_name") or "Документ"
                doc_url = next((o.get("source_document_url") for o in obs if o.get("document_title") == doc_name), None)
                doc_link = f"[{doc_name}]({doc_url})" if doc_url else doc_name
                
                loc_parts = []
                if p.get("page"): loc_parts.append(f"стр. {p['page']}")
                if p.get("sheet"): loc_parts.append(f"лист \"{p['sheet']}\"")
                if p.get("row_num"): loc_parts.append(f"строка {p['row_num']}")
                if p.get("position_number"): loc_parts.append(f"поз. {p['position_number']}")
                loc_str = ", ".join(loc_parts) or "—"
                
                st.markdown(
                    f"{idx}. **{p_name}**{brand}{model}{qty}  \n"
                    f"&nbsp; &nbsp; Категория: `{p.get('category_code')}`  \n"
                    f"&nbsp; &nbsp; Найдено в: {doc_link} ({loc_str})  \n"
                    f"&nbsp; &nbsp; Цитата: *\"{p.get('evidence_text') or '—'}\"*",
                    unsafe_allow_html=True
                )
        else:
            if total_docs > 0 and failed_docs == 0:
                st.markdown(f"*По нашим товарным категориям ничего не найдено после полного исследования {total_docs}/{total_docs} документов*")
            else:
                st.markdown("*Товары / материалы не найдены*")

        st.markdown("---")
        st.markdown(f"**Вердикт Hunter:** `{hunter_result.get('medal_hypothesis') or '—'}` (уверенность {hunter_result.get('confidence', 0.0):.0%})")
        st.markdown(f"**Вердикт Auditor:** `{auditor_result.get('medal', {}).get('verdict') or '—'}` (consensus: `{consensus}`)")
