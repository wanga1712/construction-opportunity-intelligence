from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Аналитический контур", layout="wide", initial_sidebar_state="expanded")

KPI = {
    "Новые карточки": 29,
    "Gold": 3,
    "Silver": 6,
    "Bronze": 8,
    "Early": 12,
    "Обновления": 7,
}

LIMITS = {
    "Gold": (2, 3),
    "Silver": (3, 6),
    "Bronze": (4, 8),
    "Early": (7, 12),
}

CARDS = [
    {
        "id": 101,
        "level": "GOLD",
        "object_type": "Социальный объект",
        "region": "Московская область / Мытищи",
        "stage": "Положительная экспертиза",
        "title": "Строительство общеобразовательной школы на 1100 мест",
        "category": "Светотехника, Напольные покрытия",
        "material": "Светодиодные светильники, кабельные линии",
        "found": "Светильники, кабельные линии, щитовое оборудование",
        "volume": "312 шт",
        "next_stage": "Торги на строительство",
        "forecast": "март–май 2027",
        "updated": "сегодня, 08:42",
        "reason": "материал + объём + документы",
        "customer": "ГКУ Московской области",
        "balance_holder": "ГКУ Московской области",
        "designer": "ООО «Проектстрой»",
        "contractor": "Не определён",
        "tender_url": "https://zakupki.gov.ru/",
        "rating": "87/100",
        "ai_confidence": "91%",
        "review_status": "Не проверено",
    },
    {
        "id": 102,
        "level": "SILVER",
        "object_type": "Социальный объект",
        "region": "Москва",
        "stage": "Торги",
        "title": "Капитальный ремонт здания дошкольного учреждения",
        "category": "Светотехника, Гидроизоляция",
        "material": "Аварийные светильники, герметики",
        "found": "Аварийные светильники, герметики, узлы примыкания",
        "volume": "87 шт",
        "next_stage": "Подрядчик определён",
        "forecast": "август–сентябрь 2026",
        "updated": "1 день назад",
        "reason": "материал + документы + стадия",
        "customer": "ГБУ «УКС»",
        "balance_holder": "ГБУ «УКС»",
        "designer": "АО «Моспроект»",
        "contractor": "ООО «Стройподряд»",
        "tender_url": "https://zakupki.gov.ru/",
        "rating": "74/100",
        "ai_confidence": "83%",
        "review_status": "Проверяется",
    },
]

