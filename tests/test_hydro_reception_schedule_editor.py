import json
from datetime import time
from pathlib import Path

from src.services.hydro.company_repository import (
    HydroCompanyRepository,
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


class WriteCaptureDB:
    def __init__(self):
        self.calls = []

    def execute_query(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        if "RETURNING id" in sql:
            return [{"id": 21}]
        return []


def test_reception_type_walk_in_label():
    assert RECEPTION_TYPE_LABELS["daily"] == "Живая очередь"


def test_reception_type_appointment_label():
    assert RECEPTION_TYPE_LABELS["scheduled"] == "По предварительной записи"


def test_weekday_time_roundtrip():
    raw = {"mon": {"from": "09:00", "to": "18:00"}}
    assert normalize_weekly_schedule(raw) == (raw, None)
    assert json.loads(json.dumps(schedule_for_storage(raw))) == raw


def test_company_reception_schedule_is_written_as_jsonb():
    db = WriteCaptureDB()
    repo = HydroCompanyRepository(db)
    schedule = {"mon": {"from": "09:00", "to": "18:00"}}
    repo.save_params(7, {"reception_type": "scheduled", "reception_schedule": schedule})
    sql, params = db.calls[0]
    assert "reception_type = %s" in sql
    assert "reception_schedule = %s::jsonb" in sql
    assert params == ("scheduled", json.dumps(schedule, ensure_ascii=False), 7)


def test_contact_reception_schedule_is_written_on_create_and_update():
    schedule = {"tue": {"from": "15:00", "to": "18:00"}}
    db = WriteCaptureDB()
    repo = HydroCompanyRepository(db)
    contact_id = repo.add_contact(7, {
        "full_name": "Тест", "role": "Инженер", "reception_type": "scheduled",
        "reception_schedule": schedule, "reception_note": "По звонку",
    })
    assert contact_id == 21
    insert_sql, insert_params = db.calls[0]
    assert "reception_schedule" in insert_sql
    assert insert_params[9] == json.dumps(schedule, ensure_ascii=False)
    assert insert_params[10] == "По звонку"

    db.calls.clear()
    assert repo.update_contact(21, {
        "company_id": 7, "full_name": "Тест", "role": "Инженер",
        "reception_type": "daily", "reception_schedule": schedule,
        "reception_note": "Без записи",
    })
    update_sql, update_params = db.calls[-1]
    assert "reception_schedule = %s::jsonb" in update_sql
    assert update_params[7] == "daily"
    assert update_params[8] == json.dumps(schedule, ensure_ascii=False)
    assert update_params[9] == "Без записи"


def test_disabled_day_not_saved():
    schedule, legacy = normalize_weekly_schedule({
        "mon": {"from": "09:00", "to": "18:00"},
        "sat": {"enabled": False, "start": "09:00", "end": "12:00"},
    })
    assert schedule == {"mon": {"from": "09:00", "to": "18:00"}}
    assert legacy is None


def test_editor_contains_weekdays_only_and_summary_hides_weekend():
    from src.ui.reception_schedule_editor import DAYS

    assert [day for day, _, _ in DAYS] == ["mon", "tue", "wed", "thu", "fri"]
    assert format_compact_schedule({
        "mon": {"from": "09:00", "to": "18:00"},
        "sat": {"from": "10:00", "to": "12:00"},
        "sun": {"from": "10:00", "to": "12:00"},
    }) == "Пн　09:00–18:00\nВт–Пт　выходной"


def test_time_controls_rerun_outside_forms():
    editor = (ROOT / "src/ui/reception_schedule_editor.py").read_text(encoding="utf-8")
    workspace = (ROOT / "src/ui/hydro_inline_workspace_tabs.py").read_text(encoding="utf-8")
    assert '"Применить Пн–Пт", key=f"{prefix}_apply_weekdays"' in editor
    assert "disabled=not enabled" in editor
    assert "st.form_submit_button(\"Сохранить график" not in workspace


def test_shared_component_can_render_multiple_instances():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
from src.ui.reception_schedule_editor import render_reception_schedule_editor
render_reception_schedule_editor("company", "daily", None)
render_reception_schedule_editor("contact_engineer", "scheduled", None)
render_reception_schedule_editor("contact_operations", "daily", None)
''').run()
    assert not app.exception


def test_shared_component_can_render_multiple_instances():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
from src.ui.reception_schedule_editor import render_reception_schedule_editor
render_reception_schedule_editor("company", "daily", None)
render_reception_schedule_editor("contact_engineer", "scheduled", None)
render_reception_schedule_editor("contact_operations", "daily", None)
''').run()
    assert not app.exception


def test_time_controls_rerun_outside_forms():
    editor = (ROOT / "src/ui/reception_schedule_editor.py").read_text(encoding="utf-8")
    workspace = (ROOT / "src/ui/hydro_inline_workspace_tabs.py").read_text(encoding="utf-8")
    assert '"Применить Пн–Пт", key=f"{prefix}_apply_weekdays"' in editor
    assert "disabled=not enabled" in editor
    assert "st.form_submit_button(\"Сохранить график" not in workspace


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
    }) == "Пн–Пт　09:00–18:00"


def test_appointment_readonly_view_shows_only_reception_days():
    assert format_compact_schedule({
        "tue": {"from": "15:00", "to": "18:00"},
        "thu": {"from": "10:00", "to": "13:00"},
    }, "scheduled") == "Вт　15:00–18:00\nЧт　10:00–13:00"

