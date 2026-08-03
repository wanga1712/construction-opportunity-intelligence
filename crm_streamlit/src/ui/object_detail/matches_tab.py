"""Match result rendering and downloads."""
from __future__ import annotations

import html
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.constants.object_quality import TIER_LABELS
from src.constants.product_groups import PRODUCT_GROUP_OPTIONS
from src.services.docs_match_preview import (
    confirmed_product_groups,
    other_product_groups,
    preview_line_for_group,
    product_name_matches_group,
    products_for_group,
)
from src.services.match_file_display import (
    documents_for_download,
    find_related_platform_documents,
    inner_match_file_name,
    local_download_name,
    local_file_path,
    resolve_match_display_name,
)
from src.services.object_detail_loader import ObjectDetailData
from src.services.tender_docs_bundle import build_documents_zip, bundle_filename, format_size
from .formatters import _doc_icon, _location_cell, _truncate
from .layout import _compact_metrics, _section_title


def _render_tender_zip_download(
    detail: ObjectDetailData, object_key: str, *, prefix: str = "",
) -> None:
    docs = [d for d in detail.documents if d.get("url")]
    if not docs:
        return
    bundle_key = f"docs_zip_{object_key}"
    contract = detail.contract_number or detail.item.contract_number
    zip_name = bundle_filename(contract, detail.item.tender_id)
    build_key, dl_key = f"{prefix}build_zip_{object_key}", f"{prefix}dl_zip_{object_key}"
    if st.button(f"📦 Скачать всю документацию одним ZIP ({len(docs)} файлов)", key=build_key, use_container_width=True):
        with st.spinner(f"Скачиваю {len(docs)} файлов с площадки и упаковываю…"):
            try:
                st.session_state[bundle_key] = build_documents_zip(docs)
            except Exception as exc:
                st.error(f"Не удалось собрать архив: {exc}")
                return
        st.rerun()
    cached = st.session_state.get(bundle_key)
    if cached:
        zip_bytes, stats = cached
        size_label = format_size(stats.get("size_bytes", len(zip_bytes)))
        st.download_button(
            f"⬇ Сохранить {zip_name} · {stats.get('ok', 0)}/{stats.get('total', 0)} · {size_label}",
            data=zip_bytes, file_name=zip_name, mime="application/zip", key=dl_key,
            use_container_width=True, type="primary",
        )
        failed = stats.get("failed") or []
        if failed:
            st.warning("Не удалось скачать: " + "; ".join(html.escape(x) for x in failed[:5]) + ("…" if len(failed) > 5 else ""))


def _render_match_downloads(
    mf: Dict[str, Any], idx: int, *, related_docs: List[Dict[str, Any]],
    download_docs: List[Dict[str, Any]], local_path,
) -> None:
    docs_with_url = [d for d in download_docs if d.get("url")]
    if not local_path and not docs_with_url:
        yp = (mf.get("yandex_path") or "").strip()
        if yp:
            st.caption(f"📁 Файл на диске: `{yp}` — недоступен с этой машины.")
        elif download_docs:
            st.caption("Ссылки на скачивание в БД отсутствуют — см. вкладку «Документация».")
        return
    dl_cols = st.columns(2) if local_path and docs_with_url else [st.container()]
    col_i = 0
    if local_path:
        with dl_cols[col_i]:
            try:
                data = local_path.read_bytes()
                st.download_button(
                    f"⬇ Локально: {local_download_name(mf, local_path)}", data=data,
                    file_name=local_download_name(mf, local_path), mime="application/octet-stream",
                    key=f"dl_local_{mf.get('match_id')}_{idx}", use_container_width=True,
                )
            except OSError as exc:
                st.caption(f"⚠️ {exc}")
        col_i += 1
    if docs_with_url:
        with dl_cols[col_i]:
            if not related_docs and len(docs_with_url) > 1:
                st.info("Совпадение внутри архива — скачайте ZIP документации выше.")
                return
            if len(docs_with_url) == 1:
                doc = docs_with_url[0]
                st.link_button(f"⬇ Скачать: {doc.get('file_name') or 'Документ'}", doc["url"], use_container_width=True, key=f"dl_plat_{mf.get('match_id')}_{idx}_0")
            else:
                st.markdown("**⬇ Скачать с площадки:**")
                for doc_i, doc in enumerate(docs_with_url[:6]):
                    name = doc.get("file_name") or "Документ"
                    st.link_button(f"{_doc_icon(name)} {name}", doc["url"], use_container_width=True, key=f"dl_plat_{mf.get('match_id')}_{idx}_{doc_i}")
                if len(docs_with_url) > 6:
                    st.caption(f"Ещё {len(docs_with_url) - 6} — вкладка «Документация»")


