"""User/AI object category labels applied over CRM index segments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Optional

from src.services.object_models import ObjectViewItem


_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ai_shadow"
_LABELS_PATH = _DATA_DIR / "category_labels.jsonl"

SEGMENT_LABELS = {
    "residential": "Жилой объект",
    "social": "Государственный / социальный",
    "commercial": "Коммерческий",
    "industrial": "Промышленный",
    "road_infrastructure": "Дороги / благоустройство",
    "other": "Прочее",
}


def object_label_key(item: ObjectViewItem) -> str:
    return f"{item.registry_type}:{item.tender_id}"


def object_label_keys(item: ObjectViewItem) -> list[str]:
    keys = [object_label_key(item)]
    if item.key:
        keys.append(f"object:{item.key}")
    if item.contract_number:
        keys.append(f"contract:{item.contract_number}")
    if item.matched_tender_number:
        keys.append(f"contract:{item.matched_tender_number}")
    if item.expertise_number:
        keys.append(f"expertise:{item.expertise_number}")
    return list(dict.fromkeys(keys))


def segment_from_label(label: str | None) -> Optional[str]:
    value = (label or "").strip().lower()
    if not value:
        return None
    if "социал" in value or "государ" in value or "44" in value:
        return "social"
    if "коммер" in value or "223" in value:
        return "commercial"
    if "пром" in value or "производ" in value or "завод" in value:
        return "industrial"
    if "дорог" in value or "улиц" in value or "мост" in value or "благоустр" in value or "тоннел" in value:
        return "road_infrastructure"
    if "жил" in value:
        return "residential"
    if "проч" in value or "нежил" in value:
        return "other"
    return None


def default_label_for_item(item: ObjectViewItem) -> str:
    """Prefer existing segment / name heuristics; avoid mapping all 44-FZ to social."""
    if item.segment and item.segment in SEGMENT_LABELS:
        return SEGMENT_LABELS[item.segment]
    text = " ".join(
        str(x or "")
        for x in (item.name, item.address, item.balance_holder, item.customer_name)
    ).lower()
    if any(t in text for t in ("школ", "больниц", "детсад", "гбуз", "мбоу", "сош", "культурного наследия")):
        return SEGMENT_LABELS["social"]
    if any(t in text for t in ("мкд", "многоквартир", "жилой дом", "жк ")):
        return SEGMENT_LABELS["residential"]
    if any(t in text for t in ("дорог", "улиц", "мост", "тоннел", "благоустройств")):
        return SEGMENT_LABELS["road_infrastructure"]
    if any(t in text for t in ("завод", "производств", "склад", "промышлен")):
        return SEGMENT_LABELS["industrial"]
    if "223" in str(item.registry_type):
        return SEGMENT_LABELS["commercial"]
    return "Требует проверки"


def load_category_labels() -> Dict[str, dict]:
    labels: Dict[str, dict] = {}
    if not _LABELS_PATH.exists():
        return labels
    for line in _LABELS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        key = str(row.get("key") or "")
        if key:
            labels[key] = row
        for alias in row.get("keys") or []:
            alias_key = str(alias or "")
            if alias_key:
                labels[alias_key] = row
        object_key = str(row.get("object_key") or "")
        if object_key:
            labels[f"object:{object_key}"] = row
        contract_number = str(row.get("contract_number") or "")
        if contract_number:
            labels[f"contract:{contract_number}"] = row
        expertise_number = str(row.get("expertise_number") or "")
        if expertise_number:
            labels[f"expertise:{expertise_number}"] = row
    return labels


def apply_category_label(item: ObjectViewItem, label: str | None) -> bool:
    segment = segment_from_label(label)
    if not segment:
        return False
    item.segment = segment
    return True


def apply_object_category_labels(items: Iterable[ObjectViewItem]) -> None:
    labels = load_category_labels()
    if not labels:
        return
    for item in items:
        row = next((labels.get(key) for key in object_label_keys(item) if labels.get(key)), None)
        if row:
            apply_category_label(item, row.get("label"))


def save_category_label(item: ObjectViewItem, label: str, *, source: str = "user") -> dict:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    previous_segment = item.segment
    segment = segment_from_label(label) or previous_segment or "other"
    row = {
        "key": object_label_key(item),
        "keys": object_label_keys(item),
        "tender_id": item.tender_id,
        "registry_type": item.registry_type,
        "object_key": item.key,
        "contract_number": item.contract_number,
        "expertise_number": item.expertise_number,
        "label": label,
        "segment": segment,
        "previous_segment": previous_segment,
        "source": source,
    }
    with _LABELS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    item.segment = segment
    return row
