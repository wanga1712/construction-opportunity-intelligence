"""Unit tests for the object-level deal funnel and the two-funnel board.

Once a concrete object exists the unit of work stops being the УК and becomes
that object. These tests pin the deal journal, the object card, the five deal
columns and the board aggregation that keeps the two funnels apart.
"""
from datetime import date, timedelta

import pytest

from src.services import waterproofing_deals as deals
from src.services.waterproofing_board import (
    account_columns,
    account_kpis,
    apply_filters,
    dashboard_kpis,
    pipeline_amount,
    uk_district,
    uk_districts,
)
from src.services.waterproofing_crm import build_card
from src.services.waterproofing_funnel import (
    DEAL_STAGE_IDS,
    FUNNEL_ACCOUNT,
    FUNNEL_DEAL,
    coerce_stage,
)


def _object_row(**overrides):
    row = {
        "object_id": 42,
        "cadastral_number": "77:01:0001001:1001",
        "name": "Красная Пресня, 24",
        "address": "Красная Пресня, 24",
        "floors_underground": 2,
        "area_total": 5400,
    }
    row.update(overrides)
    return row


def _uk_row(**overrides):
    row = {
        "uk_name": "ГБУ «Жилищник Пресненского района»",
        "uk_inn": "7703012345",
        "uk_ogrn": "1157746000000",
    }
    row.update(overrides)
    return row


def test_deal_key_prefers_the_stable_object_identifiers():
    assert deals.deal_key(_object_row()) == "77:01:0001001:1001"
    assert deals.deal_key(_object_row(cadastral_number="")) == "42"
    assert deals.deal_key(_object_row(cadastral_number="", object_id="")) == "Красная Пресня, 24"
    assert deals.deal_key({"name": "Без адреса"}) == "Без адреса"
    assert deals.deal_key({}) == ""


def test_deal_journal_keeps_the_newest_state_per_object(tmp_path, monkeypatch):
    monkeypatch.setattr(deals, "_DEAL_PATH", tmp_path / "deal_states.jsonl")
    deals.save_deal_state("obj-1", {"stage": "survey"})
    deals.save_deal_state("obj-1", {"stage": "proposal", "potential_amount": 2_400_000})
    deals.save_deal_state("obj-2", {"stage": "survey"})
    states = deals.load_deal_states()
    assert set(states) == {"obj-1", "obj-2"}
    assert states["obj-1"]["stage"] == "proposal"
    assert deals.latest_deal_state("obj-1")["potential_amount"] == 2_400_000
    assert deals.latest_deal_state("missing") == {}


def test_merge_deal_state_inherits_the_previous_record(tmp_path, monkeypatch):
    monkeypatch.setattr(deals, "_DEAL_PATH", tmp_path / "deal_states.jsonl")
    deals.merge_deal_state("obj-1", {"stage": "survey", "next_action": "Выехать"})
    merged = deals.merge_deal_state("obj-1", {"stage": "proposal"})
    assert merged["stage"] == "proposal"
    assert merged["next_action"] == "Выехать"
    assert merged["key"] == "obj-1"
    assert merged["updated_at"] == date.today().isoformat()


