"""Unit tests for the UK-centric waterproofing CRM model.

The contour funnel tracks management companies (УК) instead of single objects,
so these tests pin the stage, priority, overdue and board logic that the kanban
main screen relies on.
"""
from datetime import date

import pytest

from src.services import waterproofing_contour as contour
from src.services.waterproofing_615 import address_key, summarize_addresses
from src.services.waterproofing_crm import (
    CLOSED_STAGES,
    CRM_STAGE_LABELS,
    CRM_STAGES,
    board_kpis,
    build_card,
    contour_key,
    default_priority,
    format_amount,
    has_tech_contact,
    is_closed_stage,
    is_municipal_uk,
    is_overdue,
    kanban_columns,
    next_touch_default,
    normalize_priority,
    normalize_stage,
    overdue_days,
    parse_amount,
    parse_date,
    priority_icon,
    priority_reason,
    sort_cards,
    stage_index,
    uk_display_name,
)
from src.services.waterproofing_funnel import (
    DEAL_STAGE_IDS,
    FUNNEL_ACCOUNT,
    FUNNEL_DEAL,
    coerce_stage,
)


def test_crm_stages_match_requested_account_funnel():
    """The board runs on stable ids; the Russian names are UI labels only."""
    assert CRM_STAGES == ["new", "meeting", "followup", "survey_approved"]
    assert CLOSED_STAGES == ("closed",)
    assert CRM_STAGE_LABELS["new"] == "Новая УК / База"
    assert CRM_STAGE_LABELS["survey_approved"] == "Доступ к объектам"


def test_deal_funnel_stages_are_separate_from_the_account_funnel():
    assert DEAL_STAGE_IDS == (
        "survey", "proposal", "specification", "procurement", "contract",
    )
    assert not set(DEAL_STAGE_IDS) & set(CRM_STAGES)


def test_normalize_stage_accepts_canonical_values():
    for stage in CRM_STAGES:
        assert normalize_stage(stage) == stage
    assert normalize_stage("  new  ") == "new"


def test_normalize_stage_maps_the_old_first_stage_name():
    assert normalize_stage("Контур найден") == "new"


def test_normalize_stage_maps_legacy_object_contour_values():
    assert normalize_stage("Секретарь / общий телефон найден") == "new"
    assert normalize_stage("Запрошен начальник эксплуатации") == "new"
    assert normalize_stage("Контакт эксплуатации получен") == "meeting"
    assert normalize_stage("Первая встреча проведена") == "followup"
    assert normalize_stage("Выбран объект для обследования") == "survey_approved"
    assert normalize_stage("Сделка / ТКП по объекту") == "proposal"


def test_normalize_stage_maps_the_previous_single_board_funnel():
    assert normalize_stage("Первичный звонок") == "new"
    assert normalize_stage("Секретарь / диспетчер") == "new"
    assert normalize_stage("Найден тех. контакт") == "meeting"
    assert normalize_stage("Встреча назначена") == "meeting"
    assert normalize_stage("Обследование назначено") == "survey_approved"
    assert normalize_stage("Обследование проведено") == "survey"
    assert normalize_stage("КП / техрешение") == "proposal"
    assert normalize_stage("Согласование / ТЗ / торги") == "specification"
    assert normalize_stage("Договор / работы") == "contract"
    assert normalize_stage("Отложено / отказ") == "closed"


def test_coerce_stage_never_resets_a_contour_to_the_first_column():
    """A contour saved on the object funnel has already granted object access."""
    assert coerce_stage("Обследование проведено", FUNNEL_ACCOUNT) == "survey_approved"
    assert coerce_stage("Согласование / ТЗ / торги", FUNNEL_ACCOUNT) == "survey_approved"
    assert coerce_stage("Договор / работы", FUNNEL_ACCOUNT) == "survey_approved"
    assert coerce_stage("closed", FUNNEL_ACCOUNT) == "closed"
    # And an object deal saved at an УК stage has not been surveyed yet.
    assert coerce_stage("new", FUNNEL_DEAL) == "survey"
    assert coerce_stage("survey_approved", FUNNEL_DEAL) == "survey"


