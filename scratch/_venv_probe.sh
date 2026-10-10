#!/bin/bash
VENV=/opt/tender_documents_research/.venv/bin/python
ls -l "$VENV" || exit 1
"$VENV" - <<'PY'
import importlib.util as u
for m in ("pdfplumber", "PyPDF2", "docx", "xlrd", "openpyxl", "pandas", "fitz", "rapidfuzz"):
    print("%-12s %s" % (m, bool(u.find_spec(m))))
PY
echo "--- repo link ---"
ls -ld /opt/tender_documents_research /opt/CRM_Streamlit/tender_documents_research