STAGE_DATA = pd.DataFrame(
    {
        "Стадия": ["Проектирование", "Положительное заключение", "Подготовка к стройке", "Торги"],
        "Количество": [12, 8, 6, 9],
    }
)
LEVEL_DATA = pd.DataFrame({"Уровень": ["Gold", "Silver", "Bronze", "Early"], "Количество": [3, 6, 8, 12]})
CATEGORY_DATA = pd.DataFrame(
    {
        "Категория": ["Светотехника", "Гидроизоляция", "Полы", "Композиты"],
        "Количество": [9, 7, 5, 4],
    }
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
          .block-container {padding-top: 1.1rem; max-width: 100%;}
          [data-testid="stSidebar"] {min-width: 290px; max-width: 320px;}
          [data-testid="stMetric"] {padding: .7rem .85rem; border: 1px solid rgba(49,51,63,.14); border-radius: .7rem;}
          .badge {display:inline-block;padding:.2rem .55rem;border-radius:999px;font-size:.72rem;font-weight:700;margin-bottom:.35rem}
          .gold {background:#f4d77a;color:#382b00}.silver{background:#dce3e8;color:#22313b}.bronze{background:#d6a06f;color:#3e210b}.early{background:#d9d9d9;color:#333}
          .card-title{font-size:1.15rem;line-height:1.35;font-weight:700;margin-bottom:.35rem}
          .label{color:#6b7280;font-size:.74rem;margin-bottom:.08rem}
          .value{font-size:.9rem;font-weight:600}
          .reason{margin-top:.55rem;padding:.5rem .65rem;border-radius:.5rem;background:rgba(255,255,255,.35);font-size:.82rem}
          .panel-title{font-size:.92rem;font-weight:700;margin-bottom:.55rem}
          .panel-group{margin-bottom:1rem}
          .card-shell{padding:.8rem 1rem;border-radius:.95rem;border:1px solid rgba(49,51,63,.10);margin-bottom:1rem}
          .gold-shell{background:linear-gradient(180deg,#fff4c9 0%,#f6de8f 100%)}
          .silver-shell{background:linear-gradient(180deg,#eef3f6 0%,#dce3e8 100%)}
          .bronze-shell{background:linear-gradient(180deg,#efd2bc 0%,#ddb08a 100%)}
          .early-shell{background:linear-gradient(180deg,#efefef 0%,#dddddd 100%)}
          .actions{font-size:.82rem;color:#22313b}
          .card-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:.45rem}
          div[data-testid="stButton"] > button {width:100%;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.header("Фильтры и настройки")
        st.multiselect("Категория", ["Свет", "Гидроизоляция", "Полы", "Композиты"], default=["Свет", "Гидроизоляция"])
        st.multiselect("Уровень", ["Gold", "Silver", "Bronze", "Early"], default=["Gold", "Silver"])
        st.multiselect(
            "Стадия",
            ["Проектирование", "Положительное заключение", "Торги", "Подрядчик определён"],
            default=["Проектирование", "Положительное заключение", "Торги"],
        )
        st.multiselect("Регион", ["Москва", "МО", "Санкт-Петербург"], default=["Москва", "МО"])
        st.checkbox("Только с объёмом")
        st.checkbox("Только с документами", value=True)
        st.divider()
        st.selectbox("Сортировка", ["По приоритету", "По дате обновления"])


def render_header() -> None:
    left, cat, period = st.columns([5, 2, 1.5], vertical_alignment="bottom")
    with left:
        st.title("АНАЛИТИЧЕСКИЙ КОНТУР")
        st.caption("Главная / Новые карточки / Портфель / Обновления / Компании / Аналитика")
    with cat:
        st.selectbox("Категория", ["Все категории", "Светотехника", "Гидроизоляция", "Полы", "Композиты"])
    with period:
        st.selectbox("Период", ["7 дней", "30 дней", "90 дней"], index=1)


def render_kpis_and_limits() -> None:
    cols = st.columns(6)
    for col, (label, value) in zip(cols, KPI.items()):
        with col:
            st.metric(label, value, border=True)
    with st.container(border=True):
        st.caption("Лимиты: G 2/3 | S 3/6 | B 4/8 | E 7/12")
        cols = st.columns(4)
        for col, (label, (used, limit)) in zip(cols, LIMITS.items()):
            with col:
                st.write(f"**{label}: {used}/{limit}**")
                st.progress(min(used / limit, 1.0))


def render_charts() -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("График по стадиям")
        fig = px.bar(STAGE_DATA, x="Количество", y="Стадия", orientation="h", text="Количество")
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with c2:
        st.subheader("График по уровням")
        fig = px.pie(LEVEL_DATA, names="Уровень", values="Количество", hole=0.52)
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with c3:
        st.subheader("График по категориям")
        fig = px.bar(CATEGORY_DATA, x="Категория", y="Количество", text="Количество")
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), xaxis_title=None, yaxis_title=None)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def badge_class(level: str) -> str:
    return {"GOLD": "gold", "SILVER": "silver", "BRONZE": "bronze", "EARLY": "early"}.get(level.upper(), "early")


def field(label: str, value: str) -> None:
    st.markdown(f'<div class="label">{label}</div><div class="value">{value}</div>', unsafe_allow_html=True)


def render_card(card: dict) -> None:
    shell = {"GOLD": "gold-shell", "SILVER": "silver-shell", "BRONZE": "bronze-shell", "EARLY": "early-shell"}.get(
        card["level"].upper(), "early-shell"
    )
    with st.container():
        st.markdown(f'<div class="card-shell {shell}">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="card-head"><div><span class="badge {badge_class(card["level"])}">{card["level"]} КАРТОЧКА</span></div><div class="actions">[В портфель] [Следить] [Экспорт]</div></div>',
            unsafe_allow_html=True,
        )
        t1, t2 = st.columns([4, 2], vertical_alignment="top")
        with t1:
            st.markdown(f'<div class="card-title">{card["title"]}</div>', unsafe_allow_html=True)
            st.write(f'{card["region"]} / {card["object_type"]}')
        with t2:
            field("Обновлено", card["updated"])
            st.markdown(f'<a href="{card["tender_url"]}" target="_blank">Ссылка на закупку</a>', unsafe_allow_html=True)

        st.markdown("---")
        r0 = st.columns(4)
        with r0[0]:
            field("Стадия", card["stage"])
        with r0[1]:
            field("Рейтинг", card["rating"])
        with r0[2]:
            field("Категория", card["category"])
        with r0[3]:
            field("Уверенность AI", card["ai_confidence"])

        r1 = st.columns(3)
        with r1[0]:
            field("Прогноз торгов", card["forecast"])
        with r1[1]:
            field("Статус проверки", card["review_status"])
        with r1[2]:
            field("Следующий этап", card["next_stage"])

        r2 = st.columns(3)
        with r2[0]:
            field("Что найдено кратко", card["found"])
        with r2[1]:
            field("Материал", card["material"])
        with r2[2]:
            field("Объём", card["volume"])

        r3 = st.columns(3)
        with r3[0]:
            field("Балансодержатель / заказчик", card["balance_holder"])
        with r3[1]:
            field("Проектировщик", card["designer"])
        with r3[2]:
            field("Подрядчик", card["contractor"])

        st.markdown(f'<div class="reason"><strong>Причина рейтинга:</strong> {card["reason"]}</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_inline_filters() -> None:
    with st.container(border=True):
        st.markdown('<div class="panel-title">Sidebar: фильтры и настройки</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-group"><strong>Категория</strong></div>', unsafe_allow_html=True)
        st.checkbox("Свет", value=True, key="inline_cat_light")
        st.checkbox("Гидроизоляция", value=True, key="inline_cat_hydro")
        st.checkbox("Полы", value=False, key="inline_cat_floor")
        st.checkbox("Композиты", value=False, key="inline_cat_comp")
        st.markdown('<div class="panel-group"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-group"><strong>Уровень</strong></div>', unsafe_allow_html=True)
        st.checkbox("Gold", value=True, key="inline_level_gold")
        st.checkbox("Silver", value=True, key="inline_level_silver")
        st.checkbox("Bronze", value=False, key="inline_level_bronze")
        st.checkbox("Early", value=False, key="inline_level_early")
        st.markdown('<div class="panel-group"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-group"><strong>Стадия</strong></div>', unsafe_allow_html=True)
        st.checkbox("Проектирование", value=True, key="inline_stage_design")
        st.checkbox("Положительное заключение", value=True, key="inline_stage_expertise")
        st.checkbox("Торги", value=True, key="inline_stage_tender")
        st.checkbox("Подрядчик определён", value=False, key="inline_stage_awarded")
        st.markdown('<div class="panel-group"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-group"><strong>Регион</strong></div>', unsafe_allow_html=True)
        st.selectbox("Москва", ["Москва"], key="inline_region_moscow")
        st.selectbox("МО", ["МО"], key="inline_region_mo")
        st.markdown('<div class="panel-group"></div>', unsafe_allow_html=True)
        st.checkbox("Только с объёмом", key="inline_only_volume")
        st.checkbox("Только с документами", value=True, key="inline_only_docs")
        st.markdown('<div class="panel-group"></div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-group"><strong>Сортировка</strong></div>', unsafe_allow_html=True)
        st.selectbox("По приоритету", ["По приоритету"], key="inline_sort_priority")
        st.selectbox("По дате", ["По дате"], key="inline_sort_date")


def render_tabs() -> None:
    tab_new, tab_portfolio, tab_updates, tab_companies = st.tabs(["Новые", "Портфель", "Обновления", "Компании"])
    with tab_new:
        for card in CARDS:
            render_card(card)
    with tab_portfolio:
        st.info("Здесь будет портфель.")
    with tab_updates:
        st.info("Здесь будут обновления.")
    with tab_companies:
        st.info("Здесь будут компании.")


def render_page() -> None:
    inject_css()
    render_sidebar()
    render_header()
    render_kpis_and_limits()
    render_charts()
    left, right = st.columns([1.1, 2.2], gap="large")
    with left:
        render_inline_filters()
    with right:
        render_tabs()


render_page()
