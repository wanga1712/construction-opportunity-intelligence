"""РџРѕР»РЅР°СЏ РєР°СЂС‚РѕС‡РєР° РѕР±СЉРµРєС‚Р° вЂ” Salesforce-РїРѕРґРѕР±РЅС‹Р№ layout."""
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import streamlit as st


_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate"

from modules.crm.analytics.object_classifier import segment_label
from modules.crm.repositories.tender_registry_constants import registry_label
from src.constants.object_quality import TIER_LABELS
from src.services.object_detail_loader import ObjectDetailData, load_object_detail
from src.services.object_interest_service import mark_object_not_interesting
from src.services.object_leads_bridge import object_lead_status, upsert_object_lead
from src.services.match_file_display import (
    documents_for_download,
    find_related_platform_documents,
    inner_match_file_name,
    local_download_name,
    local_file_path,
    resolve_match_display_name,
)
from src.services.object_category_labels import (
    SEGMENT_LABELS,
    apply_object_category_labels,
    default_label_for_item,
    load_category_labels,
    object_label_key,
    save_category_label,
)
from src.services.object_ai_classification_store import apply_ai_classifications, save_ai_classification
from src.services.object_ai_scores import apply_object_ai_scores, save_object_ai_score
from src.services.tender_docs_bundle import (
    build_documents_zip,
    bundle_filename,
    format_size,
)
from src.services.objects_service import ObjectsService
from src.ui.object_card_format import fmt_date, is_awarded_registry


_SEGMENT_ICONS = {
    "residential": "рџЏ ",
    "social": "рџЏ›",
    "commercial": "рџЏ¬",
    "other": "рџ“¦",
}

_METRIC_ICONS = {
    "РЎРѕРІРїР°РґРµРЅРёР№": "рџЋЇ",
    "Р¤Р°Р№Р»РѕРІ": "рџ“Ѓ",
    "Р¤Р°Р№Р»РѕРІ СЃ СЃРѕРІРїР°РґРµРЅРёСЏРјРё": "рџ“Ѓ",
    "Р’СЃРµРіРѕ СЃРѕРІРїР°РґРµРЅРёР№": "рџЋЇ",
    "РЈСЂРѕРІРµРЅСЊ РґР°РЅРЅС‹С…": "рџ“Љ",
    "РќРњР¦": "рџ’°",
    "РС‚РѕРі": "вњ…",
    "РС‚РѕРіРѕРІР°СЏ": "вњ…",
    "РЎРµРіРјРµРЅС‚": "рџЏ·пёЏ",
    "РќР°С‡Р°Р»Рѕ": "в–¶пёЏ",
    "РћРєРѕРЅС‡Р°РЅРёРµ": "вЏ№пёЏ",
}

_SECTION_ICONS = {
    "Р—Р°РєСѓРїРєР°": "рџ“‹",
    "РЈС‡Р°СЃС‚РЅРёРєРё": "рџ‘Ґ",
    "Р§С‚Рѕ РЅР°Р№РґРµРЅРѕ РІ РґРѕРєСѓРјРµРЅС‚Р°С…": "рџ”Ћ",
    "РўРѕСЂРіРё": "вљ–пёЏ",
    "РџРѕСЃС‚Р°РІРєР° / РёСЃРїРѕР»РЅРµРЅРёРµ": "рџљљ",
    "Р¦РµРЅС‹": "рџ’µ",
    "Р¤Р°Р№Р»С‹ Р·Р°РєСѓРїРєРё РЅР° РїР»РѕС‰Р°РґРєРµ": "рџ“Ћ",
    "Р­РєСЃРїРµСЂС‚РёР·Р°": "рџ§ѕ",
    "NashDom": "рџЏ—пёЏ",
}

_FIELD_ICONS = {
    "Р РµРµСЃС‚СЂ": "рџ“‘",
    "в„– Р·Р°РєСѓРїРєРё": "рџ”ў",
    "Р РµРіРёРѕРЅ РїРѕСЃС‚Р°РІРєРё": "рџ“Ќ",
    "РћРљРџР”": "рџЏ·пёЏ",
    "РћРїРёСЃР°РЅРёРµ РћРљРџР”": "рџ“„",
    "РџР»РѕС‰Р°РґРєР°": "рџЊђ",
    "РЎСЃС‹Р»РєР° РїР»РѕС‰Р°РґРєРё": "рџ”—",
    "Р‘Р°Р»Р°РЅСЃРѕРґРµСЂР¶Р°С‚РµР»СЊ": "рџЏ›пёЏ",
    "РћСЂРіР°РЅРёР·Р°С‚РѕСЂ С‚РѕСЂРіРѕРІ": "рџЏў",
    "РџРѕР±РµРґРёС‚РµР»СЊ": "рџЏ†",
}


def _doc_icon(file_name: str) -> str:
    lower = (file_name or "").lower()
    if lower.endswith(".pdf"):
        return "рџ“•"
    if lower.endswith((".zip", ".rar", ".7z")):
        return "рџ—њпёЏ"
    if lower.endswith((".xlsx", ".xls")):
        return "рџ“Љ"
    if lower.endswith((".docx", ".doc")):
        return "рџ“ќ"
    return "рџ“„"


def _fmt_price(val: Optional[float]) -> str:
    if val is None:
        return "вЂ”"
    try:
        v = float(val)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.2f} РјР»РЅ в‚Ѕ"
        return f"{v:,.0f} в‚Ѕ".replace(",", " ")
    except (TypeError, ValueError):
        return str(val)


