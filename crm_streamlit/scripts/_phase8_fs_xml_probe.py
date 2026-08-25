#!/usr/bin/env python3
"""Locate control notice XML + tag-map evidence for deadline/link fields."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path[:0] = ["/opt/CRM_Streamlit", "/opt/pythonProject89"]
from dotenv import load_dotenv

load_dotenv(Path("/opt/CRM_Streamlit/.env"), override=True)
from src.services.db_bootstrap import connect_databases

REG = "32615833902"
NOTICE_INFO = "19557278"


def extract_tag(text: str, tag: str) -> list[str]:
    pat = re.compile(
        rf"<(?:[\w]+:)?{re.escape(tag)}\b[^>]*>([^<]*)</(?:[\w]+:)?{re.escape(tag)}>",
        re.I,
    )
    return [m.group(1).strip() for m in pat.finditer(text or "")]


def main() -> None:
    out: dict = {"reg": REG, "notice_info_id": NOTICE_INFO}
    _, tender, crm, _ = connect_databases()

    # processed_files / file_names_xml probe
    for table in ("processed_files", "file_names_xml"):
        cols = tender.execute_query(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        out[f"{table}_cols"] = [
            ((c["column_name"] if isinstance(c, dict) else c[0]), (c["data_type"] if isinstance(c, dict) else c[1]))
            for c in cols
        ]

    # Search likely filesystem roots for reg number (bounded)
    roots = [
        "/opt/tendermonitor/data",
        "/var/lib/tendermonitor",
        "/data",
        "/opt/eis",
        "/home",
    ]
    found_files: list[str] = []
    for root in roots:
        if not Path(root).exists():
            continue
        try:
            proc = subprocess.run(
                ["rg", "-l", "--max-count", "1", REG, root],
                capture_output=True,
                text=True,
                timeout=120,
            )
            lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
            found_files.extend(lines[:20])
        except Exception as exc:  # noqa: BLE001
            out.setdefault("fs_errors", []).append({"root": root, "error": str(exc)[:200]})
    # fallback find+grep if rg missing
    if not found_files:
        for root in roots:
            if not Path(root).exists():
                continue
            try:
                proc = subprocess.run(
                    ["bash", "-lc", f"grep -RIl --include='*.xml' -m1 {REG} {root} 2>/dev/null | head -20"],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
                found_files.extend(lines[:20])
            except Exception as exc:  # noqa: BLE001
                out.setdefault("fs_errors", []).append({"root": root, "error": str(exc)[:200]})
    out["xml_files"] = found_files[:30]

    xml_parse = []
    for path in found_files[:5]:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            xml_parse.append({"path": path, "error": str(exc)[:200]})
            continue
        xml_parse.append(
            {
                "path": path,
                "len": len(text),
                "registrationNumber": extract_tag(text, "registrationNumber")[:5],
                "purchaseNoticeNumber": extract_tag(text, "purchaseNoticeNumber")[:5],
                "submissionCloseDateTime": extract_tag(text, "submissionCloseDateTime")[:5],
                "deliveryEndDateTime": extract_tag(text, "deliveryEndDateTime")[:5],
                "urlEIS": extract_tag(text, "urlEIS")[:5],
                "has_2032": "2032" in text,
                "has_noticeInfoId": NOTICE_INFO in text,
            }
        )
    out["xml_parse"] = xml_parse

    # Tag map code scan (bounded roots)
    code_hits = []
    for root in ("/opt/pythonProject89", "/opt/tendermonitor", "/opt/CRM_Streamlit"):
        p = Path(root)
        if not p.exists():
            continue
        for f in p.rglob("*.py"):
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "submissionCloseDateTime" not in txt and "deliveryEndDateTime" not in txt and "urlEIS" not in txt:
                continue
            if not any(k in txt for k in ("end_date", "tender_link", "contract_number", "TAGS", "tag_map", "xpath")):
                continue
            snips = [
                ln.strip()
                for ln in txt.splitlines()
                if any(
                    k in ln
                    for k in (
                        "submissionCloseDateTime",
                        "deliveryEndDateTime",
                        "urlEIS",
                        "registrationNumber",
                        "end_date",
                        "tender_link",
                        "contract_number",
                    )
                )
            ][:25]
            code_hits.append({"path": str(f), "snips": snips})
            if len(code_hits) >= 12:
                break
        if len(code_hits) >= 12:
            break
    out["code_hits"] = code_hits

    # CRM/S7 comparison for over365 quartet
    out["over365_crm"] = crm.execute_query(
        """
        SELECT id, source_id, contract_number, start_date, end_date, source_updated_at
        FROM crm_procurements
        WHERE id IN (17758, 17293, 18062, 17084)
        ORDER BY end_date DESC
        """
    )
    out["over365_s7"] = tender.execute_query(
        """
        SELECT id, contract_number, start_date, end_date, tender_link, updated_at
        FROM reestr_contract_223_fz
        WHERE id IN (151355, 150890, 151659, 150681)
           OR contract_number IN ('32615833902','32615857174','32615858025','32515489436')
        """
    )

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
