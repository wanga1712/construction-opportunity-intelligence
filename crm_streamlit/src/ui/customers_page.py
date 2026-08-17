"""Раздел «Заказчики» — управляющие компании (УК)."""
from __future__ import annotations

import streamlit as st

from src.services.map_export import fetch_uk_summary
from src.ui.session_deps import get_parking_db


def render_customers_page() -> None:
    st.title("Заказчики")
    st.caption("Управляющие компании по объектам НСПД. Карта объектов — в разделе **🗺 Карта** слева.")

    db = get_parking_db()
    if not db.connect():
        st.error(f"База паркинга недоступна: {db.last_error or 'нет подключения'}")
        st.info(
            "Проверьте `PARKING_DB_*` или `CRM_DB_HOST` в `.env`. "
            "БД `nspd_parking` обычно на том же сервере, что и CRM (S13)."
        )
        return

    st.markdown("#### Управляющие компании")

    min_f = st.selectbox(
        "Мин. подземных этажей у объектов",
        [0, 2],
        format_func=lambda x: "Любые" if x == 0 else "≥ 2",
        key="uk_tab_min_floors",
    )

    rows = fetch_uk_summary(db, min_floors=min_f if min_f >= 2 else 0)
    if not rows:
        st.info("Управляющие компании не найдены.")
        return

    import pandas as pd

    df = pd.DataFrame([
        {
            "УК": r.get("uk_name") or "—",
            "ОГРН": r.get("uk_ogrn") or "—",
            "ИНН": r.get("uk_inn") or "—",
            "Объектов": r.get("object_count", 0),
            "≥2 эт.": r.get("ge2_floors", 0),
            "Телефон": r.get("uk_phone") or "—",
        }
        for r in rows
    ])
    st.dataframe(df, use_container_width=True, hide_index=True, height=min(600, 40 + len(df) * 36))
    st.caption(f"Всего УК: **{len(rows)}**")