def _truncate(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "вЂ¦"


def _location_cell(d: Dict[str, Any]) -> str:
    parts = []
    if d.get("sheet_name"):
        parts.append(str(d["sheet_name"]))
    if d.get("cell_address"):
        parts.append(str(d["cell_address"]))
    if d.get("line_number"):
        parts.append(f"СЃС‚СЂ. {d['line_number']}")
    return " / ".join(parts) or "вЂ”"


def _compact_metrics(
    items: List[tuple[str, str]],
    cols: int | None = None,
    *,
    icons: Dict[str, str] | None = None,
) -> None:
    """РљРѕРјРїР°РєС‚РЅС‹Рµ РїРѕРєР°Р·Р°С‚РµР»Рё Р±РµР· РіРёРіР°РЅС‚СЃРєРёС… С†РёС„СЂ Streamlit metric."""
    icon_map = icons or _METRIC_ICONS
    n = cols or len(items)
    columns = st.columns(n)
    for col, (label, value) in zip(columns, items):
        with col:
            icon = icon_map.get(label, "в–ЄпёЏ")
            if label == "РЎРµРіРјРµРЅС‚" and value != "вЂ”":
                for key, seg_icon in _SEGMENT_ICONS.items():
                    if segment_label(key) == value or key in value.lower():
                        icon = seg_icon
                        break
            st.markdown(
                f'<div class="sf-metric">'
                f'<div class="sf-metric-label">'
                f'<span class="sf-ico">{icon}</span>{html.escape(label)}</div>'
                f'<div class="sf-metric-value">{html.escape(str(value))}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )


def _section_title(text: str, icon: str | None = None) -> None:
    ico = icon or _SECTION_ICONS.get(text, "")
    prefix = f'<span class="sf-section-ico">{ico}</span>' if ico else ""
    st.markdown(
        f'<div class="sf-section-title">{prefix}{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def _sf_fields(fields: List[tuple[str, Optional[str]]], cols: int = 2) -> None:
    """Р”РІСѓС…РєРѕР»РѕРЅРѕС‡РЅР°СЏ СЃРµС‚РєР° РїРѕР»РµР№ РІ СЃС‚РёР»Рµ Salesforce record page."""
    visible = [(lbl, val) for lbl, val in fields if val and str(val).strip() and str(val) != "вЂ”"]
    if not visible:
        st.caption("РќРµС‚ РґР°РЅРЅС‹С…")
        return
    rows = [visible[i : i + cols] for i in range(0, len(visible), cols)]
    for row in rows:
        columns = st.columns(cols)
        for col, (label, value) in zip(columns, row):
            with col:
                field_icon = _FIELD_ICONS.get(label, "")
                icon_html = f'<span class="sf-ico">{field_icon}</span>' if field_icon else ""
                st.markdown(
                    f'<div class="sf-field">'
                    f'<div class="sf-field-label">{icon_html}{html.escape(label)}</div>'
                    f'<div class="sf-field-value">{html.escape(str(value))}</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
        if len(row) < cols:
            break


def _render_tender_zip_download(
    detail: ObjectDetailData,
    object_key: str,
    *,
    prefix: str = "",
) -> None:
    docs = [d for d in detail.documents if d.get("url")]
    if not docs:
        return

    bundle_key = f"docs_zip_{object_key}"
    contract = detail.contract_number or detail.item.contract_number
    zip_name = bundle_filename(contract, detail.item.tender_id)
    build_key = f"{prefix}build_zip_{object_key}"
    dl_key = f"{prefix}dl_zip_{object_key}"

    if st.button(
        f"рџ“¦ РЎРєР°С‡Р°С‚СЊ РІСЃСЋ РґРѕРєСѓРјРµРЅС‚Р°С†РёСЋ РѕРґРЅРёРј ZIP ({len(docs)} С„Р°Р№Р»РѕРІ)",
        key=build_key,
        use_container_width=True,
    ):
        with st.spinner(f"РЎРєР°С‡РёРІР°СЋ {len(docs)} С„Р°Р№Р»РѕРІ СЃ РїР»РѕС‰Р°РґРєРё Рё СѓРїР°РєРѕРІС‹РІР°СЋвЂ¦"):
            try:
                zip_bytes, stats = build_documents_zip(docs)
                st.session_state[bundle_key] = (zip_bytes, stats)
            except Exception as exc:
                st.error(f"РќРµ СѓРґР°Р»РѕСЃСЊ СЃРѕР±СЂР°С‚СЊ Р°СЂС…РёРІ: {exc}")
                return
        st.rerun()

    cached = st.session_state.get(bundle_key)
    if cached:
        zip_bytes, stats = cached
        size_label = format_size(stats.get("size_bytes", len(zip_bytes)))
        st.download_button(
            f"в¬‡ РЎРѕС…СЂР°РЅРёС‚СЊ {zip_name} В· {stats.get('ok', 0)}/{stats.get('total', 0)} В· {size_label}",
            data=zip_bytes,
            file_name=zip_name,
            mime="application/zip",
            key=dl_key,
            use_container_width=True,
            type="primary",
        )
        failed = stats.get("failed") or []
        if failed:
            st.warning(
                "РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ: "
                + "; ".join(html.escape(x) for x in failed[:5])
                + ("вЂ¦" if len(failed) > 5 else "")
            )


def _render_match_downloads(
    mf: Dict[str, Any],
    idx: int,
    *,
    related_docs: List[Dict[str, Any]],
    download_docs: List[Dict[str, Any]],
    local_path,
) -> None:
    docs_with_url = [d for d in download_docs if d.get("url")]
    if not local_path and not docs_with_url:
        yp = (mf.get("yandex_path") or "").strip()
        if yp:
            st.caption(f"рџ“Ѓ Р¤Р°Р№Р» РЅР° РґРёСЃРєРµ: `{yp}` вЂ” РЅРµРґРѕСЃС‚СѓРїРµРЅ СЃ СЌС‚РѕР№ РјР°С€РёРЅС‹.")
        elif download_docs:
            st.caption("РЎСЃС‹Р»РєРё РЅР° СЃРєР°С‡РёРІР°РЅРёРµ РІ Р‘Р” РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚ вЂ” СЃРј. РІРєР»Р°РґРєСѓ В«Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏВ».")
        return

    if local_path and docs_with_url:
        dl_cols = st.columns(2)
    else:
        dl_cols = [st.container()]

    col_i = 0
    if local_path:
        with dl_cols[col_i]:
            try:
                data = local_path.read_bytes()
                st.download_button(
                    f"в¬‡ Р›РѕРєР°Р»СЊРЅРѕ: {local_download_name(mf, local_path)}",
                    data=data,
                    file_name=local_download_name(mf, local_path),
                    mime="application/octet-stream",
                    key=f"dl_local_{mf.get('match_id')}_{idx}",
                    use_container_width=True,
                )
            except OSError as exc:
                st.caption(f"вљ пёЏ {exc}")
        col_i += 1

    if docs_with_url:
        with dl_cols[col_i]:
            if not related_docs and len(docs_with_url) > 1:
                st.info("РЎРѕРІРїР°РґРµРЅРёРµ РІРЅСѓС‚СЂРё Р°СЂС…РёРІР° вЂ” СЃРєР°С‡Р°Р№С‚Рµ ZIP РґРѕРєСѓРјРµРЅС‚Р°С†РёРё РІС‹С€Рµ.")
                return
            if len(docs_with_url) == 1:
                doc = docs_with_url[0]
                name = doc.get("file_name") or "Р”РѕРєСѓРјРµРЅС‚"
                st.link_button(
                    f"в¬‡ РЎРєР°С‡Р°С‚СЊ: {name}",
                    doc["url"],
                    use_container_width=True,
                    key=f"dl_plat_{mf.get('match_id')}_{idx}_0",
                )
            else:
                st.markdown("**в¬‡ РЎРєР°С‡Р°С‚СЊ СЃ РїР»РѕС‰Р°РґРєРё:**")
                for doc_i, doc in enumerate(docs_with_url[:6]):
                    name = doc.get("file_name") or "Р”РѕРєСѓРјРµРЅС‚"
                    st.link_button(
                        f"{_doc_icon(name)} {name}",
                        doc["url"],
                        use_container_width=True,
                        key=f"dl_plat_{mf.get('match_id')}_{idx}_{doc_i}",
                    )
                if len(docs_with_url) > 6:
                    st.caption(f"Р•С‰С‘ {len(docs_with_url) - 6} вЂ” РІРєР»Р°РґРєР° В«Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏВ»")


def _render_match_file_block(
    mf: Dict[str, Any],
    idx: int,
    *,
    documents: List[Dict[str, Any]],
    contract_number: str | None = None,
) -> None:
    related_docs = find_related_platform_documents(
        mf, documents, contract_number=contract_number,
    )
    download_docs = documents_for_download(
        mf, documents, contract_number=contract_number,
    )
    platform_doc = related_docs[0] if related_docs else (
        download_docs[0] if download_docs else None
    )
    display_name = resolve_match_display_name(
        mf, platform_doc,
        contract_number=contract_number,
        related_docs=related_docs or None,
        fallback_documents=download_docs if not related_docs else None,
    )
    inner_name = inner_match_file_name(mf)
    pct = mf.get("match_percentage")
    pct_s = f" В· {pct:.0f}%" if pct is not None else ""
    icon = _doc_icon(display_name)
    header = f"{icon} {display_name}  В·  рџЋЇ {mf.get('match_count', 0)} СЃРѕРІРїР°Рґ.{pct_s}"

    with st.expander(header, expanded=idx == 0):
        if inner_name and inner_name.lower() not in display_name.lower():
            st.caption(f"рџ“Ћ Р¤Р°Р№Р» СЃ СЃРѕРІРїР°РґРµРЅРёРµРј РІРЅСѓС‚СЂРё Р°СЂС…РёРІР°: `{inner_name}`")

        _render_match_downloads(
            mf, idx,
            related_docs=related_docs,
            download_docs=download_docs,
            local_path=local_file_path(mf),
        )

        details: List[Dict[str, Any]] = mf.get("details") or []
        if not details:
            st.info("Р”РµС‚Р°Р»Рё СЃРѕРІРїР°РґРµРЅРёР№ РґР»СЏ СЌС‚РѕРіРѕ С„Р°Р№Р»Р° РЅРµ Р·Р°РіСЂСѓР¶РµРЅС‹.")
            return

        rows = []
        for d in details:
            kw = ", ".join(d.get("keywords") or []) or "вЂ”"
            score = d.get("score")
            score_s = f"{score:.0f}" if score is not None else "вЂ”"
            rows.append({
                "РџСЂРѕРґСѓРєС‚": d.get("product_name") or "вЂ”",
                "РљР»СЋС‡РµРІС‹Рµ СЃР»РѕРІР°": kw,
                "РўРµРєСЃС‚ СЃРѕРІРїР°РґРµРЅРёСЏ": _truncate(d.get("text") or ""),
                "РћС†РµРЅРєР°": score_s,
                "Р›РёСЃС‚ / СЏС‡РµР№РєР°": _location_cell(d),
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "РўРµРєСЃС‚ СЃРѕРІРїР°РґРµРЅРёСЏ": st.column_config.TextColumn(width="large"),
                "РљР»СЋС‡РµРІС‹Рµ СЃР»РѕРІР°": st.column_config.TextColumn(width="medium"),
            },
        )


def _render_matches_tab(detail: ObjectDetailData, object_key: str) -> None:
    item = detail.item
    if not detail.match_files:
        st.info("РЎРѕРІРїР°РґРµРЅРёСЏ РІ РґРѕРєСѓРјРµРЅС‚Р°С… РЅРµ РЅР°Р№РґРµРЅС‹.")
        return

    _compact_metrics([
        ("Р¤Р°Р№Р»РѕРІ СЃ СЃРѕРІРїР°РґРµРЅРёСЏРјРё", str(len(detail.match_files))),
        ("Р’СЃРµРіРѕ СЃРѕРІРїР°РґРµРЅРёР№", str(item.doc_matches or 0)),
        ("РЈСЂРѕРІРµРЅСЊ РґР°РЅРЅС‹С…", TIER_LABELS.get(item.quality_tier, "вЂ”")),
    ], cols=3)

    _section_title("Р§С‚Рѕ РЅР°Р№РґРµРЅРѕ РІ РґРѕРєСѓРјРµРЅС‚Р°С…")
    if detail.documents:
        st.caption(
            "РЎРѕРІРїР°РґРµРЅРёСЏ РЅР°Р№РґРµРЅС‹ РІРѕ РІРЅСѓС‚СЂРµРЅРЅРёС… С„Р°Р№Р»Р°С… Р°СЂС…РёРІРѕРІ Р·Р°РєСѓРїРєРё. "
            "РЎРєР°С‡Р°Р№С‚Рµ РґРѕРєСѓРјРµРЅС‚Р°С†РёСЋ СЃ РїР»РѕС‰Р°РґРєРё вЂ” РЅСѓР¶РЅС‹Р№ С„Р°Р№Р» РІРЅСѓС‚СЂРё."
        )
        _render_tender_zip_download(detail, object_key, prefix="matches_")
        st.divider()

    contract_number = detail.contract_number or item.contract_number
    for idx, mf in enumerate(detail.match_files):
        _render_match_file_block(
            mf, idx,
            documents=detail.documents,
            contract_number=contract_number,
        )


def _render_docs_tab(detail: ObjectDetailData, object_key: str) -> None:
    docs = detail.documents
    if not docs:
        st.info("РЎСЃС‹Р»РєРё РЅР° РґРѕРєСѓРјРµРЅС‚Р°С†РёСЋ Р·Р°РєСѓРїРєРё РЅРµ РЅР°Р№РґРµРЅС‹ РІ Р‘Р”.")
        return

    _section_title("Р¤Р°Р№Р»С‹ Р·Р°РєСѓРїРєРё РЅР° РїР»РѕС‰Р°РґРєРµ")
    st.caption(
        f"Р’СЃРµРіРѕ **{len(docs)}** С„Р°Р№Р»РѕРІ. РњРѕР¶РЅРѕ СЃРєР°С‡Р°С‚СЊ РѕРґРЅРёРј ZIP вЂ” РІСЃРµ С‡Р°СЃС‚Рё Р°СЂС…РёРІР° РІРЅСѓС‚СЂРё."
    )

    _render_tender_zip_download(detail, object_key)

    with st.expander(f"рџ“Ћ РЎРєР°С‡Р°С‚СЊ РїРѕ РѕРґРЅРѕРјСѓ ({len(docs)})", expanded=False):
        for doc in docs:
            url = doc.get("url") or ""
            raw_name = doc.get("file_name") or "Р”РѕРєСѓРјРµРЅС‚"
            name = html.escape(raw_name)
            icon = _doc_icon(raw_name)
            if url:
                st.markdown(f"- {icon} [{name}]({url})")
            else:
                st.markdown(f"- {icon} {name}")


def _can_dismiss(item) -> bool:
    return bool(item.tender_id and item.registry_type and "nashdom" not in (item.sources or []))

def _render_ai_shadow(item) -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "ai_shadow" / "model_suggestions_filtered.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("procurement_id")) == str(item.tender_id):
            st.markdown("### рџ¤– AI-Р°РЅР°Р»РёР· (С‚РµРЅРµРІРѕР№ СЂРµР¶РёРј)")
            st.caption("Р РµР·СѓР»СЊС‚Р°С‚ РјРѕРґРµР»Рё РЅРµ РёР·РјРµРЅСЏРµС‚ С„РёР»СЊС‚СЂС‹ Рё С‚СЂРµР±СѓРµС‚ РїСЂРѕРІРµСЂРєРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ.")
            st.code(row.get("model_response", ""), language="json")
            break


def _render_ai_shadow_v2(detail: ObjectDetailData) -> None:
    item = detail.item
    path = Path(__file__).resolve().parents[2] / "data" / "ai_shadow" / "model_suggestions_filtered.jsonl"
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "data" / "ai_shadow" / "model_suggestions.jsonl"
    tender_id = str(item.tender_id or "")
    contract = str(detail.contract_number or item.contract_number or "")
    found = None
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            keys = {str(row.get(k) or "") for k in ("procurement_id", "tender_id", "contract_number", "tender_number")}
            if (tender_id and tender_id in keys) or (contract and contract in keys):
                found = row
                break
    def _extract_ai_json(text: str) -> dict:
        raw = (text or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    return {}
        return {}

    def _build_prompt() -> str:
        return (
            "РўС‹ AI-Р°РЅР°Р»РёС‚РёРє CRM РґР»СЏ РѕР±СЉРµРєС‚РЅРѕ-РїСЂРѕРµРєС‚РЅС‹С… РїСЂРѕРґР°Р¶ СЃС‚СЂРѕРёС‚РµР»СЊРЅС‹С… РјР°С‚РµСЂРёР°Р»РѕРІ. "
            "РќСѓР¶РЅРѕ РЅРµ РїРёСЃР°С‚СЊ РѕР±С‰РёРµ СЃР»РѕРІР°, Р° РґР°С‚СЊ РїСЂРёРєР»Р°РґРЅСѓСЋ РѕС†РµРЅРєСѓ Р·Р°РєСѓРїРєРё РґР»СЏ РјРµРЅРµРґР¶РµСЂР°.\n"
            "РљР»Р°СЃСЃРёС„РёС†РёСЂСѓР№ РѕР±СЉРµРєС‚ Рё РѕС†РµРЅРё РїСЂРёРѕСЂРёС‚РµС‚ РѕР±СЂР°Р±РѕС‚РєРё.\n\n"
            "Р’РµСЂРЅРё С‚РѕР»СЊРєРѕ JSON Р±РµР· markdown Рё Р±РµР· РїРѕСЏСЃРЅРµРЅРёР№ РІРѕРєСЂСѓРі JSON. РЎС…РµРјР°:\n"
            "{"
            '"decision":"keep|review|exclude",'
            '"segment":"social|commercial|residential|other",'
            '"label":"Р“РѕСЃСѓРґР°СЂСЃС‚РІРµРЅРЅС‹Р№ / СЃРѕС†РёР°Р»СЊРЅС‹Р№|РљРѕРјРјРµСЂС‡РµСЃРєРёР№|Р–РёР»РѕР№ РѕР±СЉРµРєС‚|РџСЂРѕС‡РµРµ",'
            '"priority_score":0-100,'
            '"delivery_chance":"РІС‹СЃРѕРєРёР№|СЃСЂРµРґРЅРёР№|РЅРёР·РєРёР№",'
            '"volume_signal":"РєСЂСѓРїРЅС‹Р№|СЃСЂРµРґРЅРёР№|РјР°Р»С‹Р№|РЅРµРёР·РІРµСЃС‚РЅРѕ",'
            '"reason":"РєРѕСЂРѕС‚РєРѕ: РїРѕС‡РµРјСѓ СЌС‚Рѕ РёРЅС‚РµСЂРµСЃРЅРѕ РёР»Рё СЂРёСЃРєРѕРІР°РЅРЅРѕ",'
            '"object_type":"С€РєРѕР»Р°/Р±РѕР»СЊРЅРёС†Р°/РњРљР”/РѕС„РёСЃ/РґРѕСЂРѕРіР°/РїСЂРѕС‡РµРµ",'
            '"materials_found":["..."],'
            '"volumes_found":["..."],'
            '"dates":{"bid_end":"","delivery_start":"","delivery_end":""},'
            '"risks":["..."],'
            '"missing_data":["С‡С‚Рѕ РЅРµ РЅР°Р№РґРµРЅРѕ, РЅР°РїСЂРёРјРµСЂ РѕР±СЉРµРјС‹ РјР°С‚РµСЂРёР°Р»РѕРІ"]'
            "}\n\n"
            "РџСЂР°РІРёР»Р°:\n"
            "- РњР‘РћРЈ/РЎРћРЁ/С€РєРѕР»Р°/РґРµС‚СЃР°Рґ/Р“Р‘РЈР—/Р±РѕР»СЊРЅРёС†Р°/РјСѓРЅРёС†РёРїР°Р»СЊРЅРѕРµ РёР»Рё Р±СЋРґР¶РµС‚РЅРѕРµ СѓС‡СЂРµР¶РґРµРЅРёРµ/РєСѓР»СЊС‚СѓСЂРЅРѕРµ РЅР°СЃР»РµРґРёРµ => social.\n"
            "- РњРљР”/Р¶РёР»РѕР№ РґРѕРј/РјРЅРѕРіРѕРєРІР°СЂС‚РёСЂРЅС‹Р№ РґРѕРј/Р–Рљ => residential.\n"
            "- 223-Р¤Р— РёР»Рё РєРѕРјРјРµСЂС‡РµСЃРєРёР№ Р·Р°РєР°Р·С‡РёРє => commercial.\n"
            "- Р•СЃР»Рё РѕР±СЉС‘РјС‹ РјР°С‚РµСЂРёР°Р»РѕРІ РЅРµ РІРёРґРЅС‹ РІ РґР°РЅРЅС‹С… РєР°СЂС‚РѕС‡РєРё, РїСЂСЏРјРѕ РЅР°РїРёС€Рё СЌС‚Рѕ РІ missing_data; РЅРµ РІС‹РґСѓРјС‹РІР°Р№ РѕР±СЉС‘РјС‹.\n"
            "- РџСЂРёРѕСЂРёС‚РµС‚ РІС‹С€Рµ, РµСЃР»Рё РѕР±СЉРµРєС‚ РєСЂСѓРїРЅС‹Р№, СЃСЂРѕРє РёСЃРїРѕР»РЅРµРЅРёСЏ РµС‰С‘ РїРѕР·РІРѕР»СЏРµС‚ Р·Р°Р№С‚Рё, РµСЃС‚СЊ РґРѕРєСѓРјРµРЅС‚С‹ Рё СЃРѕРІРїР°РґРµРЅРёСЏ.\n"
            "- Р•СЃР»Рё СЃСЂРѕРє Р±Р»РёР·РєРёР№ РёР»Рё РїСЂРѕС€С‘Р», chance СЃРЅРёР¶Р°Р№ Рё СѓРєР°Р¶Рё СЂРёСЃРє.\n\n"
            "Р”Р°РЅРЅС‹Рµ РєР°СЂС‚РѕС‡РєРё:\n"
            f"РќР°Р·РІР°РЅРёРµ: {item.name}\n"
            f"РћРљРџР”: {detail.okpd_code or ''}\n"
            f"РћРїРёСЃР°РЅРёРµ РћРљРџР”: {detail.okpd_name or ''}\n"
            f"Р РµРіРёРѕРЅ/Р°РґСЂРµСЃ: {detail.delivery_region or item.address or ''}\n"
            f"РќРњР¦: {detail.initial_price or ''}\n"
            f"РќРѕРјРµСЂ Р·Р°РєСѓРїРєРё/РєРѕРЅС‚СЂР°РєС‚Р°: {detail.contract_number or item.contract_number or ''}\n"
            f"РЎС‚Р°С‚СѓСЃ: {item.status or ''}; СЂРµРµСЃС‚СЂ: {item.registry_type or ''}\n"
            f"Р—Р°РєР°Р·С‡РёРє/РѕСЂРіР°РЅРёР·Р°С‚РѕСЂ: {item.customer_name or ''} {item.customer_inn or ''}\n"
            f"Р‘Р°Р»Р°РЅСЃРѕРґРµСЂР¶Р°С‚РµР»СЊ: {item.balance_holder or ''}\n"
            f"РџРѕРґСЂСЏРґС‡РёРє: {item.contractor_name or ''} {item.contractor_inn or ''}\n"
            f"РЎСЂРѕРє С‚РѕСЂРіРѕРІ: {item.start_date or ''} вЂ” {item.end_date or ''}\n"
            f"РЎСЂРѕРє РїРѕСЃС‚Р°РІРєРё/РёСЃРїРѕР»РЅРµРЅРёСЏ: {item.delivery_start_date or ''} вЂ” {item.delivery_end_date or ''}\n"
            f"РЎРѕРІРїР°РґРµРЅРёР№ РІ РґРѕРєСѓРјРµРЅС‚Р°С…: {item.doc_matches}; С„Р°Р№Р»РѕРІ СЃ СЃРѕРІРїР°РґРµРЅРёСЏРјРё: {item.matched_files}\n"
        )

    def _call_and_apply_ai() -> dict:
        payload = json.dumps({"model": "qwen2.5:7b", "prompt": _build_prompt(), "stream": False}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(_OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=75) as resp:
            response = json.loads(resp.read().decode("utf-8")).get("response", "")
        parsed = _extract_ai_json(response)
        if parsed:
            label = str(parsed.get("label") or "").strip()
            segment = str(parsed.get("segment") or "").strip()
            if not label and segment in SEGMENT_LABELS:
                label = SEGMENT_LABELS[segment]
            if label:
                save_category_label(item, label, source="ai_card")
            save_object_ai_score(item, parsed, source="ai_card")
            save_ai_classification(item, parsed, label=label, source="ai_card")
            ai_path = Path(__file__).resolve().parents[2] / "data" / "ai_shadow" / "card_ai_analysis.jsonl"
            ai_path.parent.mkdir(parents=True, exist_ok=True)
            with ai_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "tender_id": item.tender_id,
                    "registry_type": item.registry_type,
                    "contract_number": detail.contract_number or item.contract_number,
                    "response": parsed,
                }, ensure_ascii=False) + "\n")
            return {"model_response": json.dumps(parsed, ensure_ascii=False, indent=2), "parsed": parsed}
        return {"model_response": response}

    st.markdown("### рџ¤– AI-Р°РЅР°Р»РёР· Р·Р°РєСѓРїРєРё")
    st.caption("AI-СЂР°Р·РјРµС‚РєР° РјРѕР¶РµС‚ РѕР±РЅРѕРІРёС‚СЊ РєР°С‚РµРіРѕСЂРёСЋ, РїСЂРёРѕСЂРёС‚РµС‚ Рё РїРѕСЂСЏРґРѕРє РїРѕРєР°Р·Р° РІ CRM.")

    if st.button("РћР±РЅРѕРІРёС‚СЊ AI-Р°РЅР°Р»РёР· Рё РїСЂРёРјРµРЅРёС‚СЊ Рє РєР°СЂС‚РѕС‡РєРµ", key=f"refresh_ai_{item.registry_type}_{item.tender_id}"):
        with st.spinner("РњРѕРґРµР»СЊ Р°РЅР°Р»РёР·РёСЂСѓРµС‚ РєР°СЂС‚РѕС‡РєСѓ Рё СЃРѕС…СЂР°РЅСЏРµС‚ СЂР°Р·РјРµС‚РєСѓвЂ¦"):
            try:
                found = _call_and_apply_ai()
                st.success("AI-Р°РЅР°Р»РёР· СЃРѕС…СЂР°РЅС‘РЅ: РєР°С‚РµРіРѕСЂРёСЏ Рё РїСЂРёРѕСЂРёС‚РµС‚ РїСЂРёРјРµРЅРµРЅС‹.")
                st.rerun()
            except Exception as exc:
                found = {"error": str(exc)}

    if found is None:
        prompt = (
            _build_prompt()
        )
        try:
            payload = json.dumps({"model": "qwen2.5:7b", "prompt": prompt, "stream": False}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(_OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                answer = json.loads(resp.read().decode("utf-8"))
            found = {"model_response": answer.get("response", "")}
        except Exception as exc:
            found = {"error": str(exc)}
    if found and found.get("error"):
        st.warning(f"AI РІСЂРµРјРµРЅРЅРѕ РЅРµРґРѕСЃС‚СѓРїРµРЅ: {found['error']}")
    elif found:
        response_text = found.get("model_response", found.get("response", ""))
        parsed = found.get("parsed") or _extract_ai_json(response_text)
        if parsed:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("AI РїСЂРёРѕСЂРёС‚РµС‚", parsed.get("priority_score", parsed.get("priority", "вЂ”")))
            c2.metric("РЁР°РЅСЃ РїРѕСЃС‚Р°РІРєРё", parsed.get("delivery_chance", "вЂ”"))
            c3.metric("РћР±СЉС‘Рј", parsed.get("volume_signal", "вЂ”"))
            c4.metric("Р РµС€РµРЅРёРµ", parsed.get("decision", "вЂ”"))
            st.caption(parsed.get("reason", ""))
            if parsed.get("missing_data"):
                st.warning("РќРµ С…РІР°С‚Р°РµС‚ РґР°РЅРЅС‹С…: " + "; ".join(map(str, parsed.get("missing_data") or [])))
            with st.expander("JSON AI-Р°РЅР°Р»РёР·Р°"):
                st.json(parsed)
        else:
            st.code(response_text, language="json")
    else:
        st.info("AI-СЂРµР·СѓР»СЊС‚Р°С‚ РґР»СЏ СЌС‚РѕР№ Р·Р°РєСѓРїРєРё РµС‰С‘ РЅРµ СЃС„РѕСЂРјРёСЂРѕРІР°РЅ.")


def _render_procurement_chat(detail: ObjectDetailData) -> None:
    """Object-level AI advisor with chat and recommended next actions."""
    item = detail.item
    root = Path(__file__).resolve().parents[2] / "data" / "ai_shadow"
    root.mkdir(parents=True, exist_ok=True)
    memory_path = root / "user_knowledge.jsonl"
    advice_path = root / "object_ai_advice.jsonl"
    chat_key = f"procurement_chat_{item.registry_type}_{item.tender_id}"
    messages = st.session_state.setdefault(chat_key, [])

    def _load_memory() -> str:
        knowledge = []
        if memory_path.exists():
            for line in memory_path.read_text(encoding="utf-8").splitlines()[-120:]:
                try:
                    knowledge.append(json.loads(line))
                except Exception:
                    pass
        return "\n".join(f"- {x.get('text','')}" for x in knowledge[-50:]) or "(РїРѕРєР° РЅРµС‚ РѕР±С‰РµР№ РїР°РјСЏС‚Рё)"

    def _object_context() -> str:
        return (
            f"РќР°Р·РІР°РЅРёРµ: {item.name}\n"
            f"РћРљРџР”: {detail.okpd_code or ''} вЂ” {detail.okpd_name or ''}\n"
            f"Р РµРіРёРѕРЅ/Р°РґСЂРµСЃ: {detail.delivery_region or item.address or ''}\n"
            f"РќРњР¦: {detail.initial_price or ''}; РёС‚РѕРіРѕРІР°СЏ С†РµРЅР°: {detail.final_price or ''}\n"
            f"РќРѕРјРµСЂ Р·Р°РєСѓРїРєРё/РєРѕРЅС‚СЂР°РєС‚Р°: {detail.contract_number or item.contract_number or ''}\n"
            f"РЎС‚Р°С‚СѓСЃ: {item.status or ''}; СЂРµРµСЃС‚СЂ: {item.registry_type or ''}\n"
            f"Р—Р°РєР°Р·С‡РёРє/РѕСЂРіР°РЅРёР·Р°С‚РѕСЂ: {item.customer_name or ''} {item.customer_inn or ''}\n"
            f"Р‘Р°Р»Р°РЅСЃРѕРґРµСЂР¶Р°С‚РµР»СЊ: {item.balance_holder or ''}\n"
            f"РџРѕРґСЂСЏРґС‡РёРє/РїРѕР±РµРґРёС‚РµР»СЊ: {item.contractor_name or ''} {item.contractor_inn or ''}\n"
            f"РЎСЂРѕРє С‚РѕСЂРіРѕРІ: {item.start_date or ''} вЂ” {item.end_date or ''}\n"
            f"РЎСЂРѕРє РїРѕСЃС‚Р°РІРєРё/РёСЃРїРѕР»РЅРµРЅРёСЏ: {item.delivery_start_date or ''} вЂ” {item.delivery_end_date or ''}\n"
            f"РЎРѕРІРїР°РґРµРЅРёР№ РІ РґРѕРєСѓРјРµРЅС‚Р°С…: {item.doc_matches}; С„Р°Р№Р»РѕРІ СЃ СЃРѕРІРїР°РґРµРЅРёСЏРјРё: {item.matched_files}\n"
            f"AI priority: {item.ai_priority_score or ''}; С€Р°РЅСЃ: {item.ai_delivery_chance or ''}; РѕР±СЉС‘Рј: {item.ai_volume_signal or ''}\n"
            f"AI reason: {item.ai_priority_reason or ''}\n"
        )

    def _ask_model(question: str, *, save_user_knowledge: bool = False) -> str:
        context = _load_memory()
        prompt = (
            "РўС‹ AI-СЃРѕРІРµС‚РЅРёРє РІРЅСѓС‚СЂРё РєР°СЂС‚РѕС‡РєРё CRM РїРѕ РѕР±СЉРµРєС‚РЅРѕ-РїСЂРѕРµРєС‚РЅС‹Рј РїСЂРѕРґР°Р¶Р°Рј СЃС‚СЂРѕРёС‚РµР»СЊРЅС‹С… РјР°С‚РµСЂРёР°Р»РѕРІ. "
            "РћС‚РІРµС‡Р°Р№ РїРѕ-СЂСѓСЃСЃРєРё, РєРѕРЅРєСЂРµС‚РЅРѕ Рё РїСЂРёРєР»Р°РґРЅРѕ.\n\n"
            "РўРµРєСѓС‰Р°СЏ РєР°СЂС‚РѕС‡РєР° РѕР±СЉРµРєС‚Р°:\n"
            f"{_object_context()}\n"
            "РћР±С‰Р°СЏ РїР°РјСЏС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Рё РїСЂРµРґС‹РґСѓС‰РёРµ Р·РЅР°РЅРёСЏ:\n"
            f"{context}\n\n"
            "Р§С‚Рѕ РЅСѓР¶РЅРѕ СЃРґРµР»Р°С‚СЊ:\n"
            f"{question}\n\n"
            "Р¤РѕСЂРјР°С‚ РѕС‚РІРµС‚Р°:\n"
            "1) РљРѕСЂРѕС‚РєРёР№ РІС‹РІРѕРґ РїРѕ РѕР±СЉРµРєС‚Сѓ.\n"
            "2) Р РµРєРѕРјРµРЅРґРѕРІР°РЅРЅС‹Р№ СЃР»РµРґСѓСЋС‰РёР№ С€Р°Рі.\n"
            "3) РљР°РєРёРµ РґР°РЅРЅС‹Рµ/РґРѕРєСѓРјРµРЅС‚С‹ РЅСѓР¶РЅС‹.\n"
            "4) Р РёСЃРєРё.\n"
            "5) РџСЂРёРѕСЂРёС‚РµС‚ A/B/C Рё РїРѕС‡РµРјСѓ.\n"
            "РќРµ РІС‹РґСѓРјС‹РІР°Р№ С„Р°РєС‚С‹. Р•СЃР»Рё РѕР±СЉС‘РјРѕРІ, РјР°С‚РµСЂРёР°Р»РѕРІ РёР»Рё РєРѕРЅС‚Р°РєС‚РѕРІ РЅРµС‚ вЂ” РїСЂСЏРјРѕ СЃРєР°Р¶Рё, С‡С‚Рѕ РѕРЅРё РЅРµ РЅР°Р№РґРµРЅС‹."
        )
        try:
            payload = json.dumps(
                {"model": "qwen2.5:7b", "prompt": prompt, "stream": False},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                _OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=75) as resp:
                answer = json.loads(resp.read().decode("utf-8")).get("response", "РќРµС‚ РѕС‚РІРµС‚Р°")
        except Exception as exc:
            answer = f"РњРѕРґРµР»СЊ РІСЂРµРјРµРЅРЅРѕ РЅРµРґРѕСЃС‚СѓРїРЅР°: {exc}"

        with advice_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tender_id": item.tender_id,
                "registry_type": item.registry_type,
                "question": question,
                "answer": answer,
            }, ensure_ascii=False) + "\n")
        if save_user_knowledge:
            with memory_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"tender_id": item.tender_id, "text": question}, ensure_ascii=False) + "\n")
        return answer

    st.markdown("### рџ’¬ AI-СЃРѕРІРµС‚РЅРёРє РїРѕ РѕР±СЉРµРєС‚Сѓ")
    st.caption("РћР±С‰РµРЅРёРµ Рё СЂРµРєРѕРјРµРЅРґР°С†РёРё РїСЂРёРІСЏР·Р°РЅС‹ Рє СЌС‚РѕР№ РєР°СЂС‚РѕС‡РєРµ; РїРѕР»РµР·РЅС‹Рµ Р·РЅР°РЅРёСЏ СЃРѕС…СЂР°РЅСЏСЋС‚СЃСЏ РґР»СЏ СЃР»РµРґСѓСЋС‰РёС… РѕР±СЉРµРєС‚РѕРІ.")

    a1, a2, a3 = st.columns(3)
    quick_actions = [
        (a1, "РЎР»РµРґСѓСЋС‰РёР№ С€Р°Рі", "Р”Р°Р№ РєРѕРЅРєСЂРµС‚РЅС‹Р№ СЃР»РµРґСѓСЋС‰РёР№ С€Р°Рі РјРµРЅРµРґР¶РµСЂСѓ РїРѕ СЌС‚РѕРјСѓ РѕР±СЉРµРєС‚Сѓ: РєРѕРјСѓ РїРёСЃР°С‚СЊ/Р·РІРѕРЅРёС‚СЊ, С‡С‚Рѕ Р·Р°РїСЂРѕСЃРёС‚СЊ, С‡С‚Рѕ РїСЂРѕРІРµСЂРёС‚СЊ РїРµСЂРІС‹Рј."),
        (a2, "Р’РѕРїСЂРѕСЃС‹ Р·Р°РєР°Р·С‡РёРєСѓ", "РЎС„РѕСЂРјРёСЂСѓР№ СЃРїРёСЃРѕРє РІРѕРїСЂРѕСЃРѕРІ Р·Р°РєР°Р·С‡РёРєСѓ РёР»Рё РѕС‚РІРµС‚СЃС‚РІРµРЅРЅРѕРјСѓ РєРѕРЅС‚СѓСЂСѓ РїРѕ РѕР±СЉРµРєС‚Сѓ."),
        (a3, "Р”РѕРєСѓРјРµРЅС‚С‹", "РЎС„РѕСЂРјРёСЂСѓР№ СЃРїРёСЃРѕРє РґРѕРєСѓРјРµРЅС‚РѕРІ, РєРѕС‚РѕСЂС‹Рµ РЅСѓР¶РЅРѕ Р·Р°РїСЂРѕСЃРёС‚СЊ РґР»СЏ РѕС†РµРЅРєРё РѕР±СЉРµРєС‚Р° Рё РїРѕРґРіРѕС‚РѕРІРєРё РўРљРџ/РўР—."),
    ]
    for col, label, prompt in quick_actions:
        if col.button(label, key=f"ai_advice_{label}_{item.registry_type}_{item.tender_id}", use_container_width=True):
            messages.append({"role": "user", "content": label})
            with st.spinner("AI РіРѕС‚РѕРІРёС‚ СЂРµРєРѕРјРµРЅРґР°С†РёСЋвЂ¦"):
                answer = _ask_model(prompt)
            messages.append({"role": "assistant", "content": answer})
            st.rerun()

    for msg in messages[-12:]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("РЎРїСЂРѕСЃРёС‚СЊ РїРѕ РѕР±СЉРµРєС‚Сѓ РёР»Рё РґРѕР±Р°РІРёС‚СЊ Р·РЅР°РЅРёРµ РґР»СЏ СЃР»РµРґСѓСЋС‰РёС… РєР°СЂС‚РѕС‡РµРєвЂ¦", key=f"chat_input_{item.tender_id}")
    if not question:
        return
    messages.append({"role": "user", "content": question})
    answer = _ask_model(question, save_user_knowledge=True)
    messages.append({"role": "assistant", "content": answer})
    st.rerun()