def test_deal_journal_skips_malformed_lines(tmp_path, monkeypatch):
    path = tmp_path / "deal_states.jsonl"
    path.write_text(
        '{"key": "a", "stage": "survey"}\nnot json\n{"key": "a", "stage": "proposal"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(deals, "_DEAL_PATH", path)
    assert deals.load_deal_states()["a"]["stage"] == "proposal"


def test_deal_journal_of_an_absent_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(deals, "_DEAL_PATH", tmp_path / "missing.jsonl")
    assert deals.load_deal_states() == {}


def test_build_deal_card_merges_object_uk_and_state():
    card = deals.build_deal_card(
        _object_row(),
        _uk_row(),
        {
            "key": "77:01:0001001:1001",
            "stage": "proposal",
            "next_action": "Защитить техрешение",
            "next_action_date": "2026-10-08",
            "responsible": "Петров",
            "priority": "Gold",
            "potential_amount": "2,4 млн",
            "survey_date": "2026-09-26",
        },
    )
    assert card["name"] == "Красная Пресня, 24"
    assert card["address"] == "Красная Пресня, 24"
    assert card["cadastral_number"] == "77:01:0001001:1001"
    assert card["floors_underground"] == 2
    assert card["uk_key"] == "1157746000000"
    assert card["uk_name"] == "ГБУ «Жилищник Пресненского района»"
    assert card["uk_name_short"] == "ГБУ «Жилищник Пресненского района»"
    assert card["stage"] == "proposal"
    assert card["stage_label"] == "КП / Техрешение"
    assert card["stage_description"] == "Готовится и защищается КП с техническим решением"
    assert card["stage_index"] == 1
    assert card["survey_date"] == "2026-09-26"
    assert card["potential_amount"] == pytest.approx(2_400_000.0)
    assert card["potential_amount_label"] == "2.4 млн ₽"
    assert card["priority"] == "Gold"
    assert card["priority_icon"] == "🥇"
    assert card["next_action"] == "Защитить техрешение"
    assert card["next_action_date"] == "2026-10-08"
    assert card["responsible"] == "Петров"
    assert card["in_work"] is True
    assert card["overdue"] is False


def test_build_deal_card_defaults_without_saved_state():
    card = deals.build_deal_card(_object_row(floors_underground=0), _uk_row())
    assert card["key"] == "77:01:0001001:1001"
    assert card["stage"] == DEAL_STAGE_IDS[0] == "survey"
    assert card["stage_label"] == "Обследование"
    assert card["stage_index"] == 0
    assert card["next_action"] == "Зафиксировать дефекты, фото и типы протечек"
    assert card["responsible"] == "—"
    assert card["in_work"] is False
    assert card["potential_amount_label"] == "—"
    assert card["priority"] == "Bronze"
    assert card["survey_date"] == ""
    assert card["overdue"] is False


def test_build_deal_card_never_shows_an_account_stage():
    card = deals.build_deal_card(_object_row(), _uk_row(), {"key": "k", "stage": "new"})
    assert card["stage"] == "survey"
    assert coerce_stage("followup", FUNNEL_DEAL) == "survey"
    assert coerce_stage("contract", FUNNEL_ACCOUNT) == "survey_approved"


def test_build_deal_card_priority_heuristic_uses_underground_floors():
    gold = deals.build_deal_card(_object_row(floors_underground=10), _uk_row())
    silver = deals.build_deal_card(_object_row(floors_underground=4), _uk_row())
    bronze = deals.build_deal_card(_object_row(floors_underground=1), _uk_row())
    assert (gold["priority"], silver["priority"], bronze["priority"]) == (
        "Gold", "Silver", "Bronze",
    )


def test_deal_card_reports_overdue_from_its_next_touch():
    past = (date.today() - timedelta(days=3)).isoformat()
    future = (date.today() + timedelta(days=4)).isoformat()
    card = deals.build_deal_card(
        _object_row(), _uk_row(), {"key": "k", "stage": "survey", "next_action_date": past}
    )
    assert card["overdue"] is True
    assert card["overdue_days"] >= 3

    on_time = deals.build_deal_card(
        _object_row(), _uk_row(),
        {"key": "k", "stage": "survey", "next_action_date": future},
    )
    assert on_time["overdue"] is False


def test_deal_sort_key_puts_overdue_first_then_priority_then_date():
    cards = [
        {"name": "B", "overdue": False, "priority": "Gold", "next_action_date": "2026-10-05"},
        {"name": "A", "overdue": False, "priority": "Bronze", "next_action_date": "2026-09-30"},
        {"name": "C", "overdue": True, "priority": "Bronze", "next_action_date": "2026-09-01"},
        {"name": "D", "overdue": False, "priority": "Gold", "next_action_date": ""},
    ]
    ordered = [card["name"] for card in sorted(cards, key=deals.deal_sort_key)]
    assert ordered == ["C", "B", "D", "A"]


def test_deal_columns_group_objects_into_five_deal_stages():
    cards = [
        deals.build_deal_card(
            _object_row(cadastral_number="a"), _uk_row(),
            {"key": "a", "stage": "survey", "potential_amount": 1_000_000},
        ),
        deals.build_deal_card(
            _object_row(cadastral_number="b"), _uk_row(),
            {"key": "b", "stage": "procurement", "potential_amount": 2_000_000},
        ),
        deals.build_deal_card(
            _object_row(cadastral_number="c"), _uk_row(),
            {"key": "c", "stage": "proposal", "potential_amount": 500_000},
        ),
        deals.build_deal_card(
            _object_row(cadastral_number="d"), _uk_row(),
            {"key": "d", "stage": "Согласование / ТЗ / торги"},
        ),
    ]
    columns = deals.deal_columns(cards)
    assert [column["stage"] for column in columns] == list(DEAL_STAGE_IDS)
    assert [column["label"] for column in columns] == [
        "Обследование", "КП / Техрешение", "Подготовка ТЗ", "Торги / Закупка", "Контракт / Работы",
    ]
    by_stage = {column["stage"]: column for column in columns}
    assert by_stage["survey"]["count"] == 1
    assert by_stage["proposal"]["count"] == 1
    assert by_stage["specification"]["count"] == 1
    assert by_stage["procurement"]["count"] == 1
    assert by_stage["contract"]["count"] == 0
    assert by_stage["proposal"]["amount_label"] == "500 тыс ₽"
    assert by_stage["procurement"]["amount_label"] == "2 млн ₽"
    assert by_stage["contract"]["amount_label"] == "—"


def test_deal_kpis_count_every_card_that_reached_a_stage():
    cards = [
        {"stage": "survey", "stage_index": 0, "potential_amount": 100_000},
        {"stage": "survey", "stage_index": 0, "potential_amount": 0},
        {"stage": "proposal", "stage_index": 1, "potential_amount": 200_000},
        {"stage": "procurement", "stage_index": 3, "potential_amount": 400_000},
        {"stage": "contract", "stage_index": 4, "potential_amount": 800_000, "overdue": True},
    ]
    kpi = deals.deal_kpis(cards)
    assert kpi["deals"] == 5
    assert kpi["survey"] == 5
    assert kpi["proposal"] == 3
    assert kpi["procurement"] == 2
    assert kpi["contract"] == 1
    assert kpi["overdue"] == 1
    assert kpi["amount"] == pytest.approx(1_500_000.0)
    assert kpi["amount_label"] == "1.5 млн ₽"


def test_account_columns_keep_the_account_funnel_and_coerce_foreign_stages():
    accounts = [
        build_card(_uk_row(uk_ogrn="1"), {"key": "1", "stage": "new"}),
        build_card(_uk_row(uk_ogrn="2"), {"key": "2", "stage": "Обследование проведено"}),
        build_card(_uk_row(uk_ogrn="3"), {"key": "3", "stage": "contract"}),
    ]
    columns = account_columns(accounts)
    assert [column["stage"] for column in columns] == [
        "new", "meeting", "followup", "survey_approved",
    ]
    by_stage = {column["stage"]: column for column in columns}
    assert by_stage["new"]["count"] == 1
    assert by_stage["meeting"]["count"] == 0
    assert by_stage["survey_approved"]["count"] == 2


def test_account_kpis_skip_closed_contours():
    cards = [
        build_card(
            _uk_row(uk_ogrn="1", object_count=3, parking_count=2, total_underground_floors=5),
            {
                "key": "1",
                "stage": "new",
                "potential_amount": 1_000_000,
                "exploitation_contact": "Иванов И.И.",
            },
        ),
        build_card(
            _uk_row(uk_ogrn="2", object_count=1, parking_count=1, total_underground_floors=1),
            {"key": "2", "stage": "closed", "potential_amount": 9_000_000},
        ),
    ]
    kpi = account_kpis(cards)
    assert kpi["accounts"] == 1
    assert kpi["objects"] == 3
    assert kpi["parkings"] == 2
    assert kpi["underground_floors"] == 5
    assert kpi["municipal"] == 1
    assert kpi["with_tech_contact"] == 1
    assert kpi["overdue"] == 0
    assert kpi["amount"] == pytest.approx(1_000_000.0)


def test_pipeline_amount_counts_uk_money_once():
    accounts = [
        build_card(_uk_row(uk_ogrn="1"), {"key": "1", "potential_amount": 5_000_000}),
        build_card(_uk_row(uk_ogrn="2"), {"key": "2", "potential_amount": 3_000_000}),
    ]
    assert pipeline_amount(accounts, []) == pytest.approx(8_000_000.0)

    object_deals = [
        deals.build_deal_card(
            _object_row(cadastral_number="a"), _uk_row(uk_ogrn="1"),
            {"key": "a", "stage": "survey", "potential_amount": 2_000_000},
        ),
    ]
    # УК №1 already has an object estimate, so its own УК-level estimate is not added again.
    assert pipeline_amount(accounts, object_deals) == pytest.approx(5_000_000.0)


def test_dashboard_kpis_is_a_compact_real_data_strip():
    accounts = [
        build_card(_uk_row(uk_ogrn="1", object_count=2), {"key": "1", "stage": "new"}),
    ]
    object_deals = [
        deals.build_deal_card(
            _object_row(), _uk_row(uk_ogrn="1"),
            {"key": "a", "stage": "proposal", "potential_amount": 2_000_000},
        ),
    ]
    kpi = dashboard_kpis(accounts, object_deals)
    assert [chip["label"] for chip in kpi] == [
        "УК в работе", "Объектов", "Обследований", "КП выдано", "В закупке", "Сумма pipeline",
    ]
    values = {chip["label"]: chip["value"] for chip in kpi}
    assert values["УК в работе"] == "1"
    assert values["Объектов"] == "2"
    assert values["КП выдано"] == "1"
    assert values["В закупке"] == "0"
    assert values["Сумма pipeline"] == "2 млн ₽"


def test_uk_district_reads_the_district_out_of_the_name_only():
    assert uk_district({"uk_name": "ГБУ «Жилищник района Хамовники»"}) == "Хамовники"
    assert uk_district({"uk_name": "ГБУ «Жилищник Пресненского района»"}) == "Пресненского"
    assert uk_district({"uk_name": "ООО «УК Тест»"}) == ""
    assert uk_districts(
        [
            {"uk_name": "ГБУ «Жилищник района Хамовники»"},
            {"uk_name": "ГБУ «Жилищник района Хамовники»"},
            {"uk_name": "ООО «УК Тест»"},
        ]
    ) == ["Хамовники"]


def _cards_for_filters():
    return [
        build_card(
            _uk_row(uk_ogrn="1", uk_name="ГБУ «Жилищник района Хамовники»"),
            {
                "key": "1",
                "stage": "meeting",
                "responsible": "Петров",
                "next_action_date": (date.today() - timedelta(days=2)).isoformat(),
            },
        ),
        build_card(
            _uk_row(uk_ogrn="2", uk_name="ООО «УК Тест»"),
            {
                "key": "2",
                "stage": "Первичный звонок",
                "responsible": "Сидоров",
                "next_action_date": (date.today() + timedelta(days=5)).isoformat(),
            },
        ),
    ]


def test_apply_filters_search_stage_district_and_responsible():
    cards = _cards_for_filters()
    district = uk_district
    search = ("uk_name", "uk_name_short", "uk_inn")
    assert len(apply_filters(cards, {}, district_of=district, search_fields=search)) == 2
    assert len(apply_filters(cards, {"query": "тест"}, district_of=district, search_fields=search)) == 1
    assert len(apply_filters(cards, {"stage": "meeting"}, district_of=district)) == 1
    # A legacy saved label still matches the canonical stage filter.
    assert len(apply_filters(cards, {"stage": "new"}, district_of=district)) == 1
    assert len(apply_filters(cards, {"district": "Хамовники"}, district_of=district)) == 1
    assert len(apply_filters(cards, {"responsible": "Петров"}, district_of=district)) == 1
    # «Все ...» means «no restriction», it is not a district or a manager name.
    assert len(apply_filters(cards, {"district": "Все районы"}, district_of=district)) == 2
    assert len(apply_filters(cards, {"responsible": "Все менеджеры"}, district_of=district)) == 2


def test_apply_filters_overdue_and_active_only_predicates():
    cards = _cards_for_filters()
    overdue = apply_filters(cards, {"overdue": True})
    assert [card["key"] for card in overdue] == ["1"]

    in_work = apply_filters(cards, {"active_only": True}, active_of=lambda card: card["in_work"])
    assert {card["key"] for card in in_work} == {"1", "2"}

    none_active = apply_filters(cards, {"active_only": True}, active_of=lambda card: False)
    assert none_active == []
