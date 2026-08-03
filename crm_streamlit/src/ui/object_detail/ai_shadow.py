"""AI analysis panel for object details."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.services.ai_client import extract_json, generate
from src.services.ai_grounding import (
    matched_product_names,
    materials_block_for_prompt,
    sanitize_materials_found,
)
from src.services.object_ai_classification_store import save_ai_classification
from src.services.object_ai_scores import save_object_ai_score
from src.services.object_category_labels import SEGMENT_LABELS, save_category_label
from src.services.object_detail_loader import ObjectDetailData

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SEGMENT_ENUM = "|".join(SEGMENT_LABELS.keys())
_LABEL_ENUM = "|".join(SEGMENT_LABELS.values())


def _render_ai_shadow(item) -> None:
    path = _PROJECT_ROOT / "data" / "ai_shadow" / "model_suggestions_filtered.jsonl"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("procurement_id")) == str(item.tender_id):
            st.markdown("### 🤖 AI-анализ (теневой режим)")
            st.caption("Результат модели не изменяет фильтры и требует проверки пользователя.")
            st.code(row.get("model_response", ""), language="json")
            break


def _render_ai_shadow_v2(detail: ObjectDetailData) -> None:
    item = detail.item
    path = _PROJECT_ROOT / "data" / "ai_shadow" / "model_suggestions_filtered.jsonl"
    if not path.exists():
        path = _PROJECT_ROOT / "data" / "ai_shadow" / "model_suggestions.jsonl"
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

    allowed_products = matched_product_names(detail.match_files)

    def _build_prompt() -> str:
        materials_ctx = materials_block_for_prompt(
            doc_matches=item.doc_matches,
            matched_files=item.matched_files,
            match_files=detail.match_files,
        )
        return (
            "Ты AI-аналитик CRM для объектно-проектных продаж строительных материалов. "
            "Нужно не писать общие слова, а дать прикладную оценку закупки для менеджера.\n"
            "Классифицируй объект и оцени приоритет обработки.\n\n"
            "Верни только JSON без markdown и без пояснений вокруг JSON. Схема:\n"
            f'{{"decision":"keep|review|exclude","segment":"{_SEGMENT_ENUM}",'
            f'"label":"{_LABEL_ENUM}","priority_score":0-100,'
            '"delivery_chance":"высокий|средний|низкий","volume_signal":"крупный|средний|малый|неизвестно",'
            '"reason":"коротко: почему это интересно или рискованно",'
            '"object_type":"школа/больница/МКД/офис/дорога/прочее",'
            '"materials_found":[],"volumes_found":[],'
            '"dates":{"bid_end":"","delivery_start":"","delivery_end":""},'
            '"risks":["..."],"missing_data":["..."]}\n\n'
            "Правила:\n"
            "- МБОУ/СОШ/школа/детсад/ГБУЗ/больница/муниципальное или бюджетное учреждение/культурное наследие => social.\n"
            "- МКД/жилой дом/многоквартирный дом/ЖК => residential.\n"
            "- Завод/производство/склад/промзона => industrial.\n"
            "- Дорога/улица/мост/тоннель/благоустройство => road_infrastructure.\n"
            "- 223-ФЗ или коммерческий заказчик без более точной категории => commercial.\n"
            "- Непонятное => other (не подменяй на residential).\n"
            "- ЗАПРЕТ: не выдумывай материалы и объёмы. materials_found только из подтверждённого списка ниже.\n"
            "- Если совпадений 0 — materials_found=[] и volumes_found=[], добавь это в missing_data.\n"
            "- Приоритет выше только если есть реальные совпадения в документах и срок исполнения позволяет зайти.\n"
            "- Если срок близкий или прошёл, chance снижай и укажи риск.\n\n"
            "Данные карточки:\n"
            f"Название: {item.name}\nОКПД: {detail.okpd_code or ''}\nОписание ОКПД: {detail.okpd_name or ''}\n"
            f"Регион/адрес: {detail.delivery_region or item.address or ''}\nНМЦ: {detail.initial_price or ''}\n"
            f"Номер закупки/контракта: {detail.contract_number or item.contract_number or ''}\n"
            f"Статус: {item.status or ''}; реестр: {item.registry_type or ''}\n"
            f"Заказчик/организатор: {item.customer_name or ''} {item.customer_inn or ''}\n"
            f"Балансодержатель: {item.balance_holder or ''}\n"
            f"Подрядчик: {item.contractor_name or ''} {item.contractor_inn or ''}\n"
            f"Срок торгов: {item.start_date or ''} — {item.end_date or ''}\n"
            f"Срок поставки/исполнения: {item.delivery_start_date or ''} — {item.delivery_end_date or ''}\n"
            f"{materials_ctx}\n"
        )

    def _call_and_apply_ai() -> dict:
        response = generate(_build_prompt(), timeout=75)
        try:
            parsed = extract_json(response)
        except ValueError:
            parsed = {}
        if not parsed:
            return {"model_response": response}
        parsed["materials_found"] = sanitize_materials_found(
            parsed.get("materials_found"),
            allowed=allowed_products,
            doc_matches=item.doc_matches,
        )
        if int(item.doc_matches or 0) <= 0:
            parsed["volumes_found"] = []
            missing = list(parsed.get("missing_data") or [])
            note = "материалы из документов не найдены (документы не обработаны или совпадений нет)"
            if note not in missing:
                missing.append(note)
            parsed["missing_data"] = missing
        label = str(parsed.get("label") or "").strip()
        segment = str(parsed.get("segment") or "").strip()
        if not label and segment in SEGMENT_LABELS:
            label = SEGMENT_LABELS[segment]
        if label:
            save_category_label(item, label, source="ai_card")
        save_object_ai_score(item, parsed, source="ai_card")
        save_ai_classification(item, parsed, label=label, source="ai_card")
        ai_path = _PROJECT_ROOT / "data" / "ai_shadow" / "card_ai_analysis.jsonl"
        ai_path.parent.mkdir(parents=True, exist_ok=True)
        with ai_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "tender_id": item.tender_id,
                        "registry_type": item.registry_type,
                        "contract_number": detail.contract_number or item.contract_number,
                        "response": parsed,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return {"model_response": json.dumps(parsed, ensure_ascii=False, indent=2), "parsed": parsed}

    st.markdown("### 🤖 AI-анализ закупки")
    st.caption(
        "AI-разметка может обновить категорию и приоритет. "
        "Материалы берутся только из реальных совпадений в документах."
    )
    if int(item.doc_matches or 0) <= 0:
        st.info("По этой закупке пока нет совпадений в документах — AI не должен называть материалы.")
    if st.button("Обновить AI-анализ и применить к карточке", key=f"refresh_ai_{item.registry_type}_{item.tender_id}"):
        with st.spinner("Модель анализирует карточку и сохраняет разметку…"):
            try:
                found = _call_and_apply_ai()
                st.success("AI-анализ сохранён: категория и приоритет применены.")
                st.rerun()
            except Exception as exc:
                found = {"error": str(exc)}
    if found is None:
        try:
            found = {"model_response": generate(_build_prompt(), timeout=45)}
        except Exception as exc:
            found = {"error": str(exc)}
    if found and found.get("error"):
        st.warning(f"AI временно недоступен: {found['error']}")
    elif found:
        response_text = found.get("model_response", found.get("response", ""))
        try:
            parsed = found.get("parsed") or extract_json(response_text)
        except ValueError:
            parsed = {}
        if parsed:
            parsed["materials_found"] = sanitize_materials_found(
                parsed.get("materials_found"),
                allowed=allowed_products,
                doc_matches=item.doc_matches,
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("AI приоритет", parsed.get("priority_score", parsed.get("priority", "—")))
            c2.metric("Шанс поставки", parsed.get("delivery_chance", "—"))
            c3.metric("Объём", parsed.get("volume_signal", "—"))
            c4.metric("Решение", parsed.get("decision", "—"))
            st.caption(parsed.get("reason", ""))
            mats = parsed.get("materials_found") or []
            if mats:
                st.success("Материалы из документов: " + "; ".join(map(str, mats)))
            elif int(item.doc_matches or 0) <= 0:
                st.caption("Материалы из документов: не найдены.")
            if parsed.get("missing_data"):
                st.warning("Не хватает данных: " + "; ".join(map(str, parsed.get("missing_data") or [])))
            with st.expander("JSON AI-анализа"):
                st.json(parsed)
        else:
            st.code(response_text, language="json")
    else:
        st.info("AI-результат для этой закупки ещё не сформирован.")