def _render_category_label(
    detail: ObjectDetailData,
    objects_service: ObjectsService,
) -> None:
    """AI-РїСЂРµРґР»РѕР¶РµРЅРёРµ РєР°С‚РµРіРѕСЂРёРё Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєР°СЏ РєРѕСЂСЂРµРєС‚РёСЂРѕРІРєР°."""
    item = detail.item
    labels = load_category_labels()
    key = object_label_key(item)
    current = labels.get(key, {}).get("label")
    proposed = current or default_label_for_item(item)
    options = [
        SEGMENT_LABELS["social"],
        SEGMENT_LABELS["commercial"],
        SEGMENT_LABELS["residential"],
        SEGMENT_LABELS["other"],
        "РўСЂРµР±СѓРµС‚ РїСЂРѕРІРµСЂРєРё",
    ]
    st.markdown("### рџЏ·пёЏ РљР°С‚РµРіРѕСЂРёСЏ РѕР±СЉРµРєС‚Р°")
    chosen = st.selectbox("РљР°С‚РµРіРѕСЂРёСЏ (AI-РїСЂРµРґР»РѕР¶РµРЅРёРµ РјРѕР¶РЅРѕ РёР·РјРµРЅРёС‚СЊ)", options, index=options.index(proposed) if proposed in options else 4, key=f"category_{key}")
    if st.button("РЎРѕС…СЂР°РЅРёС‚СЊ РєР°С‚РµРіРѕСЂРёСЋ", key=f"save_category_{key}"):
        save_category_label(item, chosen, source="user")
        segment = next((k for k, v in SEGMENT_LABELS.items() if v == chosen), item.segment or "other")
        save_ai_classification(
            item,
            {
                "segment": segment,
                "label": chosen,
                "priority_score": item.ai_priority_score or 0,
                "delivery_chance": item.ai_delivery_chance,
                "volume_signal": item.ai_volume_signal,
                "sales_action": item.ai_sales_action,
                "reason": item.ai_priority_reason or "РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РїРѕРґС‚РІРµСЂРґРёР»/РёСЃРїСЂР°РІРёР» РєР°С‚РµРіРѕСЂРёСЋ РѕР±СЉРµРєС‚Р°.",
            },
            label=chosen,
            source="user",
            manager_corrected=True,
            manager_correction={"label": chosen, "previous_segment": item.segment},
            crm_db=objects_service.crm_db,
        )
        linked_item = objects_service.get_item_by_key(item.key)
        if linked_item and linked_item is not item:
            save_category_label(linked_item, chosen, source="user")
        st.success("РљР°С‚РµРіРѕСЂРёСЏ СЃРѕС…СЂР°РЅРµРЅР°, СЃРµРіРјРµРЅС‚ РєР°СЂС‚РѕС‡РєРё Рё СЃРїРёСЃРєР° РѕР±РЅРѕРІР»С‘РЅ.")
        st.rerun()


