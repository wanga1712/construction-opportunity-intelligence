"""DIRECT-экстрактор: смета / техпараметры / требования из документов закупки.

.docx и .xlsx/.xlsm читаются как zip + XML (stdlib, работает в CRM-venv).
.pdf/.doc разбираются воркерным venv через tools/parse_documents_cli.py
(pdfplumber/python-docx есть только там) с дисковым кэшем — файлы удаляются
retention'ом, поэтому разбор нужно помнить. Никаких записей в БД: только чтение.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import zipfile
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import psycopg2
import psycopg2.extras

logger = logging.getLogger("crm.direct_extractor")

_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_MAX_ROWS = 400
#: Служебные файлы Word/Excel и подписи — не документы закупки.
_SKIP_PREFIXES = ("~$",)
_SKIP_SUFFIXES = (".sig", ".sign", ".cer", ".dbf", ".dwg", ".cdr", ".jpg", ".png")


def _is_junk(path: str) -> bool:
    name = os.path.basename(path or "").lower()
    return name.startswith(_SKIP_PREFIXES) or name.endswith(_SKIP_SUFFIXES)


def _cell_text(cell: ET.Element) -> str:
    parts = [t.text or "" for t in cell.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _docx_tables(path: str) -> List[List[List[str]]]:
    """Все таблицы документа: [таблица][строка][ячейка]."""
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as fh:
                root = ET.parse(fh).getroot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("docx read failed %s: %s", path, exc)
        return []
    tables = []
    for tbl in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"):
        rows = []
        for tr in tbl.findall("w:tr", _NS):
            cells = [_cell_text(tc) for tc in tr.findall("w:tc", _NS)]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows[:_MAX_ROWS])
    return tables


def _docx_paragraphs(path: str) -> List[str]:
    """Все абзацы документа (в т.ч. внутри таблиц), по порядку."""
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as fh:
                root = ET.parse(fh).getroot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("docx paragraphs failed %s: %s", path, exc)
        return []
    out = []
    for par in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = re.sub(
            r"\s+", " ",
            " ".join(t.text or "" for t in par.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")),
        ).strip()
        if text:
            out.append(text)
    return out


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_tables(path: str) -> List[List[List[str]]]:
    """Таблицы всех листов .xlsx/.xlsm без внешних библиотек: [лист][строка][ячейка]."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            shared: List[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall(_XLSX_NS + "si"):
                    shared.append("".join(t.text or "" for t in si.iter(_XLSX_NS + "t")))
            sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
            tables: List[List[List[str]]] = []
            for sheet in sheets:
                root = ET.fromstring(zf.read(sheet))
                rows: List[List[str]] = []
                for row in root.iter(_XLSX_NS + "row"):
                    cells: List[str] = []
                    for c in row.findall(_XLSX_NS + "c"):
                        kind = c.get("t")
                        value = c.find(_XLSX_NS + "v")
                        if kind == "s" and value is not None and (value.text or "").isdigit():
                            idx = int(value.text)
                            text = shared[idx] if idx < len(shared) else ""
                        elif kind == "inlineStr":
                            text = "".join(x.text or "" for x in c.iter(_XLSX_NS + "t"))
                        else:
                            text = (value.text if value is not None else "") or ""
                        cells.append(re.sub(r"\s+", " ", text).strip())
                    if any(cells):
                        rows.append(cells)
                    if len(rows) >= _MAX_ROWS:
                        break
                if rows:
                    tables.append(rows)
            return tables
    except Exception as exc:  # noqa: BLE001
        logger.warning("xlsx read failed %s: %s", path, exc)
        return []


def _tables_for(path: str) -> List[List[List[str]]]:
    lower = path.lower()
    if lower.endswith(".docx"):
        return _docx_tables(path)
    if lower.endswith((".xlsx", ".xlsm")):
        return _xlsx_tables(path)
    return []


