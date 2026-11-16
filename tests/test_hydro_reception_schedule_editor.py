import json
from datetime import time
from pathlib import Path

from src.services.hydro.company_repository import (
    RECEPTION_TYPE_LABELS,
    schedule_for_storage,
)
from src.ui.reception_schedule_editor import (
    apply_weekday_shortcut,
    format_compact_schedule,
    normalize_weekly_schedule,
    validate_weekly_schedule,
)


ROOT = Path(__file__).resolve().parents[1]


def test_reception_type_walk_in_label():
    assert RECEPTION_TYPE_LABELS["daily"] == "Живая очередь"


def test_reception_type_appointment_label():
    assert RECEPTION_TYPE_LABELS["scheduled"] == "По предварительной записи"


def test_weekday_time_roundtrip():
    raw = {"mon": {"from": "09:00", "to": "18:00"}}
    assert normalize_weekly_schedule(raw) == (raw, None)
    assert json.loads(json.dumps(schedule_for_storage(raw))) == raw


def test_disabled_day_not_saved():
    schedule, legacy = normalize_weekly_schedule({
        "mon": {"from": "09:00", "to": "18:00"},
        "sat": {"enabled": False, "start": "09:00", "end": "12:00"},
    })
    assert schedule == {"mon": {"from": "09:00", "to": "18:00"}}
    assert legacy is None


def test_start_before_end_validation():
    assert validate_weekly_schedule({
        "mon": {"from": "18:00", "to": "09:00"},
    }) == "Время окончания должно быть позже времени начала."
    assert validate_weekly_schedule({
        "mon": {"from": "09:00", "to": "18:00"},
    }) is None


def test_apply_weekdays_shortcut():
    schedule = {"sat": {"from": "10:00", "to": "13:00"}}
    result = apply_weekday_shortcut(schedule, time(9, 0), time(18, 0))
    assert set(result) == {"mon", "tue", "wed", "thu", "fri", "sat"}
    assert result["fri"] == {"from": "09:00", "to": "18:00"}
    assert result["sat"] == schedule["sat"]


def test_schedule_json_normalization():
    normalized, legacy = normalize_weekly_schedule({
        "mon": {"enabled": True, "start": "09:00", "end": "18:00"},
        "tue": {"from": "10:00", "to": "17:00"},
    })
    assert normalized == {
        "mon": {"from": "09:00", "to": "18:00"},
        "tue": {"from": "10:00", "to": "17:00"},
    }
    assert legacy is None


def test_existing_legacy_schedule_readable():
    text_schedule, text_legacy = normalize_weekly_schedule("пн 09:00-18:00; вт 10:00–17:00")
    json_schedule, json_legacy = normalize_weekly_schedule({"пн": "09:00-18:00"})
    assert text_schedule["mon"] == {"from": "09:00", "to": "18:00"}
    assert text_schedule["tue"] == {"from": "10:00", "to": "17:00"}
    assert json_schedule["mon"] == {"from": "09:00", "to": "18:00"}
    assert text_legacy is json_legacy is None


def test_unknown_legacy_schedule_not_destroyed():
    raw = "по звонку, уточнить у диспетчера"
    schedule, legacy = normalize_weekly_schedule(raw)
    assert schedule == {}
    assert legacy == raw
    assert schedule_for_storage({"_legacy": legacy}) == {"_legacy": raw}
    assert "Старый график" in format_compact_schedule(raw)


def test_company_uses_shared_schedule_component():
    source = (ROOT / "src/ui/hydro_inline_workspace_tabs.py").read_text(encoding="utf-8")
    assert "hydro_company_reception_" in source
    assert "render_reception_schedule_editor(" in source


def test_contact_uses_shared_schedule_component():
    source = (ROOT / "src/ui/hydro_inline_workspace_tabs.py").read_text(encoding="utf-8")
    assert "hydro_contact_reception_{contact_id}" in source
    assert "hydro_contact_add_reception_{cid}" in source
    assert source.count("render_reception_schedule_editor(") >= 3


def test_readonly_schedule_compacts_equal_days():
    assert format_compact_schedule({
        day: {"from": "09:00", "to": "18:00"}
        for day in ("mon", "tue", "wed", "thu", "fri")
    }) == "Пн–Пт　09:00–18:00\nСб–Вс　выходной"


def test_appointment_readonly_view_shows_only_reception_days():
    assert format_compact_schedule({
        "tue": {"from": "15:00", "to": "18:00"},
        "thu": {"from": "10:00", "to": "13:00"},
    }, "scheduled") == "Вт　15:00–18:00\nЧт　10:00–13:00"

