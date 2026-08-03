import json
from pathlib import Path
import streamlit as st

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ai_shadow"

def render_ai_shadow_page() -> None:
    st.title("AI-анализ закупок")
    path = DATA_DIR / "model_suggestions.jsonl"
    if not path.exists():
        st.info("Результаты теневого анализа ещё не загружены.")
        return
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    st.caption(f"Теневой прогон: {len(rows)} закупок. Рабочие фильтры не изменяются.")
    for row in rows:
        with st.container(border=True):
            st.subheader(row.get("title") or "Без названия")
            st.caption(f"№ {row.get('tender_number') or '—'} · ID {row.get('procurement_id')}")
            st.code(row.get("model_response", ""), language="json")