def _render_document_upload(detail: ObjectDetailData) -> None:
    st.markdown("### рџ“Ћ Р—Р°РіСЂСѓР·РёС‚СЊ РґРѕРєСѓРјРµРЅС‚ РґР»СЏ Р°РЅР°Р»РёР·Р°")
    uploaded = st.file_uploader("РўР—, PDF, DOCX РёР»Рё TXT", type=["pdf", "docx", "txt"], key=f"upload_{detail.item.tender_id}")
    if not uploaded or st.button("Р Р°Р·РѕР±СЂР°С‚СЊ РґРѕРєСѓРјРµРЅС‚ РјРѕРґРµР»СЊСЋ", key=f"parse_upload_{detail.item.tender_id}") is False:
        return
    raw = uploaded.getvalue()
    text = ""
    try:
        if uploaded.name.lower().endswith(".pdf"):
            from pypdf import PdfReader
            import io
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        elif uploaded.name.lower().endswith(".docx"):
            from docx import Document
            import io
            text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        else:
            text = raw.decode("utf-8", errors="ignore")
    except Exception as exc:
        st.error(f"РќРµ СѓРґР°Р»РѕСЃСЊ СЂР°Р·РѕР±СЂР°С‚СЊ С„Р°Р№Р»: {exc}"); return
    chunks = [text[i:i+12000] for i in range(0, len(text), 12000)] or ["(С‚РµРєСЃС‚ РЅРµ РёР·РІР»РµС‡С‘РЅ)"]
    answers = []
    with st.spinner(f"РћС‚РїСЂР°РІР»СЏСЋ {len(chunks)} С‡Р°СЃС‚РµР№ РІ РјРѕРґРµР»СЊвЂ¦"):
        for i, chunk in enumerate(chunks, 1):
            prompt = f"РР·РІР»РµРєРё РёР· С‡Р°СЃС‚Рё РўР— РјР°С‚РµСЂРёР°Р»С‹, С…Р°СЂР°РєС‚РµСЂРёСЃС‚РёРєРё, РѕР±СЉС‘РјС‹, С†РµРЅС‹, СЃСЂРѕРєРё, Р±СЂРµРЅРґС‹ Рё СЂРёСЃРєРё. Р’РµСЂРЅРё JSON. Р§Р°СЃС‚СЊ {i}/{len(chunks)}:\n{chunk}"
            try:
                payload = json.dumps({"model":"qwen2.5:7b","prompt":prompt,"stream":False}).encode()
                req = urllib.request.Request(_OLLAMA_URL, data=payload, headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req, timeout=90) as resp: answers.append(json.loads(resp.read().decode()).get("response", ""))
            except Exception as exc: answers.append(f"РћС€РёР±РєР° С‡Р°СЃС‚Рё {i}: {exc}")
    memory = Path(__file__).resolve().parents[2] / "data" / "ai_shadow" / "user_knowledge.jsonl"
    with memory.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"tender_id":detail.item.tender_id,"source":uploaded.name,"text":"\n".join(answers)}, ensure_ascii=False)+"\n")
    st.success(f"Р”РѕРєСѓРјРµРЅС‚ СЂР°Р·РѕР±СЂР°РЅ Р±Р°С‚С‡Р°РјРё: {len(chunks)}. Р”Р°РЅРЅС‹Рµ РґРѕР±Р°РІР»РµРЅС‹ РІ РїР°РјСЏС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ.")
    st.json({"source": uploaded.name, "chunks": len(chunks), "results": answers})


