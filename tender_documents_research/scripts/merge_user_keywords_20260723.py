"""Добавить канонические пользовательские ключи без потери текущего словаря."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KEYWORDS_PATH = ROOT / "user_keywords.json"

COMPOSITE_DRAINAGE_PHRASES = [
    "композитный водоотводный лоток",
    "композитные водоотводные лотки",
    "водоотводный композитный лоток",
    "водоотводные композитные лотки",
    "лоток водоотводный композитный",
    "лотки водоотводные композитные",
    "лоток из композитного материала",
    "лотки из композитного материала",
    "водоотводный лоток из композита",
    "водоотводные лотки из композита",
    "композитный лоток для водоотвода",
    "композитные лотки для водоотвода",
    "композитный дренажный лоток",
    "композитные дренажные лотки",
    "дренажный лоток из композита",
    "дренажные лотки из композита",
    "композитный ливневый лоток",
    "композитные ливневые лотки",
    "ливневый лоток из композита",
    "ливневые лотки из композита",
    "композитный водоотводный канал",
    "композитные водоотводные каналы",
    "водоотводный канал из композита",
    "канал линейного водоотвода из композита",
    "композитная система линейного водоотвода",
    "система линейного водоотвода из композита",
    "стеклопластиковый водоотводный лоток",
    "стеклопластиковые водоотводные лотки",
    "водоотводный лоток из стеклопластика",
    "водоотводные лотки из стеклопластика",
    "полимеркомпозитный водоотводный лоток",
    "полимеркомпозитные водоотводные лотки",
    "водоотводный лоток из полимерного композита",
    "лоток из полимерного композитного материала",
    "композитно-полимерный водоотводный лоток",
]

SELF_LEVELING_FLOOR_PHRASES = [
    "наливные полы",
    "наливной пол",
    "наливное покрытие",
    "наливные покрытия",
    "промышленные полы",
    "промышленный пол",
    "промышленное покрытие",
    "промышленные покрытия",
    "эпоксидный пол",
    "эпоксидные полы",
    "эпоксидное покрытие пола",
    "полиуретановый пол",
    "полиуретановые полы",
    "полиуретановое покрытие пола",
    "полимерный пол",
    "полимерные полы",
    "полимерное покрытие пола",
    "беспылевое покрытие пола",
    "износостойкое покрытие пола",
]


def load_keywords() -> tuple[object, list[str]]:
    if not KEYWORDS_PATH.exists():
        return {"keywords": []}, []
    data = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        keywords = data.setdefault("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
            data["keywords"] = keywords
        return data, keywords
    if isinstance(data, list):
        return {"keywords": data}, data
    return {"keywords": []}, []


def main() -> int:
    data, keywords = load_keywords()
    before = len(keywords)
    seen = {str(item).strip().lower() for item in keywords if str(item).strip()}
    for phrase in COMPOSITE_DRAINAGE_PHRASES + SELF_LEVELING_FLOOR_PHRASES:
        key = phrase.strip().lower()
        if key and key not in seen:
            keywords.append(phrase)
            seen.add(key)
    KEYWORDS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"user_keywords: before={before} after={len(keywords)} added={len(keywords)-before}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
