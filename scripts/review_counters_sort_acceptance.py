"""Read-only real-route AppTest for review counters and TORGI deadline sorting."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
load_dotenv(root / ".env", override=True)


def _deadlines(at: AppTest) -> list[str]:
    result = []
    for item in at.markdown:
        value = str(item.value)
        if "📅" not in value:
            continue
        match = re.search(r"(\d{2}\.\d{2}\.\d{4})", value)
        if match:
            result.append(match.group(1))
    return result


def _monotonic(values: list[str], *, reverse: bool) -> bool:
    parsed = [datetime.strptime(value, "%d.%m.%Y").date() for value in values]
    return len(parsed) == 25 and parsed == sorted(parsed, reverse=reverse)


def _counter(label: str, labels: list[str]) -> int:
    value = next(item for item in labels if item.startswith(label + " ·"))
    return int(value.rsplit("·", 1)[1].strip())


def main() -> int:
    at = AppTest.from_file(str(root / "app.py"), default_timeout=240)
    at.run(timeout=240)
    next(item for item in at.radio if "Идут торги" in list(item.options)).set_value("Идут торги").run(timeout=240)

    sort = next(item for item in at.radio if item.label == "Сортировка по сроку")
    default_sort_value = sort.value
    far = _deadlines(at)
    groups = list(at.get("button_group"))
    expert = next(group for group in groups if any(str(value).startswith("Не проверено ·") for value in group.options))
    counter_labels = list(expert.options)

    sort.set_value("NEAREST_DEADLINE_FIRST").run(timeout=240)
    near = _deadlines(at)
    expert = next(group for group in at.get("button_group") if any(
        str(value).startswith("Не проверено ·") for value in group.options
    ))
    reviewed_label = next(value for value in expert.options if str(value).startswith("Проверено ·"))
    expert.set_value(reviewed_label).run(timeout=240)
    reviewed_markdown = "\n".join(str(item.value) for item in at.markdown)

    result = {
        "route": "app.py->objects_v2->Analytics Contour->Идут торги",
        "default_sort_value": default_sort_value,
        "counter_labels": counter_labels,
        "default_first_page_deadlines": far,
        "nearest_first_page_deadlines": near,
        "far_monotonic": _monotonic(far, reverse=True),
        "near_monotonic": _monotonic(near, reverse=False),
        "reviewed_filter_control_visible": "Поставка медицинских изделий (перчатки нитриловые)" in reviewed_markdown,
        "reviewed_chip_visible": "✓ Проверено" in reviewed_markdown,
        "not_interesting_chip_visible": "⛔ Неинтересная" in reviewed_markdown,
        "exceptions": [str(item.value) for item in at.exception],
    }
    result["pass"] = all((
        result["far_monotonic"], result["near_monotonic"],
        result["reviewed_filter_control_visible"], result["reviewed_chip_visible"],
        result["not_interesting_chip_visible"], not result["exceptions"],
        _counter("Все", counter_labels) == _counter("Не проверено", counter_labels) + _counter("Проверено", counter_labels),
        _counter("Неинтересные", counter_labels) <= _counter("Проверено", counter_labels),
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
