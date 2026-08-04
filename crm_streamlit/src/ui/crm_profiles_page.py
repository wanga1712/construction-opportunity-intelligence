"""Страница управления профилями поиска CRM.

Возможности:
  - Просмотр всех профилей и их ключевых слов
  - Загрузка Excel/CSV-шаблона → парсинг → сохранение в БД → рестарт поиска
  - Скачивание шаблона для заполнения
  - Ручной запуск пересева match_cache
"""
from __future__ import annotations

import io
import re
from typing import Optional

import pandas as pd
import streamlit as st

from src.services.crm_profile_service import (
    load_profiles,
    load_profile_keywords,
    load_subcategories,
    upsert_profile,
    seed_keywords,
    trigger_sync_refresh,
)


# ---------------------------------------------------------------------------
# Шаблон Excel
# ---------------------------------------------------------------------------

_TEMPLATE_COLUMNS = ["Профиль", "Подкатегория", "Ключевое слово", "Вес (1-10)"]
_TEMPLATE_EXAMPLE = [
    ["Опора освещения", "Композитные опоры", "опора освещения", 10],
    ["Опора освещения", "Композитные опоры", "композитн опора", 10],
    ["Опора освещения", "Алюминиевые опоры", "алюминиев опора", 9],
    ["Опора освещения", "Алюминиевые опоры", "металлическ опора", 7],
    ["Светотехника", "Наружное освещение", "уличный светильник", 10],
    ["Светотехника", "Наружное освещение", "наружн освещени", 9],
]