def render_object_detail(
    objects_service: ObjectsService,
    object_key: str,
    on_back: Callable[[], None],
) -> None:
    """Р”РµС‚Р°Р»СЊРЅР°СЏ СЃС‚СЂР°РЅРёС†Р° РѕР±СЉРµРєС‚Р°."""
    item = objects_service.get_item_by_key(object_key)
    if not item:
        st.warning("РћР±СЉРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ.")
        if st.button("в†ђ РќР°Р·Р°Рґ Рє СЃРїРёСЃРєСѓ", key="object_detail_not_found_back"):
            on_back()
        return

    with st.spinner("Р—Р°РіСЂСѓР·РєР° РёР· Р‘Р”вЂ¦"):
        detail = load_object_detail(
            item,
            tender_db=objects_service.tender_db,
            radar_db=objects_service.radar_db,
        )
    apply_object_category_labels([detail.item])
    apply_object_ai_scores([detail.item])
    apply_ai_classifications([detail.item], objects_service.crm_db)

    item = detail.item
    awarded = is_awarded_registry(item.registry_type)
    dismiss_key = f"dismiss_confirm_{object_key}"
    dismiss_err_key = f"dismiss_err_{object_key}"

    # --- РЁР°РїРєР° Р·Р°РїРёСЃРё ---
    hdr_left, hdr_right = st.columns([4, 1])
    with hdr_left:
        seg_ico = _SEGMENT_ICONS.get(item.segment or "", "рџЏ—пёЏ")
        st.markdown(
            f'<p class="sf-record-title">'
            f'<span class="sf-record-ico">{seg_ico}</span>'
            f'{html.escape(item.name or "вЂ”")}</p>',
            unsafe_allow_html=True,
        )
        badges = []
        if item.status:
            badges.append(("рџ“‘", item.status))
        elif item.registry_type:
            badges.append(("рџ“‘", registry_label(item.registry_type)))
        if item.quality_tier:
            badges.append(("рџ“Љ", TIER_LABELS.get(item.quality_tier, item.quality_tier)))
        if badges:
            st.markdown(
                " ".join(
                    f'<span class="sf-badge"><span class="sf-ico">{ico}</span>'
                    f'{html.escape(text)}</span>'
                    for ico, text in badges
                ),
                unsafe_allow_html=True,
            )
        if detail.tender_link:
            st.markdown(f"рџ”— [РћС‚РєСЂС‹С‚СЊ РЅР° РїР»РѕС‰Р°РґРєРµ]({detail.tender_link})")
        if item.address:
            st.caption(f"рџ“Ќ {item.address}")
        elif item.region:
            st.caption(f"рџ“Ќ {item.region}")

    with hdr_right:
        if st.button("в†ђ РќР°Р·Р°Рґ", key="object_detail_back", use_container_width=True):
            on_back()
            return
        lead_state = object_lead_status(objects_service.crm_db, object_key)
        if lead_state:
            st.caption(f"Р’ CRM: lead #{lead_state.get('id')} В· score {lead_state.get('score')}")
        if st.button("Р’Р·СЏС‚СЊ РІ СЂР°Р±РѕС‚Сѓ", key=f"object_take_work_{object_key}", use_container_width=True, type="primary"):
            try:
                result = upsert_object_lead(objects_service.crm_db, item, mark_taken=True)
                st.toast(
                    "РћР±СЉРµРєС‚ СЃРІСЏР·Р°РЅ СЃ CRM Рё РѕС‚РјРµС‡РµРЅ РєР°Рє РІР·СЏС‚С‹Р№ РІ СЂР°Р±РѕС‚Сѓ"
                    if result == "created"
                    else "CRM-СЃРѕСЃС‚РѕСЏРЅРёРµ РѕР±СЉРµРєС‚Р° РѕР±РЅРѕРІР»РµРЅРѕ",
                    icon="вњ…",
                )
                st.rerun()
            except Exception as exc:
                st.error(f"РќРµ СѓРґР°Р»РѕСЃСЊ РІР·СЏС‚СЊ РѕР±СЉРµРєС‚ РІ СЂР°Р±РѕС‚Сѓ: {exc}")
        if _can_dismiss(item):
            if st.button("рџ‘Ћ РќРµ РёРЅС‚РµСЂРµСЃРЅРѕ", key="object_dismiss_btn", use_container_width=True, type="secondary"):
                st.session_state[dismiss_key] = True
            if st.session_state.get(dismiss_key):
                st.warning("РЎРєСЂС‹С‚СЊ РѕР±СЉРµРєС‚ РёР· СЃРїРёСЃРєР°? РЎС‚Р°С‚СѓСЃ СЃРѕС…СЂР°РЅРёС‚СЃСЏ РІ Р‘Р”.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Р”Р°, СЃРєСЂС‹С‚СЊ", key="object_dismiss_yes", use_container_width=True):
                        ok, msg = mark_object_not_interesting(
                            tender_db=objects_service.tender_db,
                            crm_db=objects_service.crm_db,
                            tender_id=item.tender_id,
                            registry_type=item.registry_type,
                            object_key=object_key,
                            objects_service=objects_service,
                        )
                        st.session_state.pop(dismiss_key, None)
                        if ok:
                            st.session_state.pop(dismiss_err_key, None)
                            st.toast(msg, icon="вњ…")
                            on_back()
                        else:
                            st.session_state[dismiss_err_key] = msg
                            st.rerun()
                with c2:
                    if st.button("РћС‚РјРµРЅР°", key="object_dismiss_no", use_container_width=True):
                        st.session_state.pop(dismiss_key, None)
                        st.rerun()

    dismiss_err = st.session_state.pop(dismiss_err_key, None)
    if dismiss_err:
        st.error(dismiss_err)

    # --- РљР»СЋС‡РµРІС‹Рµ РїРѕРєР°Р·Р°С‚РµР»Рё ---
    seg_text = segment_label(item.segment) if item.segment else "вЂ”"
    metric_icons = dict(_METRIC_ICONS)
    if item.segment:
        metric_icons["РЎРµРіРјРµРЅС‚"] = _SEGMENT_ICONS.get(item.segment, "рџЏ·пёЏ")
    _compact_metrics([
        ("РЎРѕРІРїР°РґРµРЅРёР№", str(item.doc_matches or 0)),
        ("Р¤Р°Р№Р»РѕРІ", str(item.matched_files or len(detail.match_files))),
        ("РќРњР¦", _fmt_price(detail.initial_price)),
        ("РС‚РѕРі", _fmt_price(detail.final_price)),
        ("AI", str(item.ai_priority_score or "вЂ”")),
        ("РЎРµРіРјРµРЅС‚", seg_text),
    ], cols=6, icons=metric_icons)

    if item.ai_priority_reason:
        st.caption(
            f"AI СЂР°РЅР¶РёСЂРѕРІР°РЅРёРµ: {item.ai_priority_reason}"
            + (f" В· С€Р°РЅСЃ РїРѕСЃС‚Р°РІРєРё: {item.ai_delivery_chance}" if item.ai_delivery_chance else "")
            + (f" В· РѕР±СЉС‘Рј: {item.ai_volume_signal}" if item.ai_volume_signal else "")
            + (f" В· РґРµР№СЃС‚РІРёРµ: {item.ai_sales_action}" if item.ai_sales_action else "")
        )
    if item.ai_primary_class or item.ai_work_type or item.ai_project_stage:
        tags = ", ".join(item.ai_infrastructure_tags or [])
        st.caption(
            "AI РєР»Р°СЃСЃРёС„РёРєР°С†РёСЏ: "
            + " в†’ ".join(x for x in [item.ai_primary_class, item.ai_subcategory, item.ai_object_type] if x)
            + (f" В· СЂР°Р±РѕС‚С‹: {item.ai_work_type}" if item.ai_work_type else "")
            + (f" В· СЃС‚Р°РґРёСЏ: {item.ai_project_stage}" if item.ai_project_stage else "")
            + (f" В· С‚РµРіРё: {tags}" if tags else "")
        )

    st.markdown('<div class="object-detail-body">', unsafe_allow_html=True)

    tab_overview, tab_matches, tab_dates, tab_docs, tab_ai_chat, tab_extra = st.tabs(
        [
            "рџ“Љ РћР±Р·РѕСЂ",
            "рџЋЇ РЎРѕРІРїР°РґРµРЅРёСЏ",
            "рџ“… Р”Р°С‚С‹ Рё С†РµРЅС‹",
            "рџ“Ћ Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏ",
            "рџ¤– AI Рё С‡Р°С‚",
            "рџ”Ќ Р­РєСЃРїРµСЂС‚РёР·Р° / NashDom",
        ],
    )

    with tab_overview:
        with st.container(border=True):
            _section_title("Р—Р°РєСѓРїРєР°")
            _sf_fields([
                ("Р РµРµСЃС‚СЂ", item.status or registry_label(item.registry_type or "")),
                ("в„– Р·Р°РєСѓРїРєРё", detail.contract_number or item.contract_number),
                ("Р РµРіРёРѕРЅ РїРѕСЃС‚Р°РІРєРё", detail.delivery_region),
                ("РћРљРџР”", detail.okpd_code),
                ("РћРїРёСЃР°РЅРёРµ РћРљРџР”", detail.okpd_name),
                ("РџР»РѕС‰Р°РґРєР°", detail.platform_name),
                ("РЎСЃС‹Р»РєР° РїР»РѕС‰Р°РґРєРё", detail.platform_url),
            ])

        with st.container(border=True):
            _section_title("РЈС‡Р°СЃС‚РЅРёРєРё")
            organizer = item.customer_name or ""
            if organizer and item.customer_inn:
                organizer = f"{organizer} (РРќРќ {item.customer_inn})"
            winner = item.contractor_name or ""
            if winner and item.contractor_inn:
                winner = f"{winner} (РРќРќ {item.contractor_inn})"
            fields = [("Р‘Р°Р»Р°РЅСЃРѕРґРµСЂР¶Р°С‚РµР»СЊ", item.balance_holder)]
            if organizer and organizer != item.balance_holder:
                fields.append(("РћСЂРіР°РЅРёР·Р°С‚РѕСЂ С‚РѕСЂРіРѕРІ", organizer))
            if awarded and winner:
                fields.append(("РџРѕРґСЂСЏРґС‡РёРє / РїРѕР±РµРґРёС‚РµР»СЊ", winner))
            if item.expertise_planner:
                fields.append(("РџСЂРѕРµРєС‚РёСЂРѕРІС‰РёРє", item.expertise_planner))
            if item.expertise_technical_customer:
                fields.append(("РўРµС…РЅРёС‡РµСЃРєРёР№ Р·Р°РєР°Р·С‡РёРє", item.expertise_technical_customer))
            if item.expertise_developer:
                fields.append(("Р—Р°СЃС‚СЂРѕР№С‰РёРє / Р±Р°Р»Р°РЅСЃ РїРѕ СЌРєСЃРїРµСЂС‚РёР·Рµ", item.expertise_developer))
            _sf_fields(fields)

    with tab_matches:
        _render_matches_tab(detail, object_key)

    with tab_dates:
        with st.container(border=True):
            _section_title("РўРѕСЂРіРё")
            _compact_metrics([
                ("РќР°С‡Р°Р»Рѕ", fmt_date(item.start_date)),
                ("РћРєРѕРЅС‡Р°РЅРёРµ", fmt_date(item.end_date)),
            ], cols=2)
        with st.container(border=True):
            _section_title("РџРѕСЃС‚Р°РІРєР° / РёСЃРїРѕР»РЅРµРЅРёРµ")
            _compact_metrics([
                ("РќР°С‡Р°Р»Рѕ", fmt_date(item.delivery_start_date)),
                ("РћРєРѕРЅС‡Р°РЅРёРµ", fmt_date(item.delivery_end_date)),
            ], cols=2)
        with st.container(border=True):
            _section_title("Р¦РµРЅС‹")
            _compact_metrics([
                ("РќРњР¦", _fmt_price(detail.initial_price)),
                ("РС‚РѕРіРѕРІР°СЏ", _fmt_price(detail.final_price)),
            ], cols=2)

    with tab_docs:
        _render_docs_tab(detail, object_key)

    with tab_ai_chat:
        _render_procurement_chat(detail)
        _render_ai_shadow_v2(detail)
        _render_category_label(detail, objects_service)
        _render_document_upload(detail)

    with tab_extra:
        with st.container(border=True):
            _section_title("Р­РєСЃРїРµСЂС‚РёР·Р°")
            if detail.expertise_rows:
                for row in detail.expertise_rows:
                    st.markdown(
                        f"рџ§ѕ **{html.escape(row.get('expertise_number') or 'вЂ”')}** В· "
                        f"{html.escape(row.get('expertise_result_type') or '')}"
                    )
                    if row.get("expertise_date"):
                        st.caption(str(row["expertise_date"])[:10])
            elif item.expertise_number:
                st.markdown(f"**{html.escape(item.expertise_number)}**")
            else:
                st.caption("Р”Р°РЅРЅС‹Рµ СЌРєСЃРїРµСЂС‚РёР·С‹ РЅРµ РїСЂРёРІСЏР·Р°РЅС‹.")

        with st.container(border=True):
            _section_title("NashDom")
            if detail.nashdom_rows:
                for row in detail.nashdom_rows:
                    st.markdown(f"рџЏ—пёЏ **{html.escape(row.get('name') or 'вЂ”')}**")
                    if row.get("address_text"):
                        st.caption(row["address_text"])
                    st.caption(
                        f"{row.get('status_name') or 'вЂ”'} В· РџР” {row.get('pd_number') or 'вЂ”'}"
                    )
            elif item.domrf_object_id:
                st.caption(f"NashDom ID: {item.domrf_object_id}")
            else:
                st.caption("РћР±СЉРµРєС‚ NashDom РЅРµ РїСЂРёРІСЏР·Р°РЅ.")

    st.markdown("</div>", unsafe_allow_html=True)

