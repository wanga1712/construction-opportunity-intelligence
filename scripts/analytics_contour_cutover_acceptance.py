#!/usr/bin/env python3
"""Read-only real-route S13 acceptance for analytics contour card cutover."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit"))
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]

from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

load_dotenv(ROOT / ".env", override=True)

from src.ui.components.analytics_v2 import annotation_card
from src.services.annotation_queue_service import fetch_procurement_header
from src.services.db_bootstrap import connect_databases
from src.ui.components.analytics_v2 import tabs as stage_tabs

REAL_CASES = {
    1013: ("selected_torgi_id", "Идут торги", "223-ФЗ", "НМЦК", "Документы (2)", False),
    8021: ("selected_komissia_id", "Комиссия", "44-ФЗ", "НМЦК", "Документы (170)", False),
    17390: ("selected_torgi_id", "Идут торги", "223-ФЗ", "НМЦК", "Документы (6)", False),
    20254: ("selected_razygr_id", "Разыгранные", "44-ФЗ", "Цена контракта", "Документы (2)", True),
    20256: ("selected_razygr_id", "Разыгранные", "44-ФЗ", "Цена контракта", "Документы (25)", True),
}


def _new(**state) -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=240)
    at.session_state["nav_page"] = "objects_v2"
    for key, value in state.items():
        at.session_state[key] = value
    return at.run(timeout=240)


def _state_get(at: AppTest, key: str, default=None):
    try:
        return at.session_state[key]
    except KeyError:
        return default


def _button(at: AppTest, *, key: str | None = None, label: str | None = None):
    for item in at.button:
        if key is not None and item.key == key:
            return item
        if label is not None and item.label == label:
            return item
    raise AssertionError(f"button not found: key={key!r} label={label!r}")


def _open_buttons(at: AppTest, session_key: str | None = None) -> list:
    prefix = f"open_stage_card_{session_key}_" if session_key else "open_stage_card_"
    return [item for item in at.button if str(item.key or "").startswith(prefix)]


def _pid_from_open_button(item) -> int:
    match = re.search(r"_(\d+)_\d+$", str(item.key))
    if not match:
        raise AssertionError(f"cannot parse procurement id from {item.key}")
    return int(match.group(1))


def _detail_snapshot(at: AppTest) -> dict:
    tabs = [item.label for item in at.tabs]
    links = [item.label for item in at.get("link_button")]
    metrics = {item.label: str(item.value) for item in at.metric}
    infos = [str(item.value) for item in at.info]
    buttons = [item.label for item in at.button]
    return {
        "exceptions": [str(item.value) for item in at.exception],
        "tabs": tabs,
        "links": links,
        "metrics": metrics,
        "unobserved": sum("Документ ещё не исследован" in text for text in infos),
        "save_next": "💾 SAVE & NEXT →" in buttons,
        "out_of_profile": "⛔ НЕ НАШ ПРОФИЛЬ" in buttons,
    }


def main() -> int:
    resolver_calls: list[int] = []
    real_loader = annotation_card.load_annotation_card_view

    def counted_loader(procurement_id, *args, **kwargs):
        resolver_calls.append(int(procurement_id))
        return real_loader(procurement_id, *args, **kwargs)

    annotation_card.load_annotation_card_view = counted_loader
    fake_saves: list[int] = []
    annotation_card.save_expert_annotation = lambda pid, *_args, **_kwargs: fake_saves.append(pid) or 900001
    annotation_card.write_audit_row = lambda **_kwargs: None

    landing = _new()
    stage_control = next(item for item in landing.radio if item.label == "Раздел")
    initial = stage_control.set_value("Идут торги").run(timeout=240)
    list_buttons = _open_buttons(initial)
    initial_resolver_calls = len(resolver_calls)
    list_visible = len(list_buttons) >= 2 and not landing.exception and not initial.exception

    # Actual click from the real list, then back to the same list/filter state.
    first = list_buttons[0]
    first_key = str(first.key)
    session_key = next(
        key for key in ("selected_torgi_id", "selected_komissia_id", "selected_razygr_id")
        if first_key.startswith(f"open_stage_card_{key}_")
    )
    filter_snapshot = {
        key: initial.session_state[key]
        for key in ("torgi_ai_filter", "torgi_qual_layer", "razygr_qual_layer")
        if key in initial.session_state
    }
    clicked = first.click().run(timeout=240)
    click_detail = _detail_snapshot(clicked)
    click_opens_new = (
        any(label.startswith("Документы (") for label in click_detail["tabs"])
        and "Экспертная разметка" in click_detail["tabs"]
        and len(resolver_calls) == initial_resolver_calls + 1
    )
    back = _button(clicked, key=f"back_to_stage_{session_key}").click().run(timeout=240)
    back_preserves = (
        session_key not in back.session_state
        and all(_state_get(back, key) == value for key, value in filter_snapshot.items())
        and bool(_open_buttons(back, session_key))
        and not back.exception
    )

    # SAVE & NEXT on a real filtered list; writes are in-memory fakes only.
    stage_buttons = _open_buttons(back, session_key)
    save_next_ok = False
    if len(stage_buttons) >= 2:
        current_id = _pid_from_open_button(stage_buttons[0])
        next_id = _pid_from_open_button(stage_buttons[1])
        detail = stage_buttons[0].click().run(timeout=240)
        advanced = _button(detail, label="💾 SAVE & NEXT →").click().run(timeout=240)
        save_next_ok = (
            _state_get(advanced, session_key) == next_id
            and fake_saves == [current_id]
            and "Экспертная разметка" in [item.label for item in advanced.tabs]
            and not advanced.exception
        )

    cases = []
    stage_loaders = {
        "selected_torgi_id": "_load_torgi",
        "selected_komissia_id": "_load_komissia",
        "selected_razygr_id": "_load_razygranye",
    }
    for procurement_id, (selected_key, active_stage, law, amount_label, docs_tab, contract_expected) in REAL_CASES.items():
        attempts = (
            ("Предварительно ИИ", "✓ Подтверждено")
            if selected_key in {"selected_torgi_id", "selected_razygr_id"}
            else (None,)
        )
        accepted = None
        for qualification in attempts:
            state = {selected_key: procurement_id, "analytics_v2_active_stage": active_stage}
            if qualification:
                state[
                    "razygr_qual_layer" if selected_key == "selected_razygr_id" else "torgi_qual_layer"
                ] = qualification
            candidate = _new(**state)
            if _state_get(candidate, selected_key) == procurement_id:
                accepted = candidate
                break
        route_membership = "CURRENT_STAGE_LIST"
        if accepted is None:
            _, _, crm_db, _ = connect_databases()
            header = fetch_procurement_header(crm_db, procurement_id) or {}
            loader_name = stage_loaders[selected_key]
            real_stage_loader = getattr(stage_tabs, loader_name)

            def with_real_row(_loader=real_stage_loader, _header=header):
                cards = _loader()
                if not any(card.get("id") == _header.get("id") for card in cards):
                    card = dict(_header)
                    card["is_confirmed"] = False
                    cards.append(card)
                return cards

            setattr(stage_tabs, loader_name, with_real_row)
            try:
                fixture_state = {
                    selected_key: procurement_id,
                    "analytics_v2_active_stage": active_stage,
                }
                if selected_key == "selected_torgi_id":
                    fixture_state["torgi_qual_layer"] = "Предварительно ИИ"
                elif selected_key == "selected_razygr_id":
                    fixture_state["razygr_qual_layer"] = "Предварительно ИИ"
                accepted = _new(**fixture_state)
            finally:
                setattr(stage_tabs, loader_name, real_stage_loader)
            route_membership = "IN_MEMORY_REAL_DB_ROW_FIXTURE"
            if _state_get(accepted, selected_key) != procurement_id:
                cases.append({
                    "procurement_id": procurement_id,
                    "pass": False,
                    "reason": "not renderable through stage fixture",
                    "current_crm_stage": header.get("crm_stage"),
                    "current_award_status": header.get("award_status"),
                    "current_end_date": str(header.get("end_date")),
                })
                continue
        snap = _detail_snapshot(accepted)
        contract_present = "📄 Открыть контракт" in snap["links"]
        case_ok = (
            not snap["exceptions"]
            and law in snap["metrics"].get("Закон / источник", "")
            and amount_label in snap["metrics"]
            and docs_tab in snap["tabs"]
            and "Обзор" in snap["tabs"]
            and "Модель / Категории" in snap["tabs"]
            and "История" in snap["tabs"]
            and "Экспертная разметка" in snap["tabs"]
            and "🔗 Открыть закупку" in snap["links"]
            and contract_present == contract_expected
            and snap["save_next"]
            and snap["out_of_profile"]
        )
        cases.append({
            "procurement_id": procurement_id,
            "route_membership": route_membership,
            **snap,
            "pass": case_ok,
        })

    # Reset from detail must clear selection and return list defaults.
    reset_start = _new(selected_torgi_id=1013, analytics_v2_active_stage="Идут торги")
    reset = _button(reset_start, label="Сбросить фильтры").click().run(timeout=240)
    reset_ok = (
        not any(key in reset.session_state for key in (
            "selected_torgi_id", "selected_komissia_id", "selected_razygr_id"
        ))
        and bool(_open_buttons(reset))
        and not reset.exception
    )

    ok = all((
        list_visible,
        initial_resolver_calls == 0,
        click_opens_new,
        back_preserves,
        save_next_ok,
        reset_ok,
        all(case.get("pass") for case in cases),
    ))
    out = {
        "audit_mode": "READ_ONLY_DB_WRITES_FAKE",
        "list_visible": list_visible,
        "list_open_button_count": len(list_buttons),
        "list_full_document_resolver_calls": initial_resolver_calls,
        "detail_full_document_resolver_calls": 1 if click_opens_new else len(resolver_calls),
        "click_opens_new_full_card": click_opens_new,
        "back_preserves_filters": back_preserves,
        "save_next_opens_next_filtered_card": save_next_ok,
        "fake_save_calls": fake_saves,
        "reset_returns_list": reset_ok,
        "initial_exceptions": [str(item.value) for item in landing.exception] + [str(item.value) for item in initial.exception],
        "cases": cases,
        "pass": ok,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
