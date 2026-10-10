import importlib.util

for mod in ("openpyxl", "xlrd", "PyPDF2", "pdfplumber", "docx", "fitz", "pandas"):
    print("%-12s %s" % (mod, bool(importlib.util.find_spec(mod))))