def _render_match_file_block(
    mf: Dict[str, Any], idx: int, *, documents: List[Dict[str, Any]],
    contract_number: str | None = None,
) -> None:
    related_docs = find_related_platform_documents(mf, documents, contract_number=contract_number)
    download_docs = documents_for_download(mf, documents, contract_number=contract_number)
    platform_doc = related_docs[0] if related_docs else (download_docs[0] if download_docs else None)
    display_name = resolve_match_display_name(
        mf, platform_doc, contract_number=contract_number, related_docs=related_docs or None,
        fallback_documents=download_docs if not related_docs else None,
    )
    inner_name, pct = inner_match_file_name(mf), mf.get("match_percentage")
    pct_s = f" · {pct:.0f}%" if pct is not None else ""
    with st.expander(f"{_doc_icon(display_name)} {display_name}  ·  🎯 {mf.get('match_count', 0)} совпад.{pct_s}", expanded=idx == 0):
        if inner_name and inner_name.lower() not in display_name.lower():
            st.caption(f"📎 Файл с совпадением внутри архива: `{inner_name}`")
        _render_match_downloads(mf, idx, related_docs=related_docs, download_docs=download_docs, local_path=local_file_path(mf))
        details: List[Dict[str, Any]] = mf.get("details") or []
        if not details:
            st.info("Детали совпадений для этого файла не загружены.")
            return
        rows = []
        for d in details:
            score = d.get("score")
            rows.append({
                "Продукт": d.get("product_name") or "—",
                "Ключевые слова": ", ".join(d.get("keywords") or []) or "—",
                "Текст совпадения": _truncate(d.get("text") or ""),
                "Оценка": f"{score:.0f}" if score is not None else "—",
                "Лист / ячейка": _location_cell(d),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config={
            "Текст совпадения": st.column_config.TextColumn(width="large"),
            "Ключевые слова": st.column_config.TextColumn(width="medium"),
        })


def _filter_match_file_for_group(mf: Dict[str, Any], group_code: str | None) -> Dict[str, Any] | None:
    if not group_code or group_code == "all":
        return mf
    details = [
        d for d in (mf.get("details") or [])
        if product_name_matches_group(str(d.get("product_name") or ""), group_code)
    ]
    if not details:
        return None
    out = dict(mf)
    out["details"] = details
    out["match_count"] = len(details)
    return out


def _render_product_group_switcher(
    item,
    detail: ObjectDetailData,
    *,
    object_key: str,
    active_group: str | None,
) -> str | None:
    groups = confirmed_product_groups(item)
    if len(groups) <= 1:
        if active_group and active_group != "all":
            return active_group
        return None
    labels = dict(PRODUCT_GROUP_OPTIONS)
    options = [("all", "Все направления")] + [(code, labels.get(code, code)) for code in labels if code in groups]
    st.caption("Направление в документах:")
    cols = st.columns(min(len(options), 5))
    selected = active_group if active_group and active_group != "all" else "all"
    for idx, (code, label) in enumerate(options):
        with cols[idx % len(cols)]:
            count = (
                sum(int(mf.get("match_count") or 0) for mf in detail.match_files)
                if code == "all"
                else len(products_for_group(item, code))
            )
            if st.button(
                f"{label} ({count})",
                key=f"detail_grp_{object_key}_{code}",
                use_container_width=True,
                type="primary" if selected == code else "secondary",
            ):
                st.session_state["object_detail_product_group"] = None if code == "all" else code
                st.rerun()
    links = other_product_groups(item, None if selected == "all" else selected)
    if links and selected != "all":
        st.caption("Смотреть также: " + ", ".join(label for _code, label in links))
    return None if selected == "all" else selected


def _render_matches_tab(
    detail: ObjectDetailData,
    object_key: str,
    *,
    active_product_group: str | None = None,
) -> None:
    item = detail.item
    if not detail.match_files:
        st.info("Совпадения в документах не найдены.")
        return

    group_code = _render_product_group_switcher(
        item,
        detail,
        object_key=object_key,
        active_group=active_product_group,
    )

    filtered_files = []
    for mf in detail.match_files:
        filtered = _filter_match_file_for_group(mf, group_code)
        if filtered:
            filtered_files.append(filtered)

    if group_code and not filtered_files:
        label = dict(PRODUCT_GROUP_OPTIONS).get(group_code, group_code)
        st.info(f"Для направления «{label}» совпадений в документах нет.")
        preview = preview_line_for_group(item, group_code)
        if preview:
            st.caption(preview)
        return

    match_files = filtered_files or detail.match_files
    group_matches = (
        sum(int(mf.get("match_count") or 0) for mf in match_files)
        if group_code
        else int(item.doc_matches or 0)
    )

    _compact_metrics([
        ("Файлов с совпадениями", str(len(match_files))),
        ("Совпадений", str(group_matches)),
        ("Уровень данных", TIER_LABELS.get(item.quality_tier, "—")),
    ], cols=3)
    if group_code:
        st.caption(preview_line_for_group(item, group_code))
    _section_title("Что найдено в документах")
    if detail.documents:
        st.caption("Совпадения найдены во внутренних файлах архивов закупки. Скачайте документацию с площадки — нужный файл внутри.")
        _render_tender_zip_download(detail, object_key, prefix="matches_")
        st.divider()
    contract_number = detail.contract_number or item.contract_number
    for idx, mf in enumerate(match_files):
        _render_match_file_block(mf, idx, documents=detail.documents, contract_number=contract_number)