def test_normalize_stage_falls_back_to_first_stage():
    assert normalize_stage(None) == CRM_STAGES[0]
    assert normalize_stage("") == CRM_STAGES[0]
    assert normalize_stage("Неизвестный этап") == CRM_STAGES[0]


def test_stage_index_and_closed_flag():
    assert stage_index("new") == 0
    assert stage_index("meeting") == 1
    assert stage_index("followup") == 2
    assert stage_index("survey_approved") == 3
    # A closed contour sits past the four board columns instead of inside them.
    assert stage_index("closed") == 4
    assert stage_index(None) == 0
    assert is_closed_stage("closed") is True
    assert is_closed_stage("new") is False


def test_default_priority_counts_parkings_and_underground_floors():
    # 11 паркингов по 2 этажа и 3 паркинга по 5 этажей — оба крупные контуры.
    assert default_priority(parkings=11, total_underground_floors=22) == "Gold"
    assert default_priority(parkings=3, total_underground_floors=15) == "Gold"
    assert default_priority(parkings=5, total_underground_floors=10) == "Gold"
    assert default_priority(parkings=4, total_underground_floors=9) == "Silver"
    assert default_priority(parkings=3, total_underground_floors=6) == "Silver"
    assert default_priority(parkings=2, total_underground_floors=4) == "Silver"
    assert default_priority(parkings=1, total_underground_floors=2) == "Bronze"
    assert default_priority(parkings=0, total_underground_floors=0) == "Bronze"


def test_priority_reason_explains_the_priority():
    assert priority_reason(parkings=3, total_underground_floors=6) == "3 паркинг(ов) · 6 подземных этажей"


def test_normalize_priority_prefers_saved_value_and_capitalizes():
    assert normalize_priority("gold", parkings=1, total_underground_floors=0) == "Gold"
    assert normalize_priority("SILVER", parkings=0, total_underground_floors=0) == "Silver"
    assert normalize_priority("bronze", parkings=9, total_underground_floors=20) == "Bronze"
    assert normalize_priority("", parkings=9, total_underground_floors=20) == "Gold"
    assert normalize_priority("Платина", parkings=3, total_underground_floors=6) == "Silver"


def test_uk_display_name_shortens_the_legal_form():
    assert uk_display_name("Управляющая компания «Вк комфорт»") == "УК «Вк Комфорт»"
    assert uk_display_name("Управляющая компания «Жилищник пресненского района»") == (
        "УК «Жилищник Пресненского района»"
    )
    assert uk_display_name("Управляющая компания «ПИК-Комфорт Сириус»") == "УК «ПИК-Комфорт Сириус»"
    assert uk_display_name("Товарищество собственников «Ленинский 25»") == "ТСЖ «Ленинский 25»"
    assert uk_display_name("ГБУ «Жилищник района Хамовники»") == "ГБУ «Жилищник района Хамовники»"
    assert uk_display_name("Жилищно-строительный кооператив «Восход»") == "ЖСК «Восход»"
    assert uk_display_name("") == "Без названия"


def test_is_municipal_uk_flags_zhilishnik():
    assert is_municipal_uk("Управляющая компания «Жилищник района ломоносовский»") is True
    assert is_municipal_uk("ГБУ «Жилищник района Хамовники»") is True
    assert is_municipal_uk("Управляющая компания «Вк комфорт»") is False
    assert is_municipal_uk("") is False


def test_priority_icon():
    assert priority_icon("Gold") == "🥇"
    assert priority_icon("Silver") == "🥈"
    assert priority_icon("Bronze") == "🥉"
    assert priority_icon("unknown") == "🥉"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (4_200_000, 4_200_000.0),
        ("4,2 млн", 4_200_000.0),
        ("4.2 млн ₽", 4_200_000.0),
        ("4200 тыс", 4_200_000.0),
        ("1 250 000", 1_250_000.0),
        ("350000", 350_000.0),
        ("", 0.0),
        (None, 0.0),
        ("не указано", 0.0),
        (-5, 0.0),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == pytest.approx(expected)


def test_format_amount():
    assert format_amount(4_200_000) == "4.2 млн ₽"
    assert format_amount(2_000_000) == "2 млн ₽"
    assert format_amount(350_000) == "350 тыс ₽"
    assert format_amount(1_000) == "1 тыс ₽"
    assert format_amount(750) == "750 ₽"
    assert format_amount(0) == "—"
    assert format_amount("нет данных") == "—"


