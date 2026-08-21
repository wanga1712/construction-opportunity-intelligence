"""Streamlit CRM entrypoint.

    streamlit run app.py --server.port 8502
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.bootstrap import setup_source_path

setup_source_path()

import streamlit as st

from src.ui.app_bootstrap import main as run_app_bootstrap
from src.ui.styles import inject_global_styles


def main() -> None:
    st.set_page_config(
        page_title="CRM Система",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_global_styles()
    run_app_bootstrap()


if __name__ == "__main__":
    main()