def _build_template_excel() -> bytes:
    df = pd.DataFrame(_TEMPLATE_EXAMPLE, columns=_TEMPLATE_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Профили")
        ws = writer.sheets["Профили"]
        # Ширина колонок
        for i, col in enumerate(_TEMPLATE_COLUMNS, 1):
            ws.column_dimensions[chr(64 + i)].width = 30
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Парсинг загруженного файла
# ---------------------------------------------------------------------------

def _parse_upload(file) -> tuple[pd.DataFrame, str]:
    """Возвращает (df, error). df имеет колонки: profile, subcategory, keyword, weight."""
    try:
        name = file.name.lower()
        if name.endswith(".xlsx") or name.endswith(".xls"):
            df = pd.read_excel(file)
        elif name.endswith(".csv"):
            df = pd.read_csv(file)
        else:
            return pd.DataFrame(), "Формат не поддерживается. Загрузите .xlsx или .csv"
    except Exception as exc:
        return pd.DataFrame(), f"Ошибка чтения файла: {exc}"

    # Нормализуем названия колонок
    col_map = {}
    for c in df.columns:
        low = str(c).lower().strip()
        if "профиль" in low or "profile" in low:
            col_map[c] = "profile"
        elif "подкатегор" in low or "subcateg" in low or "категор" in low:
            col_map[c] = "subcategory"
        elif "ключев" in low or "keyword" in low or "слово" in low:
            col_map[c] = "keyword"
        elif "вес" in low or "weight" in low or "приор" in low:
            col_map[c] = "weight"

    df = df.rename(columns=col_map)
    required = {"profile", "keyword"}
    missing = required - set(df.columns)
    if missing:
        return pd.DataFrame(), f"Не найдены обязательные колонки: {missing}. Есть: {list(df.columns)}"

    if "subcategory" not in df.columns:
        df["subcategory"] = ""
    if "weight" not in df.columns:
        df["weight"] = 8

    df = df[["profile", "subcategory", "keyword", "weight"]].copy()
    df["profile"] = df["profile"].fillna("").str.strip()
    df["subcategory"] = df["subcategory"].fillna("").str.strip()
    df["keyword"] = df["keyword"].fillna("").str.strip()
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(8).clip(1, 10).astype(int)

    df = df[df["profile"] != ""]
    df = df[df["keyword"] != ""]

    if df.empty:
        return pd.DataFrame(), "Файл не содержит данных после очистки"

    return df, ""


# ---------------------------------------------------------------------------
# Главный рендер
# ---------------------------------------------------------------------------

def render_crm_profiles_page(_service=None) -> None:
    st.title("⚙️ Профили поиска")
    st.caption("Управление профилями, подкатегориями и ключевыми словами для автоматического матчинга закупок")

    tab_view, tab_upload, tab_manage = st.tabs([
        "📋 Профили и ключевые слова",
        "📤 Загрузить профиль",
        "🔄 Управление синхронизацией",
    ])

    with tab_view:
        _render_profiles_view()

    with tab_upload:
        _render_upload()

    with tab_manage:
        _render_sync_management()


# ---------------------------------------------------------------------------
# Вкладка: просмотр профилей
# ---------------------------------------------------------------------------

def _render_profiles_view() -> None:
    profiles = load_profiles()
    if not profiles:
        st.info("Профили не найдены. Загрузите первый профиль на вкладке «Загрузить профиль».")
        return

    selected = st.selectbox(
        "Профиль",
        options=[p["id"] for p in profiles],
        format_func=lambda pid: next(
            (f"{p['name']} ({p['keyword_count']} ключ. слов)" for p in profiles if p["id"] == pid), str(pid)
        ),
        key="profile_view_select",
    )

    if selected is None:
        return

    keywords = load_profile_keywords(selected)
    if not keywords:
        st.info("Ключевые слова не настроены. Загрузите файл на вкладке «Загрузить профиль».")
        return

    df = pd.DataFrame(keywords)
    subcats = sorted(df["subcategory"].dropna().unique().tolist())

    if subcats:
        flt = st.multiselect("Подкатегория", subcats, default=subcats, key="kw_subcat_filter")
        df = df[df["subcategory"].isin(flt) | df["subcategory"].isna()]

    show_cols = [c for c in ["subcategory", "value", "weight", "is_active", "notes"] if c in df.columns]
    col_labels = {"subcategory": "Подкатегория", "value": "Ключевое слово",
                  "weight": "Вес", "is_active": "Активно", "notes": "Заметки"}
    st.dataframe(
        df[show_cols].rename(columns=col_labels),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Всего: {len(df)} ключевых слов")


# ---------------------------------------------------------------------------
# Вкладка: загрузка файла
# ---------------------------------------------------------------------------

def _render_upload() -> None:
    col_dl, col_info = st.columns([1, 2])
    with col_dl:
        st.download_button(
            "⬇️ Скачать шаблон Excel",
            data=_build_template_excel(),
            file_name="crm_profile_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with col_info:
        st.info(
            "**Формат файла:** .xlsx или .csv\n\n"
            "**Обязательные колонки:** Профиль, Ключевое слово\n\n"
            "**Необязательные:** Подкатегория, Вес (1–10, по умолчанию 8)"
        )

    st.divider()

    uploaded = st.file_uploader(
        "Выберите файл с профилем",
        type=["xlsx", "xls", "csv"],
        key="profile_upload_file",
    )

    if uploaded is None:
        st.markdown("""
**Как заполнить шаблон:**

| Профиль | Подкатегория | Ключевое слово | Вес |
|---------|-------------|----------------|-----|
| Опора освещения | Композитные опоры | опора освещения | 10 |
| Опора освещения | Алюминиевые опоры | алюминиев опора | 9 |
| Светотехника | Наружное освещение | уличный светильник | 10 |

- **Профиль** — название продуктовой линейки (если нет — создастся новый)
- **Подкатегория** — группировка внутри профиля (необязательно)
- **Ключевое слово** — фраза для поиска в названии тендера (русский или латиница)
- **Вес** — приоритет совпадения (1–10), влияет на уровень Gold/Silver/Bronze
        """)
        return

    df, error = _parse_upload(uploaded)
    if error:
        st.error(error)
        return

    st.success(f"Файл разобран: {len(df)} строк")

    # Превью по профилям
    profiles_in_file = df["profile"].unique().tolist()
    st.markdown(f"**Профилей в файле:** {len(profiles_in_file)}")

    for pname in profiles_in_file:
        sub_df = df[df["profile"] == pname]
        subcats = sub_df["subcategory"].unique().tolist()
        with st.expander(f"**{pname}** — {len(sub_df)} слов, подкатегорий: {len([s for s in subcats if s])}"):
            st.dataframe(
                sub_df[["subcategory", "keyword", "weight"]].rename(columns={
                    "subcategory": "Подкатегория", "keyword": "Ключевое слово", "weight": "Вес"
                }),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    replace_mode = st.radio(
        "Режим загрузки",
        ["Добавить к существующим", "Заменить подкатегории из файла"],
        index=0,
        key="upload_replace_mode",
        help=(
            "**Добавить** — новые слова добавятся, существующие не тронутся.\n"
            "**Заменить** — старые ключевые слова для этих подкатегорий деактивируются."
        ),
    )

    if st.button("✅ Сохранить в базу и перезапустить поиск", type="primary", use_container_width=True):
        do_replace = replace_mode == "Заменить подкатегории из файла"
        progress = st.progress(0, text="Сохраняем профили...")
        total_kw = 0

        for i, pname in enumerate(profiles_in_file):
            sub_df = df[df["profile"] == pname]
            code = re.sub(r"[^a-z0-9_]", "_", pname.lower().strip())[:40]
            profile_id = upsert_profile(pname, code)

            rows_to_seed = [
                {
                    "subcategory": row["subcategory"] or None,
                    "keyword": row["keyword"],
                    "weight": int(row["weight"]),
                }
                for _, row in sub_df.iterrows()
            ]

            replaced_subcats = set()
            for row in rows_to_seed:
                if do_replace and row["subcategory"] and row["subcategory"] not in replaced_subcats:
                    seed_keywords(profile_id, [], replace_subcategory=row["subcategory"])
                    replaced_subcats.add(row["subcategory"])

            n = seed_keywords(profile_id, rows_to_seed)
            total_kw += n
            progress.progress((i + 1) / len(profiles_in_file), text=f"Профиль: {pname} ({n} слов)")

        trigger_sync_refresh()
        progress.progress(1.0, text="Готово!")
        st.success(
            f"Сохранено {total_kw} ключевых слов для {len(profiles_in_file)} профилей. "
            "Задание на пересев поиска поставлено в очередь."
        )
        st.balloons()


# ---------------------------------------------------------------------------
# Вкладка: управление синхронизацией
# ---------------------------------------------------------------------------

def _render_sync_management() -> None:
    import os, psycopg2
    from psycopg2.extras import RealDictCursor

    PG = dict(
        host=os.environ.get("CRM_DB_HOST", "S7"),
        port=int(os.environ.get("CRM_DB_PORT", 5432)),
        user=os.environ.get("CRM_DB_USER", "postgres"),
        password=os.environ.get("CRM_DB_PASSWORD", "<REMOVED_COMPROMISED_CREDENTIAL>"),
        dbname="crm",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Ручной пересев поиска")
        st.caption(
            "Запускает полный матчинг ключевых слов по tender_monitor "
            "и обновляет crm_procurements. Используйте после изменения ключевых слов."
        )
        if st.button("🔄 Запустить пересев", use_container_width=True, key="manual_refresh_btn"):
            trigger_sync_refresh()
            st.success("Задание поставлено в очередь")

    with col2:
        st.markdown("#### Статистика")
        try:
            conn = psycopg2.connect(**PG)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT count(*) as cnt FROM crm_procurements")
                total = cur.fetchone()["cnt"]
                cur.execute("SELECT count(*) as cnt FROM crm_procurements WHERE crm_stage='torgi'")
                torgi = cur.fetchone()["cnt"]
                cur.execute("SELECT count(*) as cnt FROM crm_procurements WHERE crm_stage='razygranye'")
                raz = cur.fetchone()["cnt"]
                cur.execute("SELECT count(*) as cnt FROM crm_search_rules WHERE is_active=true")
                kw_cnt = cur.fetchone()["cnt"]
            conn.close()
            st.metric("Всего закупок", total)
            st.metric("Идут торги", torgi)
            st.metric("Разыгранные", raz)
            st.metric("Активных ключ. слов", kw_cnt)
        except Exception as exc:
            st.warning(f"Ошибка: {exc}")

    st.divider()
    st.markdown("#### История заданий синхронизации")
    try:
        conn = psycopg2.connect(**PG)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, job_type, trigger_type, status,
                       started_at, finished_at,
                       processed_count, updated_count, awarded_count,
                       error_message
                FROM crm_sync_jobs
                ORDER BY id DESC LIMIT 20
            """)
            jobs = cur.fetchall()
        conn.close()
        if jobs:
            st.dataframe(
                pd.DataFrame([dict(j) for j in jobs]).rename(columns={
                    "id": "ID", "job_type": "Тип", "trigger_type": "Источник",
                    "status": "Статус", "started_at": "Начало", "finished_at": "Конец",
                    "processed_count": "Обработано", "updated_count": "Обновлено",
                    "awarded_count": "Разыграно", "error_message": "Ошибка",
                }),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Заданий ещё не было")
    except Exception as exc:
        st.warning(f"Ошибка: {exc}")

    st.divider()
    st.markdown("#### Очередь ручного переобогащения")
    try:
        conn = psycopg2.connect(**PG)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT j.id, j.status, j.trigger_type, j.created_at, j.finished_at,
                       p.auction_name, p.crm_category
                FROM crm_enrich_jobs j
                LEFT JOIN crm_procurements p ON p.id = j.procurement_id
                ORDER BY j.id DESC LIMIT 20
            """)
            jobs = cur.fetchall()
        conn.close()
        if jobs:
            st.dataframe(
                pd.DataFrame([dict(j) for j in jobs]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Очередь пуста")
    except Exception as exc:
        st.warning(f"Ошибка: {exc}")