def test_parse_date():
    assert parse_date("2026-09-28") == date(2026, 9, 28)
    assert parse_date("2026-09-28T10:00:00") == date(2026, 9, 28)
    assert parse_date(date(2026, 1, 2)) == date(2026, 1, 2)
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date("28.09.2026") is None


def test_next_touch_default_uses_stage_cadence():
    today = date(2026, 9, 28)
    assert next_touch_default("Контур найден", today=today) == "2026-09-29"
    assert next_touch_default("КП / техрешение", today=today) == "2026-10-03"
    assert next_touch_default("Согласование / ТЗ / торги", today=today) == "2026-10-05"
    assert next_touch_default("Отложено / отказ", today=today) == "2026-10-28"
    # An unknown stage is normalised to the first funnel stage before lookup.
    assert next_touch_default("Что-то новое", today=today) == "2026-09-29"


def test_has_tech_contact():
    assert has_tech_contact(None) is False
    assert has_tech_contact({}) is False
    assert has_tech_contact({"exploitation_contact": "   "}) is False
    assert has_tech_contact({"tech_contact_phone": ""}) is False
    assert has_tech_contact({"exploitation_contact": "Иванов И.И."}) is True
    assert has_tech_contact({"tech_contact_phone": "+7 495 000-00-00"}) is True


def test_overdue_days_and_flag():
    today = date(2026, 9, 28)
    overdue = {"stage": "Первичный звонок", "next_action_date": "2026-09-20"}
    assert overdue_days(overdue, today=today) == 8
    assert is_overdue(overdue, today=today) is True

    future = {"stage": "Первичный звонок", "next_action_date": "2026-10-05"}
    assert overdue_days(future, today=today) == 0
    assert is_overdue(future, today=today) is False

    # Due exactly today is not overdue yet.
    due_today = {"stage": "Первичный звонок", "next_action_date": "2026-09-28"}
    assert overdue_days(due_today, today=today) == 0

    # Closed contours never report overdue, and a missing date is never overdue.
    closed = {"stage": "Отложено / отказ", "next_action_date": "2026-01-01"}
    assert overdue_days(closed, today=today) == 0
    assert overdue_days({"stage": "Первичный звонок"}, today=today) == 0
    assert overdue_days(None, today=today) == 0


def _uk_row(**overrides):
    row = {
        "uk_name": "ООО «УК Тест»",
        "uk_inn": "7701234567",
        "uk_ogrn": "1157746000000",
        "uk_phone": "+7 495 111-22-33",
        "uk_address": "119313, Г.МОСКВА, ПР-КТ ЛЕНИНСКИЙ, д. 88",
        "object_count": 4,
        "parking_count": 4,
        "total_underground_floors": 9,
        "max_underground_floors": 3,
        "ge1_floors": 2,
        "ge2_floors": 1,
    }
    row.update(overrides)
    return row


def test_build_card_merges_database_row_with_saved_state():
    card = build_card(
        _uk_row(),
        {
            "key": "1157746000000",
            "stage": "followup",
            "next_action": "Подготовить КП",
            "next_action_date": "2026-10-10",
            "responsible": "Петров",
            "priority": "Gold",
            "potential_amount": "4,2 млн",
            "exploitation_contact": "Иванов И.И.",
        },
    )
    assert card["uk_name"] == "ООО «УК Тест»"
    assert card["uk_inn"] == "7701234567"
    assert card["uk_ogrn"] == "1157746000000"
    assert card["object_count"] == 4
    assert card["ge1_floors"] == 2
    assert card["stage"] == "followup"
    assert card["stage_label"] == "Встреча / Дожим"
    assert card["stage_index"] == 2
    assert card["next_action"] == "Подготовить КП"
    assert card["next_action_date"] == "2026-10-10"
    assert card["priority"] == "Gold"
    assert card["priority_icon"] == "🥇"
    assert card["uk_address"] == "119313, Г.МОСКВА, ПР-КТ ЛЕНИНСКИЙ, д. 88"
    assert card["parking_count"] == 4
    assert card["total_underground_floors"] == 9
    assert card["priority_reason"] == "4 паркинг(ов) · 9 подземных этажей"
    assert card["potential_amount"] == pytest.approx(4_200_000.0)
    assert card["potential_amount_label"] == "4.2 млн ₽"
    assert card["tech_contact"] is True
    assert card["tech_contact_person"] == "Иванов И.И."
    assert card["responsible"] == "Петров"
    assert card["in_work"] is True
    assert card["phone"] == "+7 495 111-22-33"


