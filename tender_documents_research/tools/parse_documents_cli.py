"""Разбор документов закупки в JSON (таблицы + строки) для DIRECT-контура CRM.

Запускается интерпретатором ВОРКЕРНОГО venv (`/opt/tender_documents_research/.venv/bin/python`):
pdfplumber / python-docx / openpyxl есть только там, а карточка закупки крутится в CRM-venv,
где этих библиотек нет. Только чтение: ничего не пишет в БД и не меняет файлы.

usage: python parse_documents_cli.py [--out result.json] <path> [<path> ...]
Результат: {"ok": true, "docs": {"<path>": {"tables": [[[cell]]], "lines": [str], "error": null}}}
Пишем в файл (--out), потому что логи парсеров идут в stdout и мешают машинному чтению.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

MAX_TABLES = 60
MAX_ROWS = 400
MAX_LINE = 600
MAX_LINES = 4000


def _clean(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())[:MAX_LINE]


def _pdf(path: str):
    import pdfplumber

    tables = []
    lines: list = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if len(lines) < MAX_LINES:
                try:
                    text = page.extract_text() or ""
                except Exception:  # noqa: BLE001
                    text = ""
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        lines.append(line[:MAX_LINE])
                    if len(lines) >= MAX_LINES:
                        break
            if len(tables) < MAX_TABLES:
                try:
                    page_tables = page.extract_tables() or []
                except Exception:  # noqa: BLE001
                    page_tables = []
                for table in page_tables:
                    rows = [[_clean(cell) for cell in (row or [])] for row in (table or [])]
                    rows = [row for row in rows if any(row)]
                    if rows:
                        tables.append(rows[:MAX_ROWS])
                    if len(tables) >= MAX_TABLES:
                        break
            if len(lines) >= MAX_LINES and len(tables) >= MAX_TABLES:
                break
    return tables, lines


def _docx(path: str):
    import docx

    document = docx.Document(path)
    tables = []
    for table in document.tables[:MAX_TABLES]:
        rows = [[_clean(cell.text) for cell in row.cells] for row in table.rows]
        rows = [row for row in rows if any(row)]
        if rows:
            tables.append(rows[:MAX_ROWS])
    lines = [text.strip() for text in (p.text for p in document.paragraphs) if text.strip()]
    return tables, lines[:MAX_LINES]


def _xlsx(path: str):
    from openpyxl import load_workbook

    tables = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets[:MAX_TABLES]:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [_clean(value) for value in row]
                if any(cells):
                    rows.append(cells)
                if len(rows) >= MAX_ROWS:
                    break
            if rows:
                tables.append(rows)
    finally:
        workbook.close()
    return tables, []


def _doc_text(path: str) -> list:
    from document_processor.parsers.doc_parser import DocParser

    text = DocParser().parse(Path(path)) or ""
    return [line.strip() for line in text.splitlines() if line.strip()][:MAX_LINES]


def _soffice_convert(path: str, target: str, timeout: int = 240):
    """Конвертация legacy-формата (.doc/.xls) через LibreOffice. Возвращает путь или None."""
    outdir = tempfile.mkdtemp(prefix="lo_convert_")
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    try:
        subprocess.run(
            ["soffice", "--headless", "--norestore", "--nolockcheck", "--nodefault",
             "-env:UserInstallation=file://%s" % profile,
             "--convert-to", target, "--outdir", outdir, path],
            capture_output=True, timeout=timeout, check=False,
        )
        produced = sorted(Path(outdir).glob("*.%s" % target))
        if not produced:
            return None, None
        keep = tempfile.mkdtemp(prefix="lo_out_")
        moved = Path(keep) / produced[0].name
        shutil.move(str(produced[0]), str(moved))
        return str(moved), keep
    except Exception:  # noqa: BLE001
        return None, None
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)


def _doc_binary(path: str):
    """Старый .doc: сначала конвертация в .docx (сохраняет таблицы), потом текст."""
    converted, tmpdir = _soffice_convert(path, "docx")
    if converted:
        try:
            return _docx(converted)
        finally:
            shutil.rmtree(tmpdir or "", ignore_errors=True)
            Path(converted).unlink(missing_ok=True)
    return [], _doc_text(path)


def _xls_binary(path: str):
    """Старый .xls: конвертация в .xlsx (openpyxl его не читает)."""
    converted, tmpdir = _soffice_convert(path, "xlsx")
    if converted:
        try:
            return _xlsx(converted)
        finally:
            shutil.rmtree(tmpdir or "", ignore_errors=True)
            Path(converted).unlink(missing_ok=True)
    return [], []


def parse_one(path: str) -> dict:
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".pdf":
            tables, lines = _pdf(path)
        elif suffix == ".docx":
            tables, lines = _docx(path)
        elif suffix in (".xlsx", ".xlsm"):
            tables, lines = _xlsx(path)
        elif suffix == ".doc":
            tables, lines = _doc_binary(path)
        elif suffix == ".xls":
            tables, lines = _xls_binary(path)
        else:
            return {"tables": [], "lines": [], "error": "unsupported:%s" % suffix}
    except Exception as exc:  # noqa: BLE001
        return {"tables": [], "lines": [], "error": "%s: %s" % (type(exc).__name__, exc)}
    return {"tables": tables, "lines": lines, "error": None}


def main(argv: list) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    args = argv[1:]
    out_path = None
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 < len(args):
            out_path = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
    log_buffer = StringIO()
    docs = {}
    with redirect_stdout(log_buffer):
        for path in [p for p in args if p]:
            docs[path] = parse_one(path) if Path(path).exists() else {
                "tables": [], "lines": [], "error": "missing"}
    payload = json.dumps({"ok": True, "docs": docs}, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
