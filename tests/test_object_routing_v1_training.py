"""Focused tests for TRAINING STAGE 1 (object routing) changed modules.

Scope is deliberately narrow: only the modules touched by
WIP=ANALYTICS-V2-TRAINING-STAGE-1-OBJECT-ROUTING.  No GPU, no database,
no network access; these run in the production venv.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE1 = os.path.join(ROOT, "training", "object_routing_v1")
for path in (STAGE1, ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from routing_labels import (  # noqa: E402
    LABELS,
    PROMPT_VERSION,
    build_example,
    build_user_message,
    derive_labels,
    parse_labels,
    target_json,
)

CANONICAL_CASES = [
    # (title, okpd, okpd_name, customer, expected)
    ("Строительство школы", "42.11.20", "Работы строительные", "МБОУ СОШ №1",
     {"SOCIAL": True, "PROJECT": True, "DIRECT_SUPPLY": False}),
    ("Поставка компьютеров в школу", "26.20.15", "Компьютеры", "МБОУ СОШ №5",
     {"SOCIAL": True, "PROJECT": False, "DIRECT_SUPPLY": True}),
    ("Капитальный ремонт офиса", "43.21.10", "Работы по монтажу", "ООО Ромашка",
     {"SOCIAL": False, "PROJECT": True, "DIRECT_SUPPLY": False}),
    ("Поставка картриджей", "26.20.16", "Картриджи", "ООО Ромашка",
     {"SOCIAL": False, "PROJECT": False, "DIRECT_SUPPLY": True}),
]


def load_make_run_data():
    spec = importlib.util.spec_from_file_location(
        "make_run_data", os.path.join(STAGE1, "make_run_data.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case_record(title, okpd, okpd_name, customer, **extra):
    record = {"id": 1, "title": title, "okpd_code": okpd, "okpd_name": okpd_name,
              "customer": customer, "object_type": ""}
    record.update(extra)
    return record


def test_canonical_wip_cases_match_business_semantics():
    for title, okpd, okpd_name, customer, expected in CANONICAL_CASES:
        labels = derive_labels(title=title, okpd_code=okpd, okpd_name=okpd_name, customer=customer)
        assert labels == expected, (title, labels, expected)


def test_labels_are_exactly_three_independent_flags():
    record = _case_record(*CANONICAL_CASES[1][:4])
    example = build_example(record)
    assert tuple(example["labels"]) == LABELS
    assert all(isinstance(example["labels"][name], bool) for name in LABELS)
    # the three flags are independent, not a single collapsed verdict
    assert example["labels"]["SOCIAL"] is True
    assert example["labels"]["PROJECT"] is False


def test_medal_vocabulary_never_appears():
    blob = json.dumps(build_example(_case_record(*CANONICAL_CASES[0][:4])), ensure_ascii=False).upper()
    for banned in ("GOLD", "SILVER", "BRONZE", "WOOD", "PRIORITY_SCORE"):
        assert banned not in blob


def test_price_never_influences_labels_or_prompt():
    base = _case_record(*CANONICAL_CASES[0][:4])
    cheap = build_example(dict(base, initial_price=1))
    pricey = build_example(dict(base, initial_price=1_000_000_000))
    assert cheap["labels"] == pricey["labels"]
    assert cheap["messages"] == pricey["messages"]


def test_target_json_round_trips_through_parse_labels():
    for _, _, _, _, expected in CANONICAL_CASES:
        assert parse_labels(target_json(expected)) == expected


def test_parse_labels_is_tolerant_and_strict():
    assert parse_labels('{"SOCIAL": true, "PROJECT": false, "DIRECT_SUPPLY": true}') == {
        "SOCIAL": True, "PROJECT": False, "DIRECT_SUPPLY": True}
    assert parse_labels('```json\n{"SOCIAL": "true", "PROJECT": "false", "DIRECT_SUPPLY": "false"}\n```') == {
        "SOCIAL": True, "PROJECT": False, "DIRECT_SUPPLY": False}
    assert parse_labels("никакого json здесь нет") is None
    assert parse_labels('{"SOCIAL": true}') is None
    assert parse_labels('{"SOCIAL": "maybe", "PROJECT": false, "DIRECT_SUPPLY": false}') is None


def test_example_is_stamped_with_prompt_version():
    example = build_example(_case_record(*CANONICAL_CASES[2][:4]))
    assert example["prompt_version"] == PROMPT_VERSION
    assert example["messages"][0]["role"] == "system"
    assert example["messages"][-1]["content"] == target_json(example["labels"])


def test_user_message_truncates_oversized_fields():
    record = _case_record("т" * 4000, "26.20.15", "о" * 4000, "к" * 4000, object_type="o" * 400)
    message = build_user_message(record)
    assert "т" * 120 in message and "т" * 121 not in message
    assert "о" * 55 in message and "о" * 56 not in message
    assert "к" * 70 in message and "к" * 71 not in message
    # documented worst case for the compact prompt v2 template
    assert len(message) <= 620


def test_make_run_data_slice_is_deterministic(tmp_path):
    module = load_make_run_data()
    src = tmp_path / "src"
    src.mkdir()
    rows = [{"labels": {name: bool(i % 2) for name in LABELS}, "n": i} for i in range(20)]
    (src / "train.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for name in ("validation.jsonl", "test.jsonl"):
        (src / name).write_text(json.dumps({"labels": {}, "n": "holdout"}) + "\n", encoding="utf-8")

    outs = []
    for run in range(2):
        dst = tmp_path / ("dst%d" % run)
        sys.argv = ["make_run_data.py", "--src", str(src), "--dst", str(dst), "--rows", "7"]
        assert module.main() == 0
        train = [json.loads(l) for l in (dst / "train.jsonl").read_text(encoding="utf-8").splitlines()]
        outs.append([r["n"] for r in train])
        assert len(train) == 7
        for name in ("validation.jsonl", "test.jsonl"):
            assert (dst / name).read_text(encoding="utf-8") == (src / name).read_text(encoding="utf-8")
    assert outs[0] == outs[1]


def test_make_run_data_rows_zero_keeps_everything(tmp_path):
    module = load_make_run_data()
    src = tmp_path / "src"
    src.mkdir()
    rows = [{"labels": {name: True for name in LABELS}, "n": i} for i in range(5)]
    (src / "train.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for name in ("validation.jsonl", "test.jsonl"):
        (src / name).write_text("", encoding="utf-8")
    dst = tmp_path / "dst"
    sys.argv = ["make_run_data.py", "--src", str(src), "--dst", str(dst), "--rows", "0"]
    assert module.main() == 0
    assert len((dst / "train.jsonl").read_text(encoding="utf-8").splitlines()) == 5