#!/usr/bin/env python3
"""Read-only S13 acceptance for the Phase 2 annotation card redesign."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CRM_APP_ROOT", "/opt/CRM_Streamlit"))
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), os.environ.get("CRM_SOURCE_ROOT", "/opt/pythonProject89")]

from dotenv import load_dotenv
from streamlit.testing.v1 import AppTest

load_dotenv(ROOT / ".env", override=True)

from src.services.annotation_card_view import load_annotation_card_view
from src.services.annotation_queue_service import fetch_procurement_header
from src.services.db_bootstrap import connect_databases

PROCUREMENT_IDS = (1013, 8021, 17390, 20254, 20256)


def _app_test(procurement_id: int) -> dict:
    source = f"""
from src.services.db_bootstrap import connect_databases
from src.services.annotation_queue_service import fetch_procurement_header, lifecycle_label
from src.services.expert_annotation_service import load_expert_annotation, load_model_assessment_for_annotation
from src.ui.components.analytics_v2.annotation_card import render_annotation_card
_, _, crm_db, _ = connect_databases()
header = fetch_procurement_header(crm_db, {procurement_id})
render_annotation_card(
    crm_db=crm_db,
    procurement_id={procurement_id},
    header=header,
    assessment=load_model_assessment_for_annotation({procurement_id}, crm_db),
    existing_annotation=load_expert_annotation({procurement_id}, crm_db),
    publication_visible=True,
    lifecycle_label=lifecycle_label(header),
)
"""
    at = AppTest.from_string(source, default_timeout=180).run(timeout=180)
    tabs = [item.label for item in at.tabs]
    buttons = [item.label for item in at.button]
    link_buttons = [item.label for item in at.get("link_button")]
    metrics = {item.label: str(item.value) for item in at.metric}
    infos = [str(item.value) for item in at.info]
    return {
        "exceptions": [str(item.value) for item in at.exception],
        "tabs": tabs,
        "metrics": metrics,
        "procurement_link": "🔗 Открыть закупку" in link_buttons,
        "contract_link": "📄 Открыть контракт" in link_buttons,
        "document_links": link_buttons.count("Открыть / скачать документ"),
        "unobserved_messages": sum("Документ ещё не исследован" in item for item in infos),
        "fast_actions": {
            label: label in buttons
            for label in (
                "✓ ВЕРНО",
                "✕ НЕВЕРНО",
                "+ ДОБАВИТЬ ПРОПУЩЕННУЮ КАТЕГОРИЮ",
                "💾 SAVE & NEXT →",
                "⛔ НЕ НАШ ПРОФИЛЬ",
            )
        },
    }


def main() -> int:
    _, _, crm_db, _ = connect_databases()
    observation_count = int(
        crm_db.execute_query("SELECT count(*) AS n FROM crm_v3_document_observations")[0]["n"]
    )
    cases = []
    ok = observation_count == 0
    for procurement_id in PROCUREMENT_IDS:
        header = fetch_procurement_header(crm_db, procurement_id)
        view = load_annotation_card_view(procurement_id, header, crm_db)
        app = _app_test(procurement_id)
        facts = view["facts"]
        states = [row["observation_state"] for row in view["documents"]]
        expected_contract = facts["lifecycle"] == "AWARDED"
        case_ok = (
            not app["exceptions"]
            and len(app["tabs"]) == 5
            and any(label.startswith("Документы (") for label in app["tabs"])
            and app["procurement_link"]
            and app["contract_link"] == expected_contract
            and app["document_links"] == view["document_count"]
            and app["unobserved_messages"] == view["document_count"]
            and all(state == "UNOBSERVED" for state in states)
            and all(
                app["fast_actions"][label]
                for label in (
                    "+ ДОБАВИТЬ ПРОПУЩЕННУЮ КАТЕГОРИЮ",
                    "💾 SAVE & NEXT →",
                    "⛔ НЕ НАШ ПРОФИЛЬ",
                )
            )
            and app["fast_actions"]["✓ ВЕРНО"] == app["fast_actions"]["✕ НЕВЕРНО"]
            and set(("НМЦК" if facts["lifecycle"] == "OPEN" else "Цена контракта", "Закон / источник"))
            <= set(app["metrics"])
        )
        ok = ok and case_ok
        cases.append(
            {
                "procurement_id": procurement_id,
                "lifecycle": facts["lifecycle"],
                "law": facts["law"],
                "display_amount_label": facts["display_amount_label"],
                "display_amount": str(facts["display_amount"]),
                "deadline_label": facts["deadline_label"],
                "deadline": str(facts["deadline"]),
                "document_count": view["document_count"],
                "raw_document_rows": view["document_resolution"].get("raw_document_link_count"),
                "unobserved_count": states.count("UNOBSERVED"),
                "orphan_observations": len(view["orphan_observations"]),
                "procurement_link": app["procurement_link"],
                "contract_link": app["contract_link"],
                "tabs": app["tabs"],
                "fast_actions": app["fast_actions"],
                "exceptions": app["exceptions"],
                "pass": case_ok,
            }
        )
    out = {
        "audit_mode": "READ_ONLY",
        "production_observation_count": observation_count,
        "cases": cases,
        "pass": ok,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
