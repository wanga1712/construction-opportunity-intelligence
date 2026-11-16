"""Tests for waterproofing call prep and the call calendar."""
from src.ui.hydro_cards import call_calendar_rows, call_readiness


def test_call_readiness_accepts_all_mandatory_fields():
    result = call_readiness({
        "phone": "+7 495 000-00-00",
        "reception_hours": "Пн–Пт 09:00–18:00",
        "responsible": "Иванов",
        "next_action": "Согласовать встречу",
        "next_action_date": "2026-11-12",
        "next_action_time": "10:30",
    })

    assert result["ready"] is True
    assert result["missing"] == []
    assert result["goal"] == "Согласовать встречу"


def test_call_readiness_lists_missing_fields_in_call_order():
    result = call_readiness({
        "phone": "",
        "reception_hours": "",
        "responsible": "—",
        "next_action": "",
        "next_action_date": "",
        "next_action_time": "",
        "stage": "new",
    })

    assert result["ready"] is False
    assert result["missing"] == [
        "телефон",
        "часы приёма",
        "ответственный",
        "следующее действие",
        "дата касания",
        "время звонка",
    ]


def test_call_calendar_keeps_equal_times_for_different_uk_as_separate_rows():
    rows = call_calendar_rows([
        {
            "key": "uk-1",
            "uk_name_short": "УК «Один»",
            "next_action_date": "2026-11-12",
            "next_action_time": "10:30",
            "next_action": "Позвонить",
            "reception_hours": "Пн–Пт 09:00–18:00",
        },
        {
            "key": "uk-2",
            "uk_name_short": "УК «Два»",
            "next_action_date": "2026-11-12",
            "next_action_time": "10:30",
            "next_action": "Позвонить",
            "reception_hours": "Пн–Пт 09:00–18:00",
        },
    ])

    assert len(rows) == 2
    assert [row["УК"] for row in rows] == ["УК «Два»", "УК «Один»"]