def test_build_card_defaults_without_saved_state():
    card = build_card(_uk_row(
        object_count=1, parking_count=1, total_underground_floors=1,
        max_underground_floors=1, ge1_floors=0, ge2_floors=0,
    ))
    assert card["stage"] == CRM_STAGES[0]
    assert card["in_work"] is False
    assert card["priority"] == "Bronze"
    assert card["next_action"] == "Дозвониться в УК и выйти на техническую службу"
    assert card["responsible"] == "—"
    assert card["tech_contact"] is False
    assert card["potential_amount_label"] == "—"
    assert card["overdue"] is False


def test_build_card_derives_key_from_row_when_state_is_absent():
    row = _uk_row()
    card = build_card(row)
    assert card["key"] == contour_key(row) == "1157746000000"


def test_build_card_keys_stay_unique_across_contour_rows():
    other = _uk_row(uk_ogrn="1027700132195", uk_inn="7707083893", uk_name="ООО «УК Другая»")
    keys = {build_card(_uk_row())["key"], build_card(other)["key"]}
    assert len(keys) == 2


def test_build_card_applies_priority_heuristic_without_override():
    card = build_card(
        _uk_row(parking_count=4, total_underground_floors=9, max_underground_floors=3),
        {"key": "x"},
    )
    assert card["priority"] == "Silver"
    assert card["priority_icon"] == "🥈"

    gold = build_card(_uk_row(parking_count=3, total_underground_floors=15), {"key": "y"})
    assert gold["priority"] == "Gold"


def test_build_card_accepts_615_pp_slice():
    card = build_card(_uk_row(), None, tenders_615={
        "tenders": 3, "amount": 70_014_959.0, "waterproofing_tenders": 1,
        "last_date": "2026-09-11", "year": "2026",
    })
    assert card["tenders_615_count"] == 3
    assert card["tenders_615_amount_label"] == "70 млн ₽"
    assert card["tenders_615_waterproofing"] == 1
    assert card["tenders_615_last_date"] == "2026-09-11"
    assert card["tenders_615_year"] == "2026"


def test_sort_cards_puts_overdue_then_priority_then_zhilishnik():
    cards = [
        {"uk_name": "B", "overdue": False, "next_action_date": "2026-10-05", "priority": "Gold"},
        {"uk_name": "A", "overdue": False, "next_action_date": "2026-09-30", "priority": "Bronze"},
        {"uk_name": "C", "overdue": True, "next_action_date": "2026-09-29", "priority": "Silver"},
        {"uk_name": "D", "overdue": False, "next_action_date": "", "priority": "Gold"},
    ]
    ordered = [card["uk_name"] for card in sort_cards(cards)]
    # просрочка -> приоритет -> дата касания
    assert ordered == ["C", "B", "D", "A"]


def test_sort_cards_lifts_municipal_uk_inside_the_same_priority():
    cards = [
        {"uk_name": "Коммерческая", "overdue": False, "priority": "Silver",
         "next_action_date": "2026-10-01", "municipal": False},
        {"uk_name": "Жилищник", "overdue": False, "priority": "Silver",
         "next_action_date": "2026-10-02", "municipal": True},
    ]
    ordered = [card["uk_name"] for card in sort_cards(cards)]
    assert ordered == ["Жилищник", "Коммерческая"]


