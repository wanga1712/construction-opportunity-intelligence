#!/usr/bin/env python3
"""AppTest: objects_v2 → Идут торги shows procurement number + public 223 link."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/opt/CRM_Streamlit")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/opt/pythonProject89")
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from streamlit.testing.v1 import AppTest
from src.services.db_bootstrap import connect_databases
from src.services.procurement_identity import resolve_procurement_link


def main() -> int:
    _, _, crm, _ = connect_databases()
    control = crm.execute_query(
        "SELECT id, contract_number, tender_link, source_table FROM crm_procurements WHERE id=17758"
    )[0]
    view = resolve_procurement_link(
        source_table=control["source_table"],
        contract_number=control["contract_number"],
        tender_link=control["tender_link"],
    )

    # Sample 5x44 + 5x223 open
    samples = crm.execute_query(
        """
        (
          SELECT id, source_table, contract_number, tender_link, '44' AS law
          FROM crm_procurements
          WHERE source_table ILIKE %s AND crm_stage='torgi'
            AND award_status='submission_open' AND end_date>=CURRENT_DATE
          ORDER BY end_date ASC, id DESC LIMIT 5
        )
        UNION ALL
        (
          SELECT id, source_table, contract_number, tender_link, '223' AS law
          FROM crm_procurements
          WHERE source_table ILIKE %s AND crm_stage='torgi'
            AND award_status='submission_open' AND end_date>=CURRENT_DATE
          ORDER BY end_date ASC, id DESC LIMIT 5
        )
        """,
        ("%44%", "%223%"),
    )
    sample_views = []
    for row in samples:
        v = resolve_procurement_link(
            source_table=row["source_table"],
            contract_number=row["contract_number"],
            tender_link=row["tender_link"],
        )
        sample_views.append(
            {
                "id": row["id"],
                "law": row["law"],
                "number": v.procurement_number,
                "public_url": v.public_url,
                "render": v.render_direct_link,
                "private_lk_rendered": bool(
                    v.render_direct_link and v.public_url and "lk.zakupki.gov.ru" in v.public_url
                ),
            }
        )

    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["nav_page"] = "objects_v2"
    at.run(timeout=180)
    # Prefer farthest sort so control 2032 card appears on first page if present in workset.
    text = " ".join(str(x.value) for x in list(at.markdown) + list(at.caption) + list(at.info))
    buttons = [b.label for b in at.button]
    out = {
        "exceptions": [str(e.value) for e in at.exception],
        "control_row": control,
        "control_view": {
            "number": view.procurement_number,
            "public_url": view.public_url,
            "render": view.render_direct_link,
            "validity": view.validity.value,
        },
        "control_private_lk_in_db": "lk.zakupki.gov.ru" in str(control.get("tender_link") or ""),
        "sample_views": sample_views,
        "sample_private_rendered": sum(1 for s in sample_views if s["private_lk_rendered"]),
        "ui_has_procurement_number_label": "№ закупки" in text or any("№ закупки" in b for b in buttons),
        "markdown_sample": text[:1200],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    ok = (
        not out["exceptions"]
        and view.procurement_number == "32615833902"
        and view.public_url
        and "regNumber=32615833902" in view.public_url
        and "lk.zakupki.gov.ru" not in (view.public_url or "")
        and out["sample_private_rendered"] == 0
        and not out["control_private_lk_in_db"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
