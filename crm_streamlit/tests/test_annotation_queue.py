from src.ui.components.analytics_v2.annotation_queue import (
    GO_NEXT_FROM_KEY,
    GO_NEXT_KEY,
    bind_and_advance,
    next_id,
    rotate_to,
)


def _cards(*ids: int) -> list[dict]:
    return [{"id": pid} for pid in ids]


def test_next_id_advances_and_stops_at_end() -> None:
    ids = [10, 20, 30]
    assert next_id(ids, 10) == 20
    assert next_id(ids, 20) == 30
    assert next_id(ids, 30) is None
    assert next_id(ids, 99) is None


def test_rotate_to_puts_target_first_without_dropping_cards() -> None:
    cards = _cards(1, 2, 3, 4)
    rotated = rotate_to(cards, 3)
    assert [c["id"] for c in rotated] == [3, 4, 1, 2]


def test_bind_and_advance_consumes_flag_and_selects_next() -> None:
    session = {
        "selected_torgi_id": 1,
        GO_NEXT_KEY: True,
        GO_NEXT_FROM_KEY: 1,
    }
    cards = bind_and_advance(_cards(1, 2, 3), "selected_torgi_id", session)
    assert [c["id"] for c in cards] == [2, 3, 1]
    assert session["selected_torgi_id"] == 2
    assert GO_NEXT_KEY not in session
    assert GO_NEXT_FROM_KEY not in session


def test_bind_and_advance_noop_without_flag() -> None:
    session = {"selected_torgi_id": 1}
    cards = bind_and_advance(_cards(1, 2, 3), "selected_torgi_id", session)
    assert [c["id"] for c in cards] == [1, 2, 3]
    assert session["selected_torgi_id"] == 1


def test_stale_from_id_after_filter_change_is_consumed() -> None:
    session = {
        "selected_torgi_id": 9,
        GO_NEXT_KEY: True,
        GO_NEXT_FROM_KEY: 9,
    }
    cards = bind_and_advance(_cards(1, 2, 3), "selected_torgi_id", session)
    assert [c["id"] for c in cards] == [1, 2, 3]
    assert GO_NEXT_KEY not in session


def test_missing_id_can_be_left_for_another_list() -> None:
    session = {
        "selected_komissia_id": 4,
        GO_NEXT_KEY: True,
        GO_NEXT_FROM_KEY: 4,
    }
    waiting = bind_and_advance(
        _cards(1, 2),
        "selected_komissia_id",
        session,
        consume_if_missing=False,
    )
    assert [c["id"] for c in waiting] == [1, 2]
    assert session[GO_NEXT_KEY] is True
    not_found = bind_and_advance(_cards(3, 4), "selected_komissia_id", session)
    assert [c["id"] for c in not_found] == [4, 3]
    assert session["selected_komissia_id"] == 4
    assert GO_NEXT_KEY not in session


def test_current_card_stays_first_across_rerun() -> None:
    session = {"selected_torgi_id": 3}
    cards = bind_and_advance(_cards(1, 2, 3, 4), "selected_torgi_id", session)
    assert [c["id"] for c in cards] == [3, 4, 1, 2]


def test_expert_five_card_sequential_save_next() -> None:
    cards = _cards(1, 2, 3, 4, 5)
    session = {"selected_torgi_id": 1}
    seen = [session["selected_torgi_id"]]
    for _ in range(4):
        session[GO_NEXT_KEY] = True
        session[GO_NEXT_FROM_KEY] = session["selected_torgi_id"]
        cards = bind_and_advance(_cards(1, 2, 3, 4, 5), "selected_torgi_id", session)
        seen.append(session["selected_torgi_id"])
    assert seen == [1, 2, 3, 4, 5]
    assert [c["id"] for c in cards] == [5, 1, 2, 3, 4]
    session[GO_NEXT_KEY] = True
    session[GO_NEXT_FROM_KEY] = 5
    unchanged = bind_and_advance(_cards(1, 2, 3, 4, 5), "selected_torgi_id", session)
    assert session["selected_torgi_id"] == 5
    assert [c["id"] for c in unchanged] == [5, 1, 2, 3, 4]