def test_kanban_columns_group_cards_and_keep_stage_order():
    cards = [
        {
            "uk_name": "A",
            "stage": "new",
            "potential_amount": 1_000_000,
            "priority": "Gold",
            "overdue": False,
            "next_action_date": "2026-10-01",
        },
        {
            "uk_name": "B",
            "stage": "followup",
            "potential_amount": 2_000_000,
            "priority": "Silver",
            "overdue": False,
            "next_action_date": "2026-10-02",
        },
        {
            "uk_name": "C",
            "stage": "new",
            "potential_amount": 500_000,
            "priority": "Bronze",
            "overdue": False,
            "next_action_date": "2026-10-03",
        },
    ]
    columns = kanban_columns(cards)
    assert [column["stage"] for column in columns] == CRM_STAGES
    assert len(columns) == 4

    first = columns[0]
    assert first["count"] == 2
    assert [card["uk_name"] for card in first["cards"]] == ["A", "C"]
    assert first["amount_label"] == "1.5 млн ₽"

    followup = columns[2]
    assert followup["stage"] == "followup"
    assert followup["count"] == 1
    assert followup["amount_label"] == "2 млн ₽"

    assert columns[1]["count"] == 0
    assert columns[1]["amount_label"] == "—"


def test_kanban_columns_never_mix_the_two_funnels():
    """An object-funnel stage may not open a fifth column on the УК board."""
    columns = kanban_columns([
        {"uk_name": "A", "stage": "proposal", "priority": "Gold",
         "overdue": False, "next_action_date": "2026-10-01"},
        {"uk_name": "B", "stage": "closed", "priority": "Gold",
         "overdue": False, "next_action_date": "2026-10-01"},
    ])
    assert [column["stage"] for column in columns] == CRM_STAGES
    assert sum(column["count"] for column in columns) == 1
    assert columns[3]["count"] == 1
    assert columns[3]["cards"][0]["uk_name"] == "A"


def test_board_kpis_aggregate_the_main_screen_numbers():
    cards = [
        {
            "overdue": True,
            "in_work": True,
            "object_count": 4,
            "parking_count": 4,
            "total_underground_floors": 9,
            "ge1_floors": 3,
            "ge2_floors": 2,
            "municipal": True,
            "tech_contact": True,
            "potential_amount": 1_500_000.0,
        },
        {
            "overdue": False,
            "in_work": False,
            "object_count": 2,
            "parking_count": 1,
            "total_underground_floors": 2,
            "ge1_floors": 0,
            "ge2_floors": 0,
            "municipal": False,
            "tech_contact": False,
            "potential_amount": 500_000.0,
        },
    ]
    kpis = board_kpis(cards)
    assert kpis["contours"] == 2
    assert kpis["in_work"] == 1
    assert kpis["objects"] == 6
    assert kpis["parkings"] == 5
    assert kpis["underground_floors"] == 11
    assert kpis["underground_objects"] == 3
    assert kpis["ge2_floors"] == 2
    assert kpis["municipal"] == 1
    assert kpis["overdue"] == 1
    assert kpis["with_tech_contact"] == 1
    assert kpis["amount"] == pytest.approx(2_000_000.0)
    assert kpis["amount_label"] == "2 млн ₽"


def test_contour_state_roundtrip_and_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(contour, "_STATE_PATH", tmp_path / "contour_states.jsonl")

    assert contour.load_contour_history("UK1") == []
    assert contour.latest_contour_state("UK1") == {}

    contour.merge_contour_state("UK1", {"stage": "new", "responsible": "Петров"})
    contour.merge_contour_state("UK1", {"stage": "meeting"})

    history = contour.load_contour_history("UK1")
    assert [row["stage"] for row in history] == ["new", "meeting"]

    latest = contour.latest_contour_state("UK1")
    assert latest["stage"] == "meeting"
    # merge inherits fields from the previous record instead of dropping them
    assert latest["responsible"] == "Петров"
    assert latest["key"] == "UK1"
    assert latest["updated_at"]


def test_contour_states_are_isolated_per_key(tmp_path, monkeypatch):
    monkeypatch.setattr(contour, "_STATE_PATH", tmp_path / "states.jsonl")
    contour.merge_contour_state("A", {"stage": "new"})
    contour.merge_contour_state("B", {"stage": "followup"})
    assert contour.latest_contour_state("A")["stage"] == "new"
    assert contour.latest_contour_state("B")["stage"] == "followup"
    merged = contour.merge_contour_state("A", {"note": "перезвонить"})
    assert merged["stage"] == "new"
    assert merged["note"] == "перезвонить"


