"""Batch AI classification and prioritisation for CRM objects."""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from src.services.ai_client import configured_model, generate_json
from src.services.ai_grounding import sanitize_materials_found
from src.services.object_ai_classification_store import save_ai_classification
from src.services.object_ai_fallbacks import (
    fallback_delivery_chance,
    fallback_priority,
    fallback_sales_action,
    guarded_segment,
    label_for_segment,
    sanitize_volume_signal,
)
from src.services.object_ai_prompts import MODEL_VERSION, prompt_for_item
from src.services.object_ai_scores import save_object_ai_score
from src.services.object_category_labels import (
    SEGMENT_LABELS,
    load_category_labels,
    object_label_keys,
    save_category_label,
    segment_from_label,
)
from src.services.object_lifecycle import DEFAULT_SALES_WINDOW_DAYS, delivery_days_left
from src.services.object_models import ObjectViewItem


def classify_item_with_ai(item: ObjectViewItem) -> dict:
    try:
        data = generate_json(prompt_for_item(item), timeout=40)
    except Exception:
        data = {}

    segment = str(data.get("segment") or "").strip().lower()
    label = str(data.get("label") or "").strip()
    if segment not in SEGMENT_LABELS:
        segment = segment_from_label(label) or "other"
    label = label_for_segment(segment, label)
    segment, label = guarded_segment(item, segment, label)

    allowed_materials = list(item.matched_products_ai or item.matched_product_preview or [])
    materials_found = sanitize_materials_found(
        data.get("materials_found"),
        allowed=allowed_materials,
        doc_matches=item.doc_matches,
    )
    volumes_found: list[str] = []
    if int(item.doc_matches or 0) > 0:
        for raw in data.get("volumes_found") or []:
            text = str(raw or "").strip()
            if text:
                volumes_found.append(text)
        volumes_found = list(dict.fromkeys(volumes_found))[:8]
        vol_preview = (item.docs_volume_preview or "").strip()
        if vol_preview and "не извлеч" not in vol_preview.lower() and not volumes_found:
            volumes_found = [vol_preview]

    try:
        priority = int(data.get("priority_score") or data.get("priority") or 0)
    except Exception:
        priority = 0
    priority = fallback_priority(item, priority)

    sales_action = fallback_sales_action(item, str(data.get("sales_action") or "").strip())
    delivery_days = delivery_days_left(item)
    material_share = data.get("material_share_estimate")
    reason = str(data.get("reason") or "").strip()
    if delivery_days is None:
        priority = min(priority, 75)
        reason = ((reason + " ") if reason else "") + (
            "Срок исполнения/поставки не найден; нельзя оценивать шанс по сроку торгов."
        )
    elif delivery_days < DEFAULT_SALES_WINDOW_DAYS:
        priority = 0
        reason = (
            f"До окончания исполнения/поставки меньше {DEFAULT_SALES_WINDOW_DAYS} дней "
            f"({item.delivery_end_date}); для прямой активной продажи материалов поздно, "
            "объект оставлен для мониторинга."
        )
    if material_share is None and str(data.get("volume_signal") or "").strip().lower() in {"", "неизвестно"}:
        priority = min(priority, 85)
        if "объем" not in reason.lower() and "объём" not in reason.lower():
            reason = ((reason + " ") if reason else "") + (
                "Объём и доля материалов в сумме закупки пока не подтверждены."
            )
    elif not reason:
        reason = "Приоритет рассчитан по типу объекта, сроку исполнения, документам и числу совпадений."

    return {
        "segment": segment,
        "label": label,
        "primary_class": data.get("primary_class"),
        "subcategory": data.get("subcategory"),
        "object_type": data.get("object_type"),
        "object_subtype": data.get("object_subtype"),
        "social_status": data.get("social_status"),
        "work_type": data.get("work_type"),
        "project_stage": data.get("project_stage"),
        "stage_signals": data.get("stage_signals") or [],
        "stage_primary": data.get("stage_primary"),
        "stage_reason": data.get("stage_reason"),
        "infrastructure_tags": data.get("infrastructure_tags") or [],
        "materials_found": materials_found,
        "volumes_found": volumes_found,
        "confidence": int(data.get("confidence") or 0),
        "classification_confidence": int(data.get("confidence") or 0),
        "priority_score": priority,
        "delivery_chance": fallback_delivery_chance(item, str(data.get("delivery_chance") or "")),
        "volume_signal": sanitize_volume_signal(
            item, str(data.get("volume_signal") or "неизвестно").strip()
        ),
        "material_share_estimate": (
            None if int(item.doc_matches or 0) <= 0 else data.get("material_share_estimate")
        ),
        "sales_action": sales_action,
        "manager_next_step": str(data.get("manager_next_step") or "").strip() or None,
        "talk_track": str(data.get("talk_track") or "").strip() or None,
        "reason": reason,
        "classification_reason": reason,
        "model_name": configured_model(),
        "model_version": MODEL_VERSION,
    }


def classify_objects_with_ai(
    items: Iterable[ObjectViewItem],
    *,
    limit: Optional[int] = None,
    overwrite_user: bool = False,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> dict:
    labels = load_category_labels()
    user_keys = {key for key, row in labels.items() if row.get("source") == "user"}
    selected = list(items)
    if limit:
        selected = selected[:limit]
    total = len(selected)
    ok = skipped = failed = changed = 0

    for idx, item in enumerate(selected, 1):
        keys = object_label_keys(item)
        if any(key in user_keys for key in keys) and not overwrite_user:
            skipped += 1
            if on_progress:
                on_progress(f"Пропущена ручная метка {idx}/{total}: {item.name[:80]}", idx / max(1, total))
            continue
        if on_progress:
            on_progress(f"AI классифицирует {idx}/{total}: {item.name[:80]}", (idx - 1) / max(1, total))
        before = item.segment
        try:
            result = classify_item_with_ai(item)
            save_category_label(item, result["label"], source="ai_batch")
            save_object_ai_score(item, result, source="ai_batch")
            save_ai_classification(item, result, source="ai_batch")
            if result["segment"] != before:
                changed += 1
            ok += 1
        except Exception:
            failed += 1

    if on_progress:
        on_progress("Готово", 1.0)
    return {
        "total": total,
        "ok": ok,
        "skipped_user": skipped,
        "failed": failed,
        "changed": changed,
    }
