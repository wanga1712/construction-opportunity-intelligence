"""Read-only test of the DIRECT contour on a real procurement (S13)."""
import json
import os
import sys

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.db_bootstrap import connect_databases
from src.services.direct_document_extractor import build_tkp_request, load_direct_extraction
from src.services.procurement_card_dossier_service import load_procurement_dossier

PID = int(os.getenv("DIRECT_TEST_PID", "459631"))
OUT = os.getenv("DIRECT_TEST_OUT", "/tmp/direct_test_out.txt")


def main() -> int:
    lines = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text, flush=True)

    radar_db, tender_db, crm_db, warn = connect_databases()
    emit("db_warn=%s" % (warn or "-"))
    if crm_db is None:
        emit("crm_db=None -> abort")
        return 2

    ext = load_direct_extraction(PID)
    sections = ext.get("sections") or {}
    emit("pid=%s files=%s" % (PID, ext.get("files")))
    emit("tab_counts spec=%s tech=%s req=%s" % (
        len(ext.get("spec") or []), len(ext.get("tech") or []), len(ext.get("requirements") or [])))
    emit("sections=%s total=%s" % (
        {k: len(v or []) for k, v in sections.items()},
        sum(len(v or []) for v in sections.values())))

    for i, row in enumerate((ext.get("spec") or [])[:6]):
        emit("SPEC[%d]=%s" % (i, json.dumps(row, ensure_ascii=False)[:280]))

    dossier = load_procurement_dossier(crm_db, PID)
    ident = dossier.get("identity") or {}
    emit("dossier=%s" % json.dumps({k: ident.get(k) for k in
                                    ("id", "contract_number", "law", "crm_stage", "okpd_code")},
                                   ensure_ascii=False))
    emit("opps=%s docs=%s" % (len(dossier.get("opportunities") or []), len(dossier.get("documents") or [])))

    tkp = build_tkp_request(ext, dossier)
    emit("tkp_chars=%s tkp_lines=%s" % (len(tkp), tkp.count("\n") + 1))
    emit("--- TKP HEAD ---")
    emit(tkp[:1800])

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(tkp)
    emit("tkp_saved=%s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
