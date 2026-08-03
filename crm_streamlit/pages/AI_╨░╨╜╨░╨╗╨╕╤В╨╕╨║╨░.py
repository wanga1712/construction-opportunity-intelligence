import json
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="AI-анализ закупок", layout="wide")
st.title("AI-анализ закупок")
path = Path(__file__).resolve().parents[1] / "data" / "ai_shadow" / "model_suggestions.jsonl"
if not path.exists():
    st.info("Результаты теневого анализа ещё не загружены.")
else:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    st.caption(f"Теневой прогон: {len(rows)} закупок. Рабочие фильтры не изменяются.")
    for row in rows:
        with st.container(border=True):
            st.subheader(row.get("title") or "Без названия")
            st.caption(f"№ {row.get('tender_number') or '—'} · ID {row.get('procurement_id')}")
            st.code(row.get("model_response", ""), language="json")