def test_load_contour_states_returns_newest_per_contour(tmp_path, monkeypatch):
    monkeypatch.setattr(contour, "_STATE_PATH", tmp_path / "states.jsonl")
    contour.merge_contour_state("A", {"stage": "new"})
    contour.merge_contour_state("A", {"stage": "meeting"})
    contour.merge_contour_state("B", {"stage": "new"})
    states = contour.load_contour_states()
    assert states["A"]["stage"] == "meeting"
    assert states["B"]["stage"] == "new"


def test_load_contour_history_skips_malformed_lines(tmp_path, monkeypatch):
    state_path = tmp_path / "states.jsonl"
    state_path.write_text(
        '{"key": "A", "stage": "new"}\nnot json\n', encoding="utf-8"
    )
    monkeypatch.setattr(contour, "_STATE_PATH", state_path)
    history = contour.load_contour_history("A")
    assert len(history) == 1
    assert history[0]["stage"] == "new"


def test_saved_contour_state_drives_board_card(tmp_path, monkeypatch):
    monkeypatch.setattr(contour, "_STATE_PATH", tmp_path / "states.jsonl")
    contour.merge_contour_state(
        "1157746000000",
        {
            "stage": "Согласование / ТЗ / торги",
            "next_action_date": "2026-09-01",
            "potential_amount": "3,5 млн",
        },
    )
    state = contour.latest_contour_state("1157746000000")
    card = build_card(_uk_row(), state)
    # Saved before the funnel was split: the contour keeps its progress instead of
    # restarting from «Новая УК / База».
    assert card["stage"] == "survey_approved"
    assert card["stage_label"] == "Доступ к объектам"
    assert card["stage_index"] == 3
    assert card["in_work"] is True
    assert card["potential_amount_label"] == "3.5 млн ₽"
    assert card["overdue"] is True


def test_615_address_key_matches_615_and_nspd_formats():
    assert address_key("Ломоносовский пр-кт 27 к.1") == address_key(
        "Российская Федерация, город Москва, вн.тер.г. муниципальный округ Раменки, "
        "проспект Ломоносовский, дом 27, корпус 4"
    )
    assert address_key("Чистый пер. 5А") == address_key(
        "Российская Федерация, город Москва, вн.тер.г. муниципальный округ Хамовники, "
        "переулок Чистый, дом 5А"
    )
    # Аббревиатура «Б.» разворачивается в «Большая».
    assert address_key("Серпуховская Б. ул. 31 к.10") == address_key(
        "Российская Федерация, город Москва, вн.тер.г. муниципальный округ Замоскворечье, "
        "улица Большая Серпуховская, дом 31, строение 15"
    )
    # Городской адрес без дома сопоставить нельзя.
    assert address_key("Москва") is None
    assert address_key("") is None


def test_615_summarize_addresses_aggregates_by_house():
    rows = [
        {"contract_number": "1", "start_date": date(2026, 7, 14), "initial_price": 1_000_000,
         "final_price": None, "is_waterproofing": True, "delivery_address": "Бестужевых ул. 21"},
        {"contract_number": "2", "start_date": date(2026, 8, 1), "initial_price": 500_000,
         "final_price": 400_000, "is_waterproofing": False, "delivery_address": "Бестужевых ул. 21"},
        {"contract_number": "3", "start_date": date(2026, 9, 1), "initial_price": 9_000_000,
         "final_price": None, "is_waterproofing": False, "delivery_address": "Москва"},
    ]
    from src.services.waterproofing_615 import build_index, year_overview

    index = build_index(rows)
    assert len(index) == 1
    slice_data = {"year": 2026, "index": index, "rows": rows, "overview": year_overview(rows, 2026)}
    summary = summarize_addresses(slice_data, [
        "Российская Федерация, город Москва, улица Бестужевых, дом 21",
        "Российская Федерация, город Москва, улица Бестужевых, дом 21",
    ])
    assert summary["tenders"] == 2
    assert summary["amount"] == pytest.approx(1_400_000.0)
    assert summary["waterproofing_tenders"] == 1
    assert summary["last_date"] == "2026-08-01"
    assert summary["has_tenders"] is True
    # Городской контракт без адреса дома в срез УК не попадает.
    assert slice_data["overview"]["tenders"] == 3

    empty = summarize_addresses(slice_data, ["Селигерская ул. 28"])
    assert empty["tenders"] == 0
    assert empty["has_tenders"] is False
    assert empty["amount_label"] == "—"


