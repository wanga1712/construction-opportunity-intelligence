"""????? ???????? AI-???????? ? ?????? ??????????? ?????????."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.services.companies_service import CompaniesService
from src.services.docs_match_preview import confirmed_product_groups
from src.services.object_pipeline_stage import PIPELINE_STAGE_OPTIONS
from src.ui.session_deps import get_objects_service

_REVIEW_DIR = Path("/opt/CRM_Streamlit/data/ai_review")
_REVIEW_FILE = _REVIEW_DIR / "manual_corrections.jsonl"
_REASONS = [
    "wrong_object_type",
    "wrong_stage",
    "wrong_product_category",
    "wrong_material",
    "wrong_quantity",
    "duplicate",
    "insufficient_evidence",
    "low_volume",
    "wrong_region",
    "late_stage",
    "not_commercially_relevant",
    "hallucinated_value",
]
_REVIEW_STATUSES = [
    "ai_generated",
    "manager_confirmed",
    "manager_corrected",
    "manager_rejected",
    "auto_confirmed_by_rule",
    "queued_for_training",
    "included_in_training",
]


def _product_label_map(service) -> dict[str, str]:
    groups = service.dynamic_product_groups(include_computers=False)
    return {code: label for code, label in groups}


def _stage_map() -> dict[str, str]:
    return {code: label for code, label in PIPELINE_STAGE_OPTIONS}


def _build_review_rows(service) -> pd.DataFrame:
    objects_service = get_objects_service(service)
    rows = []
    product_map = _product_label_map(objects_service)
    stage_map = _stage_map()
    for item in objects_service.all_objects():
        groups = sorted(confirmed_product_groups(item))
        if not groups and not item.ai_priority_score:
            continue
        rows.append(
            {
                "object_key": item.key,
                "object_name": item.name,
                "stage_ai": stage_map.get(item.pipeline_stage_code or "news_signal", item.pipeline_stage_code or "news_signal"),
                "level_ai": item.quality_tier or "wood",
                "category_ai": ", ".join(product_map.get(code, code) for code in groups[:3]) or "?? ??????????",
                "ai_score": int(item.ai_priority_score or 0),
                "confidence": round(float((item.ai_classification_confidence or 0) / 100.0), 2),
                "confirmed": False,
                "corrected_stage": stage_map.get(item.pipeline_stage_code or "news_signal", item.pipeline_stage_code or "news_signal"),
                "corrected_level": item.quality_tier or "wood",
                "corrected_category": ", ".join(product_map.get(code, code) for code in groups[:1]) or "?? ??????????",
                "review_status": "ai_generated",
                "correction_reason": "",
                "manager_comment": "",
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=[
            "object_key", "object_name", "stage_ai", "level_ai", "category_ai", "ai_score", "confidence",
            "confirmed", "corrected_stage", "corrected_level", "corrected_category", "review_status",
            "correction_reason", "manager_comment",
        ])
    return frame.sort_values(["ai_score", "confidence"], ascending=[False, False]).head(200)


def _save_review_events(frame: pd.DataFrame) -> int:
    _REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    with _REVIEW_FILE.open("a", encoding="utf-8") as fh:
        for row in frame.to_dict("records"):
            if not row.get("confirmed") and not row.get("correction_reason") and not row.get("manager_comment"):
                continue
            payload = {
                "training_event_id": int(datetime.now().timestamp() * 1000),
                "object_key": row["object_key"],
                "object_name": row["object_name"],
                "model_name": "qwen2.5-3b",
                "prompt_version": "object_classifier_v7",
                "model_output": {
                    "stage": row.get("stage_ai"),
                    "card_level": row.get("level_ai"),
                    "product_category": row.get("category_ai"),
                    "score": row.get("ai_score"),
                },
                "manager_output": {
                    "stage": row.get("corrected_stage"),
                    "card_level": row.get("corrected_level"),
                    "product_category": row.get("corrected_category"),
                },
                "correction_reason": row.get("correction_reason") or "manager_review",
                "manager_comment": row.get("manager_comment") or "",
                "review_status": row.get("review_status") or "manager_corrected",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            saved += 1
    return saved


@st.fragment
def render_ai_review_page(service: CompaniesService) -> None:
    objects_service = get_objects_service(service)
    st.title("AI-????????")
    st.caption("???????? ???????? ??????? ??????, ?????? ??????????? ? ??????? ?? ????????")

    with st.spinner("???????? ???????? ??? AI-????????..."):
        if not objects_service.load_sync(search_query=st.session_state.get("objects_search_active", "")):
            st.error(objects_service.last_error or "?? ??????? ????????? ???????")
            return

    review_df = _build_review_rows(service)
    cols = st.columns(4)
    cols[0].metric("???????? ? ???????", len(review_df))
    cols[1].metric("? ??????? AI score", int((review_df["ai_score"] >= 70).sum()) if not review_df.empty else 0)
    cols[2].metric("??????? ??????", int((review_df["confidence"] < 0.75).sum()) if not review_df.empty else 0)
    cols[3].metric("? ???????????", int((review_df["category_ai"] != "?? ??????????").sum()) if not review_df.empty else 0)

    if review_df.empty:
        st.info("??? AI-???????? ???? ??? ????????.")
        return

    stage_options = sorted(review_df["stage_ai"].dropna().unique().tolist())
    level_options = sorted(review_df["level_ai"].dropna().unique().tolist())
    category_options = sorted(review_df["category_ai"].dropna().unique().tolist())

    edited = st.data_editor(
        review_df,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "object_key": st.column_config.TextColumn("????", disabled=True, width="small"),
            "object_name": st.column_config.TextColumn("??????", disabled=True, width="large"),
            "stage_ai": st.column_config.TextColumn("?????? ??", disabled=True),
            "level_ai": st.column_config.TextColumn("??????? ??", disabled=True),
            "category_ai": st.column_config.TextColumn("????????? ??", disabled=True, width="medium"),
            "ai_score": st.column_config.NumberColumn("Score", disabled=True, min_value=0, max_value=100),
            "confidence": st.column_config.ProgressColumn("???????????", min_value=0.0, max_value=1.0),
            "confirmed": st.column_config.CheckboxColumn("?????"),
            "corrected_stage": st.column_config.SelectboxColumn("?????????? ??????", options=stage_options),
            "corrected_level": st.column_config.SelectboxColumn("?????????? ???????", options=level_options),
            "corrected_category": st.column_config.SelectboxColumn("?????????? ?????????", options=category_options),
            "review_status": st.column_config.SelectboxColumn("??????", options=_REVIEW_STATUSES),
            "correction_reason": st.column_config.SelectboxColumn("???????", options=[""] + _REASONS),
            "manager_comment": st.column_config.TextColumn("???????????"),
        },
        key="ai_review_editor",
    )

    with st.status("??????? ???????? ? ????????", expanded=False) as status:
        status.write("1. ???????? ???????????? ??? ?????????? ????")
        status.write("2. ??????? ???????? ? ???? ??????? manual_corrections.jsonl")
        status.write("3. ????? ??? ??????????? ? training events ? ???????")
        status.update(label="??????? ?????? ? ??????", state="complete")

    actions = st.columns([1, 1, 2])
    if actions[0].button("????????? ???????????", type="primary", use_container_width=True):
        saved = _save_review_events(edited)
        st.success(f"????????? ??????? ????????: {saved}")
    if actions[1].button("???????? ?????", use_container_width=True):
        st.session_state.pop("ai_review_editor", None)
        st.rerun()
