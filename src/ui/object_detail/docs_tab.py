"""Procurement document tab."""
from __future__ import annotations

import html

import streamlit as st

from src.services.object_detail_loader import ObjectDetailData
from .formatters import _doc_icon
from .layout import _section_title
from .matches_tab import _render_tender_zip_download


def _render_docs_tab(detail: ObjectDetailData, object_key: str) -> None:
    docs = detail.documents
    if not docs:
        st.info("Ссылки на документацию закупки не найдены в БД.")
        return
    _section_title("Файлы закупки на площадке")
    st.caption(f"Всего **{len(docs)}** файлов. Можно скачать одним ZIP — все части архива внутри.")
    _render_tender_zip_download(detail, object_key)
    with st.expander(f"📎 Скачать по одному ({len(docs)})", expanded=False):
        for doc in docs:
            url = doc.get("url") or ""
            raw_name = doc.get("file_name") or "Документ"
            name = html.escape(raw_name)
            icon = _doc_icon(raw_name)
            if url:
                st.markdown(f"- {icon} [{name}]({url})")
            else:
                st.markdown(f"- {icon} {name}")