def test_615_matches_house_with_history_outside_current_year():
    from src.services.waterproofing_615 import build_index, year_overview

    rows = [
        {"contract_number": "old", "start_date": date(2023, 5, 4), "initial_price": 9_000_000,
         "final_price": None, "is_waterproofing": False,
         "delivery_address": "Селезневская ул. 13 с.1"},
        {"contract_number": "cur", "start_date": date(2026, 2, 1), "initial_price": 2_000_000,
         "final_price": None, "is_waterproofing": False, "delivery_address": "Реутовская ул. 16"},
    ]
    index = build_index(rows)
    slice_data = {"year": 2026, "index": index, "rows": rows, "overview": year_overview(rows, 2026)}
    summary = summarize_addresses(slice_data, [
        "Российская Федерация, город Москва, улица Селезневская, дом 13, строение 1",
    ])
    # Дом найден по истории, хотя в текущем году торгов по нему не было.
    assert summary["tenders"] == 0
    assert summary["history_tenders"] == 1
    assert summary["history_amount_label"] == "9 млн ₽"
    assert summary["history_last_date"] == "2023-05-04"
    assert summary["years"] == [2023]
    assert summary["has_tenders"] is True
    # Обзор программы считается только по текущему году.
    assert slice_data["overview"]["tenders"] == 1


def test_615_matches_by_house_number_and_street_words():
    from src.services.waterproofing_615 import build_index, year_overview

    rows = [
        {"contract_number": "1", "start_date": date(2026, 3, 1), "initial_price": 1_000_000,
         "final_price": None, "is_waterproofing": False,
         "delivery_address": "Полковника Романова ул. 5"},
    ]
    index = build_index(rows)
    slice_data = {"year": 2026, "index": index, "rows": rows, "overview": year_overview(rows, 2026)}
    summary = summarize_addresses(slice_data, [
        "Российская Федерация, Московская область, г.о. Мытищи, п Нагорное, "
        "ул Полковника Романова, д. 5",
    ])
    assert summary["matched_addresses"] == 1
    assert summary["history_tenders"] == 1
    # Посёлок в адресе НСПД не совпадает с адресом 615-ПП, поэтому совпадение приблизительное.
    assert summary["approximate_matches"] == 1
    assert summary["matches"][0]["confidence"].startswith("похожий адрес")


def test_615_rejects_same_house_number_on_another_street():
    from src.services.waterproofing_615 import build_index, year_overview

    rows = [
        {"contract_number": "1", "start_date": date(2026, 3, 1), "initial_price": 1_000_000,
         "final_price": None, "is_waterproofing": False, "delivery_address": "Реутовская ул. 16"},
    ]
    index = build_index(rows)
    slice_data = {"year": 2026, "index": index, "rows": rows, "overview": year_overview(rows, 2026)}
    summary = summarize_addresses(slice_data, ["Селигерская ул. 16"])
    assert summary["matched_addresses"] == 0
    assert summary["checked_addresses"] == 1
    assert summary["has_tenders"] is False


def test_build_card_uses_615_history_and_current_year():
    card = build_card(_uk_row(), None, tenders_615={
        "year": "2026", "tenders": 1, "amount": 2_000_000.0, "amount_label": "2 млн ₽",
        "history_tenders": 3, "history_amount": 30_000_000.0,
        "history_amount_label": "30 млн ₽", "history_last_date": "2025-07-28",
        "history_waterproofing_tenders": 1, "years": [2023, 2025, 2026],
        "matched_addresses": 1, "approximate_matches": 0, "has_tenders": True,
    })
    assert card["tenders_615_count"] == 3
    assert card["tenders_615_amount_label"] == "30 млн ₽"
    assert card["tenders_615_last_date"] == "2025-07-28"
    assert card["tenders_615_year_count"] == 1
    assert card["tenders_615_year_amount_label"] == "2 млн ₽"
    assert card["tenders_615_years"] == [2023, 2025, 2026]
    assert card["tenders_615_waterproofing"] == 1
