"""Object AI chat, category correction, and document upload."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.services.ai_client import generate
from src.services.ai_grounding import materials_block_for_prompt
from src.services.object_ai_classification_store import save_ai_classification
from src.services.object_category_labels import (
    SEGMENT_LABELS, default_label_for_item, load_category_labels,
    object_label_key, save_category_label,
)
from src.services.object_detail_loader import ObjectDetailData
from src.services.objects_service import ObjectsService
from src.services.sales_spin_playbook import spin_block_for_prompt, spin_chat_instructions

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _render_procurement_chat(detail: ObjectDetailData) -> None:
    """Object-level AI advisor with chat and recommended next actions."""
    item = detail.item
    root = _PROJECT_ROOT / "data" / "ai_shadow"
    root.mkdir(parents=True, exist_ok=True)
    memory_path, advice_path = root / "user_knowledge.jsonl", root / "object_ai_advice.jsonl"
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
        return "\n".join(f"- {x.get('text', '')}" for x in knowledge[-50:]) or "(пока нет общей памяти)"

    def _object_context() -> str:
        materials_ctx = materials_block_for_prompt(
            doc_matches=item.doc_matches,
            matched_files=item.matched_files,
            match_files=detail.match_files,
        )
        return (
            f"Название: {item.name}\nОКПД: {detail.okpd_code or ''} — {detail.okpd_name or ''}\n"
            f"Регион/адрес: {detail.delivery_region or item.address or ''}\n"
            f"НМЦ: {detail.initial_price or ''}; итоговая цена: {detail.final_price or ''}\n"
            f"Номер закупки/контракта: {detail.contract_number or item.contract_number or ''}\n"
            f"Статус: {item.status or ''}; реестр: {item.registry_type or ''}\n"
            f"Заказчик/организатор: {item.customer_name or ''} {item.customer_inn or ''}\n"
            f"Балансодержатель: {item.balance_holder or ''}\n"
            f"Подрядчик/победитель: {item.contractor_name or ''} {item.contractor_inn or ''}\n"
            f"Срок торгов: {item.start_date or ''} — {item.end_date or ''}\n"
            f"Срок поставки/исполнения: {item.delivery_start_date or ''} — {item.delivery_end_date or ''}\n"
            f"{materials_ctx}\n"
            f"AI priority: {item.ai_priority_score or ''}; шанс: {item.ai_delivery_chance or ''}; "
            f"объём: {item.ai_volume_signal or ''}\n"
            f"AI reason: {item.ai_priority_reason or ''}\n"
        )

    def _ask_model(question: str, *, save_user_knowledge: bool = False) -> str:
        prompt = (
            "Ты AI-советник внутри карточки CRM по объектно-проектным продажам строительных материалов. "
            "Отвечай по-русски, конкретно и прикладно.\n\n"
            f"{spin_block_for_prompt()}\n\n"
            f"{spin_chat_instructions()}\n\n"
            "Текущая карточка объекта:\n"
            f"{_object_context()}"
            "Общая память пользователя (не путай с материалами этой закупки):\n"
            f"{_load_memory()}\n\n"
            f"Что нужно сделать:\n{question}\n\nФормат ответа:\n"
            "1) Situation / Problem / Implication / Need-payoff (кратко).\n"
            "2) Рекомендованный следующий шаг (один главный).\n"
            "3) Talk-track: что сказать.\n"
            "4) Какие данные/документы нужны.\n"
            "5) Риски и чего НЕ делать.\n"
            "6) Приоритет A/B/C и почему.\n"
            "ЗАПРЕТ: не называй материалы, которых нет в «Подтверждённые материалы из документов». "
            "Если список пуст — прямо скажи, что материалы в документах не найдены / документы не обработаны."
        )
        try:
            answer = generate(prompt, timeout=120) or "Нет ответа"
        except Exception as exc:
            answer = f"Модель временно недоступна: {exc}"
        with advice_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tender_id": item.tender_id, "registry_type": item.registry_type, "question": question, "answer": answer}, ensure_ascii=False) + "\n")
        if save_user_knowledge:
            with memory_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"tender_id": item.tender_id, "text": question}, ensure_ascii=False) + "\n")
        return answer

    st.markdown("### AI-советник по объекту (SPIN)")
    st.caption("SPIN-консультация по карточке; кейсы и память сохраняются для следующих объектов.")
    a1, a2, a3, a4 = st.columns(4)
    quick_actions = [
        (a1, "Следующий шаг", "По SPIN дай один главный следующий шаг менеджеру: кому писать/звонить, что сказать, что запросить."),
        (a2, "SPIN разбор", "Разложи объект по SPIN: Situation, Problem, Implication, Need-payoff и talk-track."),
        (a3, "Вопросы", "Сформируй SPIN-вопросы заказчику/подрядчику (не допрос, а вскрытие боли и выгоды)."),
        (a4, "Документы", "Какие документы запросить, чтобы усилить продажу и подтвердить объём/узел."),
    ]
    for col, label, prompt in quick_actions:
        if col.button(label, key=f"ai_advice_{label}_{item.registry_type}_{item.tender_id}", use_container_width=True):
            messages.append({"role": "user", "content": label})
            with st.spinner("AI готовит рекомендацию…"):
                answer = _ask_model(prompt)
            messages.append({"role": "assistant", "content": answer})
            st.rerun()
    for msg in messages[-12:]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    question = st.chat_input("Спросить по объекту или добавить знание для следующих карточек…", key=f"chat_input_{item.tender_id}")
    if not question:
        return
    messages.append({"role": "user", "content": question})
    messages.append({"role": "assistant", "content": _ask_model(question, save_user_knowledge=True)})
    st.rerun()


def _render_category_label(detail: ObjectDetailData, objects_service: ObjectsService) -> None:
    """AI-предложение категории и пользовательская корректировка."""
    item = detail.item
    labels, key = load_category_labels(), object_label_key(item)
    current = labels.get(key, {}).get("label")
    proposed = current or default_label_for_item(item)
    options = [
        SEGMENT_LABELS["social"],
        SEGMENT_LABELS["residential"],
        SEGMENT_LABELS["commercial"],
        SEGMENT_LABELS["industrial"],
        SEGMENT_LABELS["road_infrastructure"],
        SEGMENT_LABELS["other"],
        "Требует проверки",
    ]
    st.markdown("### 🏷️ Категория объекта")
    chosen = st.selectbox(
        "Категория (AI-предложение можно изменить)",
        options,
        index=options.index(proposed) if proposed in options else len(options) - 1,
        key=f"category_{key}",
    )
    if st.button("Сохранить категорию", key=f"save_category_{key}"):
        save_category_label(item, chosen, source="user")
        save_ai_classification(item, {
            "segment": SEGMENT_LABELS and next((k for k, v in SEGMENT_LABELS.items() if v == chosen), item.segment),
            "label": chosen, "priority_score": item.ai_priority_score or 0,
            "delivery_chance": item.ai_delivery_chance, "volume_signal": item.ai_volume_signal,
            "reason": item.ai_priority_reason or "Пользователь подтвердил/исправил категорию объекта.",
        }, label=chosen, source="user", manager_corrected=True,
            manager_correction={"label": chosen, "previous_segment": item.segment}, crm_db=objects_service.crm_db)
        linked_item = objects_service.get_item_by_key(item.key)
        if linked_item and linked_item is not item:
            save_category_label(linked_item, chosen, source="user")
        st.success("Категория сохранена, сегмент карточки и списка обновлён.")
        st.rerun()


def _render_document_upload(detail: ObjectDetailData) -> None:
    st.markdown("### 📎 Загрузить документ для анализа")
    uploaded = st.file_uploader("ТЗ, PDF, DOCX или TXT", type=["pdf", "docx", "txt"], key=f"upload_{detail.item.tender_id}")
    if not uploaded or st.button("Разобрать документ моделью", key=f"parse_upload_{detail.item.tender_id}") is False:
        return
    raw, text = uploaded.getvalue(), ""
    try:
        if uploaded.name.lower().endswith(".pdf"):
            import io
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        elif uploaded.name.lower().endswith(".docx"):
            import io
            from docx import Document
            text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        else:
            text = raw.decode("utf-8", errors="ignore")
    except Exception as exc:
        st.error(f"Не удалось разобрать файл: {exc}")
        return
    chunks, answers = [text[i:i + 12000] for i in range(0, len(text), 12000)] or ["(текст не извлечён)"], []
    with st.spinner(f"Отправляю {len(chunks)} частей в модель…"):
        for i, chunk in enumerate(chunks, 1):
            prompt = f"Извлеки из части ТЗ материалы, характеристики, объёмы, цены, сроки, бренды и риски. Верни JSON. Часть {i}/{len(chunks)}:\n{chunk}"
            try:
                answers.append(generate(prompt, timeout=90))
            except Exception as exc:
                answers.append(f"Ошибка части {i}: {exc}")
    memory = _PROJECT_ROOT / "data" / "ai_shadow" / "user_knowledge.jsonl"
    with memory.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"tender_id": detail.item.tender_id, "source": uploaded.name, "text": "\n".join(answers)}, ensure_ascii=False) + "\n")
    st.success(f"Документ разобран батчами: {len(chunks)}. Данные добавлены в память пользователя.")
    st.json({"source": uploaded.name, "chunks": len(chunks), "results": answers})
