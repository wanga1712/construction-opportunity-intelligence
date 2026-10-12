"""Small informational tabs for the waterproofing CRM page."""
from __future__ import annotations

import streamlit as st

from src.services.waterproofing_process import (
    AI_ANALYSIS_PROMPT_TEMPLATE,
    FIELD_GROUPS,
    KNOWLEDGE_TOPICS,
    PIPELINES,
    SCORING_RULES,
    STAGES,
)
from src.services.waterproofing_crm import CRM_STAGES, STAGE_DEFAULT_ACTIONS


def render_pipeline_tab() -> None:
    st.markdown("### Воронка УК — главная")
    st.caption("Движение управляющей компании по этапам продажи: на этих этапах живут карточки УК.")
    for index, stage in enumerate(CRM_STAGES, start=1):
        st.markdown(f"- **{index}. {stage}** — {STAGE_DEFAULT_ACTIONS.get(stage, '—')}")
    st.markdown("### Портфели / направления")
    for pipeline in PIPELINES:
        st.markdown(f"- **{pipeline.name}** — {pipeline.description}")
    st.markdown("### Этапы работы с объектом внутри УК")
    for stage in STAGES:
        with st.expander(f"{stage.number}. {stage.name}"):
            st.caption("Обязательные поля для перехода дальше:")
            st.write(", ".join(stage.required_fields) or "—")


def render_fields_tab() -> None:
    for group in FIELD_GROUPS:
        with st.expander(group.name, expanded=group.name == "Базовые поля объекта"):
            for field in group.fields:
                st.markdown(f"- {field}")
    st.markdown("### Скоринг 0–100")
    for points, rule in SCORING_RULES:
        st.markdown(f"- `{'+' if points > 0 else ''}{points}` — {rule}")


def render_ai_tab() -> None:
    st.markdown("### AI работает внутри каждой карточки")
    st.info(
        "Открывайте объект из вкладки «Объекты из БД» — во вкладке карточки "
        "«🤖 AI и чат» есть советник, быстрые рекомендации и чат по конкретному объекту."
    )
    st.markdown("### База знаний Qwen")
    st.caption("На первом этапе без fine-tuning: RAG / база знаний + шаблоны промптов.")
    columns = st.columns(3)
    for index, topic in enumerate(KNOWLEDGE_TOPICS):
        columns[index % 3].markdown(f"- {topic}")
    st.markdown("### Промпт AI-анализа объекта")
    st.code(AI_ANALYSIS_PROMPT_TEMPLATE, language="text")
