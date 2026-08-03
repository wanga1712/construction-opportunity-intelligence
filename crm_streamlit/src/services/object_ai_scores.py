"""AI priority scores for CRM object ordering."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable

from src.services.object_category_labels import object_label_key, object_label_keys
from src.services.object_models import ObjectViewItem


_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ai_shadow"
_SCORES_PATH = _DATA_DIR / "object_priority_scores.jsonl"


def load_object_ai_scores() -> Dict[str, dict]:
    scores: Dict[str, dict] = {}
    if not _SCORES_PATH.exists():
        return scores
    for line in _SCORES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        key = str(row.get("key") or "")
        if key:
            scores[key] = row
        for alias in row.get("keys") or []:
            alias_key = str(alias or "")
            if alias_key:
                scores[alias_key] = row
        object_key = str(row.get("object_key") or "")
        if object_key:
            scores[f"object:{object_key}"] = row
        contract_number = str(row.get("contract_number") or "")
        if contract_number:
            scores[f"contract:{contract_number}"] = row
        expertise_number = str(row.get("expertise_number") or "")
        if expertise_number:
            scores[f"expertise:{expertise_number}"] = row
    return scores


def apply_object_ai_scores(items: Iterable[ObjectViewItem]) -> None:
    scores = load_object_ai_scores()
    if not scores:
        return
    for item in items:
        row = next((scores.get(key) for key in object_label_keys(item) if scores.get(key)), None)
        if not row:
            continue
        try:
            item.ai_priority_score = int(row.get("priority_score") or 0)
        except Exception:
            item.ai_priority_score = 0
        item.ai_priority_reason = row.get("reason")
        item.ai_delivery_chance = row.get("delivery_chance")
        item.ai_volume_signal = row.get("volume_signal")


def save_object_ai_score(item: ObjectViewItem, result: dict, *, source: str = "ai_batch") -> dict:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        score = int(result.get("priority_score") or result.get("priority") or 0)
    except Exception:
        score = 0
    score = max(0, min(100, score))
    row = {
        "key": object_label_key(item),
        "keys": object_label_keys(item),
        "tender_id": item.tender_id,
        "registry_type": item.registry_type,
        "object_key": item.key,
        "contract_number": item.contract_number,
        "expertise_number": item.expertise_number,
        "priority_score": score,
        "delivery_chance": result.get("delivery_chance"),
        "volume_signal": result.get("volume_signal"),
        "reason": result.get("reason"),
        "source": source,
    }
    with _SCORES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    item.ai_priority_score = score
    item.ai_delivery_chance = row["delivery_chance"]
    item.ai_volume_signal = row["volume_signal"]
    item.ai_priority_reason = row["reason"]
    return row
