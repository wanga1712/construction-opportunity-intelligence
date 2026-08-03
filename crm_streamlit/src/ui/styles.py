"""Global Streamlit UI styles: compact Salesforce-like CRM cards."""
from __future__ import annotations

import streamlit as st

from src.ui.styles_salesforce import SALESFORCE_STYLES

PRIMARY = "#0176D3"


def inject_global_styles() -> None:
    mode = 'light'
    dark = False

    colors = {
        "primary": PRIMARY,
        "app_bg": "#172033" if dark else "#E8EDF3",
        "surface": "#1C273A" if dark else "#F8FAFC",
        "card": "#223047" if dark else "#FFFFFF",
        "card_2": "#2A3A55" if dark else "#F3F6FA",
        "input": "#182236" if dark else "#FFFFFF",
        "input_focus": "#1E2B42" if dark else "#FFFFFF",
        "border": "#3B4D68" if dark else "#D7DEE8",
        "border_soft": "#30425E" if dark else "#E4E9F0",
        "text": "#F4F7FB" if dark else "#181818",
        "muted": "#C7D2E2" if dark else "#5F6B7A",
        "muted_2": "#9FB0C7" if dark else "#706E6B",
        "chip_bg": "#1D365A" if dark else "#EEF4FB",
        "chip_text": "#8CC7FF" if dark else "#0176D3",
        "hover": "#2B3D59" if dark else "#EEF3F8",
        "shadow": "rgba(0,0,0,0.24)" if dark else "rgba(24, 39, 75, 0.07)",
    }

    st.markdown(
        f"""
        <style>
        :root {{
            --crm-primary: {colors["primary"]};
            --crm-app-bg: {colors["app_bg"]};
            --crm-surface: {colors["surface"]};
            --crm-card: {colors["card"]};
            --crm-card-2: {colors["card_2"]};
            --crm-input: {colors["input"]};
            --crm-input-focus: {colors["input_focus"]};
            --crm-border: {colors["border"]};
            --crm-border-soft: {colors["border_soft"]};
            --crm-text: {colors["text"]};
            --crm-muted: {colors["muted"]};
            --crm-muted-2: {colors["muted_2"]};
            --crm-chip-bg: {colors["chip_bg"]};
            --crm-chip-text: {colors["chip_text"]};
            --crm-hover: {colors["hover"]};
            --crm-shadow: {colors["shadow"]};
        }}

        .stApp {{
            background:
                radial-gradient(circle at top left, rgba(1,118,211,0.16), transparent 34rem),
                linear-gradient(180deg, rgba(255,255,255,0.02), transparent 14rem),
                var(--crm-app-bg) !important;
            color: var(--crm-text) !important;
        }}
        .block-container {{
            padding-top: 1.8rem !important;
        }}

        h1, h2, h3, h4, h5, h6,
        p, label, span, div, [data-testid="stMarkdownContainer"] {{
            color: inherit;
        }}
        div[data-testid="stSidebar"] {{
            background: var(--crm-surface) !important;
            border-right: 1px solid var(--crm-border-soft) !important;
        }}
        div[data-testid="stSidebar"] .block-container {{
            padding-top: 1.25rem;
        }}

        div[data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stExpander"],
        div[data-testid="stMetric"] {{
            background: var(--crm-card) !important;
            border: 1px solid var(--crm-border) !important;
            border-radius: 0.55rem !important;
            box-shadow: 0 1px 3px var(--crm-shadow) !important;
        }}
        [data-testid="stExpander"] details {{
            background: var(--crm-card) !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            margin-bottom: 0.55rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
            border-color: var(--crm-primary) !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] > div {{
            padding: 0.5rem 0.7rem 0.55rem 0.7rem !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] {{
            gap: 0.2rem !important;
        }}

        .crm-card-name {{
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--crm-text);
            margin: 0;
            line-height: 1.3;
            padding-top: 0.35rem;
        }}
        .crm-card-edit {{
            margin-top: 0.15rem;
            padding-top: 0.2rem;
            border-top: 1px solid var(--crm-border-soft);
        }}
        .crm-chip {{
            display: flex;
            flex-direction: column;
            align-items: center;
            background: var(--crm-card-2);
            border: 1px solid var(--crm-border-soft);
            border-radius: 0.35rem;
            padding: 0.35rem 0.4rem;
            min-width: 0;
            line-height: 1.15;
        }}
        .crm-chip-ico {{ font-size: 0.95rem; line-height: 1; }}
        .crm-chip-val {{
            font-size: 0.9rem;
            font-weight: 700;
            color: var(--crm-text);
        }}
        .crm-chip-lbl {{
            font-size: 0.6rem;
            color: var(--crm-muted-2);
            text-transform: uppercase;
            letter-spacing: 0.02em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 100%;
        }}
        .crm-nav-caption {{
            font-size: 0.6875rem;
            font-weight: 700;
            color: var(--crm-muted-2);
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin: 1rem 0 0.35rem 0;
        }}

        .stButton > button {{
            border-radius: 0.45rem !important;
        }}
        .stButton > button[kind="primary"] {{
            background-color: var(--crm-primary) !important;
            border-color: var(--crm-primary) !important;
            color: #FFFFFF !important;
            font-size: 0.78rem;
            padding: 0.22rem 0.55rem;
            min-height: 1.8rem;
        }}
        .stButton > button[kind="secondary"] {{
            background: var(--crm-card) !important;
            border-color: var(--crm-border) !important;
            color: var(--crm-text) !important;
        }}
        .stButton > button[kind="secondary"]:hover {{
            border-color: var(--crm-primary) !important;
            color: var(--crm-primary) !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] button[kind="tertiary"] {{
            font-size: 1.35rem !important;
            line-height: 1 !important;
            min-height: 2rem !important;
            padding: 0.1rem 0.35rem !important;
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] button[kind="tertiary"]:hover {{
            background: var(--crm-hover) !important;
        }}

        input,
        textarea,
        div[data-baseweb="input"],
        div[data-baseweb="textarea"],
        div[data-baseweb="select"],
        div[data-baseweb="select"] > div,
        div[data-baseweb="popover"] div,
        [data-baseweb="menu"],
        [data-baseweb="menu"] ul,
        [data-baseweb="menu"] li {{
            background: var(--crm-input) !important;
            color: var(--crm-text) !important;
            border-color: var(--crm-border) !important;
        }}
        input:focus,
        textarea:focus,
        div[data-baseweb="input"]:focus-within,
        div[data-baseweb="textarea"]:focus-within,
        div[data-baseweb="select"]:focus-within {{
            background: var(--crm-input-focus) !important;
            border-color: var(--crm-primary) !important;
            box-shadow: 0 0 0 1px rgba(1,118,211,0.35) !important;
        }}
        input::placeholder,
        textarea::placeholder {{
            color: var(--crm-muted-2) !important;
            opacity: 0.92 !important;
        }}
        [data-baseweb="select"] span,
        [data-baseweb="select"] svg,
        [data-baseweb="menu"] li,
        [data-baseweb="menu"] span {{
            color: var(--crm-text) !important;
            fill: var(--crm-muted) !important;
        }}
        [data-baseweb="menu"] li:hover {{
            background: var(--crm-hover) !important;
        }}
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stTextArea"] textarea {{
            min-height: 2.15rem !important;
        }}

        {SALESFORCE_STYLES.replace("{{", "{").replace("}}", "}")}
        </style>
        """,
        unsafe_allow_html=True,
    )


