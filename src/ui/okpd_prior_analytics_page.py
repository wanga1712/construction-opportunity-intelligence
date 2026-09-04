"""Read-only diagnostics and analytics page for OKPD Prior Learning V1.

Displays:
- Training corpus statistics
- OKPD Root hierarchy distribution
- Model quality metrics (PR-AUC, ROC-AUC, Lift@K%, Recall@K%)
- Band performance (GOLD, SILVER, BRONZE, WOOD)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
import streamlit as st

from src.learning.okpd_prior.model import MODEL_NAME, MODEL_VERSION


def render_okpd_prior_analytics_page(
    report_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Renders the OKPD Prior Learning V1 Diagnostics and Model Evaluation Dashboard."""
    st.title("📊 Диагностика модели: OKPD Prior Learning V1")
    st.caption("Теневая оценка вероятности полезной документарной находки P(RESEARCH_HIT) по кодам ОКПД2")

    # If no data provided directly, attempt to load from default report location
    if report_data is None:
        report_path = "data/okpd_prior_models/training_report_v1.json"
        tmp_report_path = "/tmp/okpd_prior_models/training_report_v1.json"
        
        target_path = report_path if os.path.exists(report_path) else tmp_report_path
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                report_data = json.load(f)

    if not report_data:
        st.info("ℹ️ Отчет об обучении модели еще не сгенерирован. Запустите offline-обучение для формирования метрик.")
        return

    # 1. Overview & Snapshot Header
    ds = report_data.get("dataset", {})
    st.markdown("### 📁 Обучающий корпус (Training Corpus)")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Всего исследованных", ds.get("total_procurements", 0))
    with col2:
        st.metric("Положительные (Hits)", ds.get("positive_count", 0))
    with col3:
        st.metric("Безопасные отрицательные", ds.get("safe_negative_count", 0))
    with col4:
        st.metric("Исключено (Unresolved)", ds.get("unresolved_excluded_count", 0))
    with col5:
        st.metric("Базовая конверсия (Hit Rate)", f"{ds.get('positive_rate', 0.0) * 100:.1f}%")

    st.markdown(
        f"**Snapshot SHA256:** `{report_data.get('dataset_snapshot_sha256', '—')}` · "
        f"**Сплит:** Train={ds.get('train_rows', 0)}, Val={ds.get('val_rows', 0)}, Holdout={ds.get('holdout_rows', 0)}"
    )

    st.divider()

    # 2. Model Quality Metrics
    st.markdown("### 🎯 Качество ранжирования модели (Model Quality)")
    m_metrics = report_data.get("model_metrics", {}).get("holdout") or report_data.get("model_metrics", {}).get("all", {})
    b_metrics = report_data.get("baseline_metrics", {}).get("holdout") or report_data.get("baseline_metrics", {}).get("all", {})

    q_col1, q_col2, q_col3, q_col4, q_col5 = st.columns(5)
    with q_col1:
        st.metric("PR-AUC", f"{m_metrics.get('pr_auc', 0.0):.4f}")
    with q_col2:
        st.metric("ROC-AUC", f"{m_metrics.get('roc_auc', 0.0):.4f}")
    with q_col3:
        st.metric("Lift @ 10%", f"{m_metrics.get('lift_at_10', 1.0):.2f}x")
    with q_col4:
        st.metric("Recall @ 10%", f"{m_metrics.get('recall_at_10', 0.0) * 100:.1f}%")
    with q_col5:
        st.metric("Recall @ 30%", f"{m_metrics.get('recall_at_30', 0.0) * 100:.1f}%")

    st.caption(f"Статус проверки качества: **{report_data.get('model_result', '—')}**")

    st.divider()

    # 3. Band Performance (Medals)
    st.markdown("### 🏅 Фактическая эффективность медальных корзин (Band Performance)")
    bands = report_data.get("bands", {})
    b_counts = bands.get("counts", {})
    b_hits = bands.get("hits", {})

    band_rows = []
    base_rate = ds.get("positive_rate", 0.05) or 0.05
    for b_name in ("GOLD", "SILVER", "BRONZE", "WOOD"):
        cnt = b_counts.get(b_name, 0)
        hits = b_hits.get(b_name, 0)
        hit_rate = (hits / cnt) if cnt > 0 else 0.0
        lift = (hit_rate / base_rate) if base_rate > 0 else 1.0
        band_rows.append({
            "Корзина": b_name,
            "Количество": cnt,
            "Подтвержденных находок": hits,
            "Фактический Hit Rate": f"{hit_rate * 100:.1f}%",
            "Lift к базовой частоте": f"{lift:.2f}x",
        })

    st.table(band_rows)

    st.divider()

    # 4. OKPD Root Distribution Table
    st.markdown("### 🌲 Статистика по корням ОКПД2 (OKPD Root Table)")
    roots = report_data.get("roots_table", [])
    if roots:
        root_table_data = [
            {
                "Корень ОКПД2": r.get("prefix"),
                "Исследовано закупок": r.get("total"),
                "С находками (+)": r.get("positive"),
                "Без находок (-)": r.get("negative"),
                "Фактический Hit Rate": f"{r.get('raw_hit_rate', 0.0) * 100:.1f}%",
                "Сглаженный Prior": f"{r.get('smoothed_hit_rate', 0.0) * 100:.1f}%",
            }
            for r in roots
        ]
        st.dataframe(root_table_data, use_container_width=True)
    else:
        st.caption("Таблица корней пуста.")