#: Форматы, которые разбирает воркерный venv (pdfplumber/python-docx), а не CRM-venv.
_EXTERNAL_SUFFIXES = (".pdf", ".doc", ".xls")
_PARSE_CLI = os.getenv("DIRECT_PARSE_CLI", "/opt/tender_documents_research/tools/parse_documents_cli.py")
_PARSE_PY = os.getenv("DIRECT_PARSE_PY", "/opt/tender_documents_research/.venv/bin/python")
_PARSE_TIMEOUT = int(os.getenv("DIRECT_PARSE_TIMEOUT", "180"))
_PARSE_CACHE = os.getenv("DIRECT_PARSE_CACHE", "/var/cache/crm_direct_parse")
#: Версия логики внешнего разбора — входит в ключ кэша (иначе держатся устаревшие результаты).
_PARSE_VERSION = "2"


def _cache_file(path: str) -> str:
    try:
        stat = os.stat(path)
        key = "v%s|%s|%s|%s" % (_PARSE_VERSION, path, stat.st_size, stat.st_mtime_ns)
    except OSError:
        key = "v%s|%s" % (_PARSE_VERSION, path)
    name = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest() + ".json"
    return os.path.join(_PARSE_CACHE, name)


def _cache_read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_file(path), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _cache_write(path: str, doc: Dict[str, Any]) -> None:
    if doc.get("error"):
        return
    try:
        os.makedirs(_PARSE_CACHE, exist_ok=True)
        with open(_cache_file(path), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        logger.debug("parse cache write skipped for %s", path)


def _local_doc(path: str) -> Dict[str, Any]:
    """Разбор файла средствами CRM-venv (.docx/.xlsx) в общий формат."""
    lines = _docx_paragraphs(path) if path.lower().endswith(".docx") else []
    return {"tables": _tables_for(path), "lines": lines, "error": None}


def _external_docs(local_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Таблицы/строки по всем документам с дисковым кэшем (переживает retention).

    pdf/doc/xls разбирает воркерный venv, .docx/.xlsx — здесь же; результат кэшируется,
    поэтому после удаления файлов разобранные данные остаются доступны.
    """
    out: Dict[str, Dict[str, Any]] = {}
    pending: List[str] = []
    for path in local_paths:
        if not path or _is_junk(path):
            continue
        cached = _cache_read(path)
        if cached is not None:
            out[path] = cached
            continue
        if not os.path.exists(path):
            continue
        if path.lower().endswith(_EXTERNAL_SUFFIXES):
            pending.append(path)
        else:
            doc = _local_doc(path)
            out[path] = doc
            _cache_write(path, doc)
    if not pending or not os.path.exists(_PARSE_PY) or not os.path.exists(_PARSE_CLI):
        return out
    import tempfile

    handle, out_path = tempfile.mkstemp(prefix="direct_parse_", suffix=".json")
    os.close(handle)
    try:
        subprocess.run([_PARSE_PY, _PARSE_CLI, "--out", out_path] + pending,
                       capture_output=True, timeout=_PARSE_TIMEOUT, check=False)
        with open(out_path, "r", encoding="utf-8") as fh:
            payload = json.loads(fh.read() or "{}")
        docs = payload.get("docs") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("external document parse failed: %s", exc)
        return out
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
    for path in pending:
        doc = docs.get(path) or {"tables": [], "lines": [], "error": "no_output"}
        out[path] = doc
        _cache_write(path, doc)
    return out


#: Явные подписи срока — строка остаётся кандидатом даже без разобранной даты.
_TERM_STRONG = ("срок поставки", "сроки поставки", "срок исполнения", "срок оказания услуг",
                "срок выполнения работ", "срок передачи товара", "сроки исполнения")
#: Косвенные формулировки — берём только если в строке разобралась дата или длительность.
_TERM_WEAK = ("поставка товара осуществляется", "поставка осуществляется",
              "поставка товара производится", "товар поставляется")
#: Ложные срабатывания — это не срок поставки.
_TERM_SKIP = ("срок действия", "срок годности", "срок гарант", "гарантийн", "срок оплаты",
              "срок рассмотрения", "срок предоставления обеспеч", "срок возврата",
              "срок подписания", "срок размещения", "срок направления", "срок действия договора",
              # ссылки на нормы — это не срок поставки конкретной закупки
              "статье", "статьи", "статьей", "федерального закона", "фз №", "кодекса", "гк рф")
_MONTHS = (("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("май", 5),
           ("июн", 6), ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10),
           ("ноябр", 11), ("декабр", 12))
_ANCHORS = ("с даты подписания", "с момента подписания", "с даты заключения",
            "с момента заключения", "с даты поставки", "с момента поставки",
            "со дня подписания", "со дня заключения", "с даты вступления")


def _parse_term_dates(text: str) -> Dict[str, Any]:
    """Детерминированно вытащить срок из формулировки: дата, длительность, точка отсчёта."""
    low = re.sub(r"\s+", " ", text).lower()
    compact = re.sub(r"\s+", "", low)
    result: Dict[str, Any] = {"deadline": None, "duration_value": None,
                              "duration_unit": None, "anchor": None}
    numeric = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", compact)
    if numeric:
        day, month, year = (int(part) for part in numeric.groups())
        if year < 100:
            year += 2000
        if 1 <= day <= 31 and 1 <= month <= 12:
            result["deadline"] = "%04d-%02d-%02d" % (year, month, day)
    if not result["deadline"]:
        worded = re.search(r"(\d{1,2})([а-яё]{3,})(\d{4})", compact)
        if worded:
            for stem, month in _MONTHS:
                if worded.group(2).startswith(stem):
                    result["deadline"] = "%04d-%02d-%02d" % (
                        int(worded.group(3)), month, int(worded.group(1)))
                    break
    duration = re.search(
        r"(?:в течение|не позднее чем через|в срок)(\d{1,3})(?:\([^)]*\))?"
        r"(календарн\w*|рабоч\w*)?(дн\w+|месяц\w+|год\w+|лет)", compact)
    if duration and not result["deadline"]:
        unit = duration.group(3)
        result["duration_value"] = int(duration.group(1))
        result["duration_unit"] = "месяцев" if unit.startswith(("месяц", "лет", "год")) else "дней"
        if duration.group(2):
            result["duration_unit"] = ("%s %s" % (duration.group(2), result["duration_unit"])).strip()
    for anchor in _ANCHORS:
        if anchor in low:
            result["anchor"] = anchor
            break
    return result


def extract_delivery_terms(local_paths: List[str],
                           external: Optional[Dict[str, Dict[str, Any]]] = None
                           ) -> List[Dict[str, Any]]:
    """Строки документов о сроке поставки/исполнения (сырьё для модели-нормализатора)."""
    found: List[Dict[str, Any]] = []
    seen: set = set()
    for path in local_paths:
        if not path or _is_junk(path):
            continue
        doc = (external or {}).get(path)
        if doc is None and not os.path.exists(path):
            continue
        lines = [str(x) for x in ((doc or {}).get("lines") or [])]
        if not lines:
            lines = _paragraphs_for(path, external)
        if not lines and path.lower().endswith(".docx") and os.path.exists(path):
            lines = [" ".join(row) for table in _tables_for(path) for row in table]
        source = os.path.basename(path)
        for line in lines:
            low = line.lower()
            strong = any(marker in low for marker in _TERM_STRONG)
            weak = any(marker in low for marker in _TERM_WEAK)
            if not (strong or weak):
                continue
            # «срок исполнения» без привязки к поставке/работам — это не срок поставки.
            if strong and "постав" not in low and "товар" not in low \
                    and "работ" not in low and "услуг" not in low:
                continue
            if any(bad in low for bad in _TERM_SKIP):
                continue
            if not re.search(r"\d", low):
                continue
            text = re.sub(r"\s+", " ", line).strip()
            parsed = _parse_term_dates(text)
            dated = bool(parsed.get("deadline") or parsed.get("duration_value"))
            # Косвенные формулировки и короткие заголовки без срока не информативны.
            if not dated and (weak and not strong or len(text) < 40):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            term = {"source_file": source, "text": text[:300]}
            term.update(parsed)
            found.append(term)
    # Сначала то, где есть конкретная дата или длительность.
    found.sort(key=lambda item: (item.get("deadline") is None,
                                 item.get("duration_value") is None, len(item["text"])))
    # Один срок — одна запись: одинаковую дату/длительность из разных документов
    # (ТЗ, проект договора, извещение) сводим к одному пункту, а прочие формулировки
    # сохраняем в «variants», чтобы ничего не терять.
    merged: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    uninformative: Optional[Dict[str, Any]] = None
    for term in found:
        deadline = term.get("deadline")
        duration = term.get("duration_value")
        if not deadline and not duration:
            if uninformative is None:
                uninformative = dict(term, variants=[], sources=[term.get("source_file")])
                merged.append(uninformative)
            else:
                uninformative.setdefault("variants", []).append(term.get("text"))
                source = term.get("source_file")
                if source and source not in uninformative.setdefault("sources", []):
                    uninformative["sources"].append(source)
            continue
        key = deadline or ("%s|%s" % (duration, term.get("duration_unit") or ""))
        if key in by_key:
            item = by_key[key]
            item.setdefault("variants", []).append(term.get("text"))
            source = term.get("source_file")
            if source and source not in item.setdefault("sources", []):
                item["sources"].append(source)
            if not item.get("anchor") and term.get("anchor"):
                item["anchor"] = term["anchor"]
            continue
        item = dict(term, variants=[], sources=[term.get("source_file")])
        by_key[key] = item
        merged.append(item)
    return merged[:10]


#: Секции требований: (ключ, подписи-заголовки).
_SECTIONS = (
    ("participant", ("требования к участник", "требование к участник",
                     "участник закупки", "требования к участникам")),
    ("product", ("общие требования", "требования к товар", "технические требования",
                 "требования к поставляемому")),
    ("participation", ("условия участия", "порядок подачи", "заявка на участие",
                       "порядок проведения")),
    ("security", ("обеспечение исполнения", "обеспечение заявки", "обеспечение договора")),
    ("national", ("национальн", "преференц", "преимуществ")),
)


def _paragraphs_for(path: str, external: Optional[Dict[str, Dict[str, Any]]]) -> List[str]:
    doc = (external or {}).get(path)
    if doc is not None:
        return [str(x) for x in (doc.get("lines") or [])]
    if path.lower().endswith(".docx"):
        return _docx_paragraphs(path)
    return []


def extract_text_sections(local_paths: List[str],
                          external: Optional[Dict[str, Dict[str, Any]]] = None
                          ) -> Dict[str, List[Dict[str, Any]]]:
    """Текстовые требования секциями: участник / товар / участие / обеспечение / нацрежим.

    Заголовок секции — абзац, содержащий одну из подписей; тело — абзацы до
    следующего заголовка (или до конца документа).
    """
    out: Dict[str, List[Dict[str, Any]]] = {key: [] for key, _ in _SECTIONS}
    for path in local_paths:
        if not path or _is_junk(path):
            continue
        if path not in (external or {}) and not os.path.exists(path):
            continue
        name = os.path.basename(path)
        paras = _paragraphs_for(path, external)
        current = None
        for text in paras:
            low = text.lower()
            hit = None
            if len(text) <= 120:
                for key, labels in _SECTIONS:
                    if any(lbl in low for lbl in labels):
                        hit = key
                        break
            if hit:
                current = hit
                continue
            if current and len(text) > 20:
                out[current].append({"source_file": name, "text": text})
    return out


def _header(rows: List[List[str]]) -> str:
    return re.sub(r"\s+", " ", " ".join(rows[0] if rows else [])).lower()


def _norm_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _squash(value: Any) -> str:
    """Текст без пробелов: pdfplumber рвёт слова внутри ячейки («Еди ниц а изм ере ния»)."""
    return re.sub(r"\s+", "", str(value or "")).lower()


def _find_col(header_low: List[str], *markers: str) -> int:
    """Индекс первой колонки, чьё название содержит любой из маркеров."""
    for idx, title in enumerate(header_low):
        squashed = _squash(title)
        if any(marker in title or _squash(marker) in squashed for marker in markers):
            return idx
    return -1


def _cell(row: List[str], idx: int) -> str:
    return row[idx] if 0 <= idx < len(row) else ""


def _find_item_col(header_low: List[str]) -> int:
    """Колонка товара/позиции — не путать с колонкой «наименование характеристики»."""
    for idx, title in enumerate(header_low):
        squashed = _squash(title)
        has_name = "наименован" in squashed or "товар" in squashed
        if has_name and "характеристик" not in squashed:
            return idx
    for idx, title in enumerate(header_low):
        squashed = _squash(title)
        if "товар" in squashed and ("характеристик" in squashed or "описан" in squashed):
            return idx
    return -1


def _classify(rows: List[List[str]]) -> Optional[str]:
    header = [_norm_cell(c).lower() for c in (rows[0] if rows else [])]
    head = _squash(" ".join(header))
    item_col = _find_item_col(header)
    has_char = any("характеристик" in _squash(h) for h in header)
    has_value = any(any(marker in _squash(h) for marker in
                        ("значени", "параметр", "единица", "требуем")) for h in header)
    if has_char and has_value:
        return "spec_tech" if item_col >= 0 else "tech"
    if "требован" in head and ("национальн" in head or "окпд" in head or "режим" in head):
        return "requirements"
    if item_col >= 0 and ("кол-во" in head or "количество" in head or "окпд" in head or "реестр" in head):
        return "spec"
    if item_col >= 0 and ("цена" in head or "сумма" in head or "стоимость" in head):
        return "spec"
    return None


def _classify_with_offset(rows: List[List[str]]) -> "tuple[Optional[str], int]":
    """Искать шапку таблицы не только в первой строке (Excel/Word с заголовком сверху)."""
    for offset in range(min(8, len(rows))):
        kind = _classify(rows[offset:])
        if kind:
            return kind, offset
    return None, 0


_SPEC_HEADER = ["Наименование", "Код ОКПД2", "Кол-во"]
_TECH_HEADER = ["Параметр", "Значение", "Единица"]


def _emit_spec_tech(out: Dict[str, List[Dict[str, Any]]], data_rows: List[List[str]],
                    header: List[str], name: str) -> None:
    """Комбинированная таблица ТЗ: строка = товар + характеристика + значение."""
    header_low = [_norm_cell(h).lower() for h in header]
    i_name = _find_item_col(header_low)
    i_char = _find_col(header_low, "характеристик")
    i_val = _find_col(header_low, "значени", "параметр")
    i_unit = _find_col(header_low, "единица", "ед. изм")
    i_qty = _find_col(header_low, "кол-во", "количество")
    i_okpd = _find_col(header_low, "окпд", "код")
    seen: set = set()
    for row in data_rows:
        if not any(_norm_cell(c) for c in row):
            continue
        item = _norm_cell(_cell(row, i_name))
        if not item:
            continue
        if item.lower() not in seen:
            seen.add(item.lower())
            out["spec"].append({
                "source_file": name, "header": _SPEC_HEADER,
                "cells": [item, _norm_cell(_cell(row, i_okpd)), _norm_cell(_cell(row, i_qty))],
            })
        char = _norm_cell(_cell(row, i_char))
        value = _norm_cell(_cell(row, i_val))
        if not value:
            continue
        param = item if not char or char == item else "%s — %s" % (item, char)
        out["tech"].append({
            "source_file": name, "header": _TECH_HEADER,
            "cells": [param, value, _norm_cell(_cell(row, i_unit))],
        })


def extract_tables(local_paths: List[str],
                   external: Optional[Dict[str, Dict[str, Any]]] = None
                   ) -> Dict[str, List[Dict[str, Any]]]:
    """Спека / техпараметры / требования по .docx/.xlsx и внешним pdf/doc (.venv воркера)."""
    out: Dict[str, List[Dict[str, Any]]] = {"spec": [], "tech": [], "requirements": []}
    for path in local_paths:
        if not path or _is_junk(path):
            continue
        name = os.path.basename(path)
        doc = (external or {}).get(path)
        if doc is None and not os.path.exists(path):
            continue
        tables = doc.get("tables") if doc else None
        if not tables:
            tables = _tables_for(path)
        for rows in tables:
            kind, offset = _classify_with_offset(rows)
            if not kind:
                continue
            header = rows[offset]
            data_rows = rows[offset + 1:]
            if kind == "spec_tech":
                _emit_spec_tech(out, data_rows, header, name)
                continue
            if kind == "tech":
                header_low = [_norm_cell(h).lower() for h in header]
                i_name = _find_col(header_low, "наименован", "характеристик", "параметр")
                i_val = _find_col(header_low, "значени", "требуем")
                i_unit = _find_col(header_low, "единица", "ед. изм")
                for row in data_rows:
                    if not any(_norm_cell(c) for c in row):
                        continue
                    if i_name >= 0:
                        out["tech"].append({
                            "source_file": name, "header": _TECH_HEADER,
                            "cells": [_norm_cell(_cell(row, i_name)),
                                      _norm_cell(_cell(row, i_val)),
                                      _norm_cell(_cell(row, i_unit))],
                        })
                    else:
                        out["tech"].append({"source_file": name, "header": header, "cells": row})
                continue
            for row in data_rows:
                if not any(_norm_cell(c) for c in row):
                    continue
                out[kind].append({"source_file": name, "header": header, "cells": row})
    return out


def _di_conn() -> Any:
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    kw = dict(require_crm_db_connect_kwargs())
    kw["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kw.setdefault("connect_timeout", 8)
    return psycopg2.connect(**kw)


def load_direct_extraction(procurement_id: int) -> Dict[str, Any]:
    """Смета/техпараметры/требования для закупки (read-only)."""
    empty = {"spec": [], "tech": [], "requirements": [], "sections": {}, "files": 0}
    try:
        conn = _di_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT local_path FROM document_files
                        WHERE procurement_id = %s AND download_status = 'COMPLETED'
                          AND local_path IS NOT NULL""",
                    (int(procurement_id),),
                )
                paths = [r[0] for r in cur.fetchall() if r and r[0]]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("direct extraction DI query failed: %s", exc)
        return empty
    external = _external_docs(paths)
    data = extract_tables(paths, external)
    data["sections"] = extract_text_sections(paths, external)
    data["terms"] = extract_delivery_terms(paths, external)
    data["delivery"] = next(
        (term for term in data["terms"] if term.get("deadline") or term.get("duration_value")),
        (data["terms"][0] if data["terms"] else None))
    data["files"] = len(paths)
    data["parsed"] = len(external)
    return data


def normalize_spec_positions(items: List[str]) -> List[Dict[str, Any]]:
    """ИИ-нормализация позиций сметы: имя + категория реестра (кандидаты).

    Локальная модель через Ollama; ничего не пишет в БД.
    """
    import json as _json
    import urllib.request

    from src.services.manual_category_service import list_categories

    names = [str(x).strip() for x in items if str(x or "").strip()][:20]
    if not names:
        return []
    cats = list_categories(db=None)
    cat_list = "; ".join(f'{c["category_code"]}={c.get("category_name")}' for c in cats)
    prompt = (
        "Ты нормализуешь позиции сметы закупки. Верни СТРОГО JSON-массив объектов вида "
        '{"raw": "...", "normalized": "...", "category_code": "...", '
        '"subcategory_hint": "...", "confidence": 0..1}.\n'
        f"Разрешённые категории: {cat_list}.\n"
        'Если позиция не относится ни к одной — category_code = "OTHER".\n\n'
        "Позиции:\n" + "\n".join(f"- {x}" for x in names) + "\n\nJSON:"
    )
    try:
        body = _json.dumps({"model": "qwen2.5:7b", "prompt": prompt, "stream": False,
                            "options": {"temperature": 0}}).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = _json.loads(resp.read().decode("utf-8")).get("response", "")
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", cleaned).strip()
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start >= 0 and end > start:
            return _json.loads(cleaned[start:end + 1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("normalize_spec_positions failed: %s", exc)
    return []


def normalize_delivery_terms(terms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ИИ-нормализация сроков поставки: дата ИЛИ длительность + точка отсчёта.

    Локальная модель через Ollama; ничего не пишет в БД. Сырьё — строки документов,
    собранные extract_delivery_terms().
    """
    import json as _json
    import urllib.request

    raw_lines = [str(t.get("text") or "").strip() for t in (terms or []) if str(t.get("text") or "").strip()]
    if not raw_lines:
        return []
    prompt = (
        "Ты нормализуешь условие о сроке поставки из документов закупки. "
        "Верни СТРОГО JSON-массив объектов вида "
        '{"raw": "...", "deadline": "YYYY-MM-DD"|null, "duration_value": число|null, '
        '"duration_unit": "дней"|"месяцев"|null, "anchor": "с даты подписания договора"|null, '
        '"confidence": 0..1}.\n'
        "Если в строке конкретная календарная дата — заполни deadline и оставь duration null. "
        "Если указан интервал — заполни duration. Если срок не про поставку — deadline и duration null.\n\n"
        "Строки:\n" + "\n".join("- %s" % line[:300] for line in raw_lines[:20]) + "\n\nJSON:"
    )
    try:
        body = _json.dumps({"model": os.getenv("DIRECT_TERM_MODEL", "qwen2.5:7b"),
                            "prompt": prompt, "stream": False,
                            "options": {"temperature": 0}}).encode("utf-8")
        request = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = _json.loads(response.read().decode("utf-8")).get("response", "")
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", cleaned).strip()
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start >= 0 and end > start:
            return _json.loads(cleaned[start:end + 1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("normalize_delivery_terms failed: %s", exc)
    return []


#: Маркеры требований к сертификатам/декларациям соответствия в документах.
_CERT_MARKERS = ("сертификат", "деклараци", "соответстви", "реестр", "сертификаци",
                 "гарантия", "лицензия", "паспорт")


def build_tkp_request(extraction: Dict[str, Any], dossier: Dict[str, Any], *,
                      include_participant: bool = False, include_security: bool = False,
                      include_national: bool = False,
                      delivery_lines: Optional[List[str]] = None,
                      estimate_rows: Optional[List[Dict[str, Any]]] = None) -> str:
    """Запрос ТКП поставщику из структурированных данных (без модели).

    По умолчанию берём только то, что относится к коммерческому предложению поставщика:
    позиции сметы, технические требования, условия поставки, гарантию и сертификаты.
    Требования к участнику и обеспечение в запрос поставщику не попадают (см. WIP §10) —
    их можно включить флагами.
    """
    ident = (dossier or {}).get("identity") or {}
    md = (dossier or {}).get("money_and_dates") or {}
    parties = (dossier or {}).get("parties") or {}
    spec = extraction.get("spec") or []
    tech = extraction.get("tech") or []
    reqs = extraction.get("requirements") or []
    secs = extraction.get("sections") or {}

    lines: List[str] = []
    lines.append("Запрос технико-коммерческого предложения (ТКП)")
    lines.append(f"Закупка: № {ident.get('contract_number') or '?'} — {ident.get('auction_name') or '?'}")
    law = ident.get("law") or "?"
    lines.append(f"Закон: {law} · ОКПД2: {ident.get('okpd_code') or '?'} · Регион: {ident.get('region') or '?'}")
    lines.append(f"Заказчик: {parties.get('customer') or '?'}")
    lines.append(f"НМЦК: {md.get('initial_price') or '?'} руб.")
    lines.append("")

    rows = estimate_rows if estimate_rows is not None else None
    lines.append(f"1. Позиции сметы ({len(rows) if rows is not None else len(spec)})")
    if rows:
        for row in rows:
            tail = " · ".join(x for x in (
                ("Кол-во: %s %s" % ("%g" % row.get("qty"), row.get("unit") or "")).strip()
                if row.get("qty") else "",
                ("ОКПД2: %s" % row.get("okpd")) if row.get("okpd") else "") if x)
            price = row.get("unit_price")
            if price:
                tail += " · цена за ед.: %s%s" % (
                    "{:,.2f}".format(float(price)).replace(",", " "),
                    {"nmck_share": " (ориентировочно из НМЦК)"}.get(
                        row.get("unit_price_source") or "", ""))
            lines.append(f"  - {row.get('name')}{' · ' + tail if tail else ''}")
        lines.append("")
    elif spec:
        header = spec[0].get("header") or []
        header_low = [str(h).strip().lower() for h in header]

        def _col(marker: str) -> int:
            for idx, title in enumerate(header_low):
                if marker in title:
                    return idx
            return -1

        qty_col = _col("кол")
        okpd_col = _col("окпд")
        for item in spec:
            cells = [str(c).strip() for c in (item.get("cells") or [])]
            joined = " ".join(cells).lower()
            if not cells or "итого" in joined:
                continue
            name = next((c for c in cells if c and len(c) > 5 and c.lower() != "итого"), "?")
            if name in ("—", "-", ""):
                continue
            qty = cells[qty_col] if 0 <= qty_col < len(cells) else ""
            if not qty or not qty.replace(" ", "").isdigit():
                qty = next((c for c in cells[1:] if c.replace(" ", "").isdigit()), "")
            okpd = cells[okpd_col] if 0 <= okpd_col < len(cells) else ""
            if not re.match(r"^\d{2}\.\d{2}", okpd or ""):
                okpd = next((c for c in cells if re.match(r"^\d{2}\.\d{2}", c)), "")
            tail = " · ".join(x for x in (f"Кол-во: {qty}" if qty else "",
                                          f"ОКПД2: {okpd}" if okpd else "") if x)
            lines.append(f"  - {name}{' · ' + tail if tail else ''}")
        lines.append(f"  (Колонки таблицы: {', '.join(header)})")
    else:
        lines.append("  - Позиции не найдены")
    lines.append("")

    lines.append(f"2. Технические параметры ({len(tech)})")
    for item in tech[:120]:
        cells = [str(c).strip() for c in (item.get("cells") or [])]
        if len(cells) >= 2 and cells[0]:
            value = cells[1] if len(cells) > 1 else ""
            unit = cells[2] if len(cells) > 2 else ""
            lines.append(f"  - {cells[0]}: {value} {unit}".rstrip())
    if not tech:
        lines.append("  - не найдены")
    lines.append("")

    lines.append("3. Требования к товару и поставке")
    for item in reqs[:40]:
        cells = [str(c).strip() for c in (item.get("cells") or [])]
        if any(cells):
            lines.append("  - " + " | ".join(c for c in cells if c))
    blocks = [("product", "Требования к товару и поставке")]
    if include_participant:
        blocks.append(("participant", "Требования к участнику"))
    if include_security:
        blocks.append(("security", "Обеспечение"))
    if include_national:
        blocks.append(("national", "Национальный режим"))
    for key, title in blocks:
        items = secs.get(key) or []
        if not items:
            continue
        lines.append(f"  {title} ({len(items)}):")
        for it in items[:15]:
            lines.append(f"    - {str(it.get('text') or '')[:200]}")
    lines.append("")

    if delivery_lines:
        lines.append(f"4. Условия поставки ({len(delivery_lines)})")
        for text in delivery_lines[:15]:
            lines.append(f"  - {str(text)[:220]}")
        lines.append("")

    certs = []
    for it in (secs.get("product") or []) + (secs.get("participant") or []) + reqs:
        text = str(it.get("text") or " ".join(it.get("cells") or []))
        low = text.lower()
        if any(m in low for m in _CERT_MARKERS):
            certs.append(text[:200])
    lines.append(f"5. Сертификаты / декларации соответствия ({len(certs)})")
    for c in certs[:10]:
        lines.append(f"  - {c}")
    if not certs:
        lines.append("  - Список сертификатов и деклараций не найден")
    lines.append("")
    lines.append("Документ подготовлен автоматически: смета, технические параметры, "
                 "требования и национальный режим.")
    return "\n".join(lines)
