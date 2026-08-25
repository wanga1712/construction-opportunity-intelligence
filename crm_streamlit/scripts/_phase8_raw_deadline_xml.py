#!/usr/bin/env python3
"""Prove control 2032 deadline against S7/raw XML fields."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases


def snippets(text: str, needle: str, radius: int = 120) -> list[str]:
    out = []
    for m in re.finditer(re.escape(needle), text or "", flags=re.I):
        a = max(0, m.start() - radius)
        b = min(len(text), m.end() + radius)
        out.append(text[a:b].replace("\n", " "))
        if len(out) >= 8:
            break
    return out


def main() -> None:
    _, tender, crm, _ = connect_databases()
    out: dict = {}

    out["control_crm"] = crm.execute_query(
        """
        SELECT id, source_id, contract_number, start_date, end_date,
               source_updated_at, tender_link
        FROM crm_procurements WHERE id = 17758
        """
    )[0]

    out["s7_row"] = tender.execute_query(
        """
        SELECT id, contract_number, tender_link, start_date, end_date,
               delivery_start_date, delivery_end_date, updated_at
        FROM reestr_contract_223_fz WHERE id = 151355
        """
    )

    # discover xml-ish tables
    tabs = tender.execute_query(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (
            table_name ILIKE '%xml%'
            OR table_name ILIKE '%notice%'
            OR table_name ILIKE '%raw%'
            OR table_name ILIKE '%blob%'
            OR table_name ILIKE '%eis%'
            OR table_name ILIKE '%file%'
          )
        ORDER BY table_name
        """
    )
    out["candidate_tables"] = [t["table_name"] if isinstance(t, dict) else t[0] for t in tabs]

    # try common places for raw xml containing registration number
    reg = "32615833902"
    hits = []
    for table in out["candidate_tables"]:
        cols = tender.execute_query(
            f"""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        col_names = [
            (c["column_name"] if isinstance(c, dict) else c[0]) for c in cols
        ]
        textish = [
            c
            for c in col_names
            if any(x in c.lower() for x in ("xml", "content", "body", "raw", "text", "data", "payload"))
        ]
        if not textish and not any("xml" in c.lower() for c in col_names):
            continue
        probe_cols = textish or [c for c in col_names if "xml" in c.lower()]
        for col in probe_cols[:4]:
            try:
                rows = tender.execute_query(
                    f"""
                    SELECT {col} AS payload
                    FROM {table}
                    WHERE CAST({col} AS text) LIKE %s
                    LIMIT 1
                    """,
                    (f"%{reg}%",),
                )
            except Exception as exc:  # noqa: BLE001
                hits.append({"table": table, "col": col, "error": str(exc)[:200]})
                continue
            if not rows:
                continue
            payload = rows[0]["payload"] if isinstance(rows[0], dict) else rows[0][0]
            text = payload if isinstance(payload, str) else str(payload)
            hits.append(
                {
                    "table": table,
                    "col": col,
                    "len": len(text),
                    "has_submissionCloseDateTime": "submissionCloseDateTime" in text,
                    "has_deliveryEndDateTime": "deliveryEndDateTime" in text,
                    "has_2032": "2032" in text,
                    "submission_snips": snippets(text, "submissionCloseDateTime"),
                    "delivery_snips": snippets(text, "deliveryEndDateTime"),
                    "reg_snips": snippets(text, reg, 80),
                    "urlEIS_snips": snippets(text, "urlEIS"),
                    "registration_snips": snippets(text, "registrationNumber"),
                }
            )
            break
        if len(hits) >= 5:
            break

    out["xml_hits"] = hits

    # tag map authority if present in tendermonitor code on disk
    tag_paths = [
        Path("/opt/pythonProject89"),
        Path("/opt/CRM_Streamlit"),
    ]
    tag_evidence = []
    for root in tag_paths:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "submissionCloseDateTime" in txt or "deliveryEndDateTime" in txt or "urlEIS" in txt:
                if "end_date" in txt or "tender_link" in txt or "contract_number" in txt:
                    tag_evidence.append(
                        {
                            "path": str(p),
                            "has_submissionClose": "submissionCloseDateTime" in txt,
                            "has_deliveryEnd": "deliveryEndDateTime" in txt,
                            "has_urlEIS": "urlEIS" in txt,
                            "snips": [
                                line.strip()
                                for line in txt.splitlines()
                                if any(
                                    k in line
                                    for k in (
                                        "submissionCloseDateTime",
                                        "deliveryEndDateTime",
                                        "urlEIS",
                                        "registrationNumber",
                                        "end_date",
                                        "tender_link",
                                    )
                                )
                            ][:20],
                        }
                    )
            if len(tag_evidence) >= 8:
                break
        if len(tag_evidence) >= 8:
            break
    out["tag_code_evidence"] = tag_evidence

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
