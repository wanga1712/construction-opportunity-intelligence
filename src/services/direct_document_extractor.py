"""DIRECT-экстрактор: смета / техпараметры / требования из документов закупки.

Без внешних зависимостей: .docx читается как zip + XML (works в любом venv).
Никаких записей — только чтение локальных файлов, уже скачанных документным
контуром. Нормализация названий через ИИ — следующий этап.
"""
from __future__ import annotations

import logging
import os
import re
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


def extract_text_sections(local_paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Текстовые требования секциями: участник / товар / участие / обеспечение / нацрежим.

    Заголовок секции — абзац, содержащий одну из подписей; тело — абзацы до
    следующего заголовка (или до конца документа).
    """
    out: Dict[str, List[Dict[str, Any]]] = {key: [] for key, _ in _SECTIONS}
    for path in local_paths:
        if not path or not os.path.exists(path) or _is_junk(path):
            continue
        if not path.lower().endswith(".docx"):
            continue
        name = os.path.basename(path)
        paras = _docx_paragraphs(path)
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


def _find_col(header_low: List[str], *markers: str) -> int:
    """Индекс первой колонки, чьё название содержит любой из маркеров."""
    for idx, title in enumerate(header_low):
        if any(marker in title for marker in markers):
            return idx
    return -1


def _cell(row: List[str], idx: int) -> str:
    return row[idx] if 0 <= idx < len(row) else ""


def _find_item_col(header_low: List[str]) -> int:
    """Колонка товара/позиции — не путать с колонкой «наименование характеристики»."""
    for idx, title in enumerate(header_low):
        if ("наименован" in title or "товар" in title) and "характеристик" not in title:
            return idx
    for idx, title in enumerate(header_low):
        if "товар" in title and ("характеристик" in title or "описан" in title):
            return idx
    return -1


def _classify(rows: List[List[str]]) -> Optional[str]:
    header = [_norm_cell(c).lower() for c in (rows[0] if rows else [])]
    head = " ".join(header)
    item_col = _find_item_col(header)
    has_char = any("характеристик" in h for h in header)
    has_value = any(("значени" in h or "параметр" in h or "единица" in h or "требуем" in h)
                    for h in header)
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


def extract_tables(local_paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Спека / техпараметры / требования по .docx и .xlsx закупки."""
    out: Dict[str, List[Dict[str, Any]]] = {"spec": [], "tech": [], "requirements": []}
    for path in local_paths:
        if not path or not os.path.exists(path) or _is_junk(path):
            continue
        name = os.path.basename(path)
        for rows in _tables_for(path):
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
    data = extract_tables(paths)
    data["sections"] = extract_text_sections(paths)
    data["files"] = len(paths)
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


#: Маркеры требований к сертификатам/декларациям соответствия в документах.
_CERT_MARKERS = ("сертификат", "деклараци", "соответстви", "реестр", "сертификаци",
                 "гарантия", "лицензия", "паспорт")


def build_tkp_request(extraction: Dict[str, Any], dossier: Dict[str, Any]) -> str:
    """Детерминированный запрос ТКП по смете + требованиям (deterministic, без модели)."""
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

    lines.append(f"1. Позиции сметы ({len(spec)})")
    if spec:
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

    lines.append("3. Требования")
    for item in reqs[:40]:
        cells = [str(c).strip() for c in (item.get("cells") or [])]
        if any(cells):
            lines.append("  - " + " | ".join(c for c in cells if c))
    for key, title in (("product", "Требования к товару и поставке"),
                       ("participant", "Требования к участнику"),
                       ("security", "Обеспечение"),
                       ("national", "Национальный режим")):
        items = secs.get(key) or []
        if not items:
            continue
        lines.append(f"  {title} ({len(items)}):")
        for it in items[:15]:
            lines.append(f"    - {str(it.get('text') or '')[:200]}")
    lines.append("")

    certs = []
    for it in (secs.get("product") or []) + (secs.get("participant") or []) + reqs:
        text = str(it.get("text") or " ".join(it.get("cells") or []))
        low = text.lower()
        if any(m in low for m in _CERT_MARKERS):
            certs.append(text[:200])
    lines.append(f"4. Сертификаты / декларации соответствия ({len(certs)})")
    for c in certs[:10]:
        lines.append(f"  - {c}")
    if not certs:
        lines.append("  - Список сертификатов и деклараций не найден")
    lines.append("")
    lines.append("Документ подготовлен автоматически: смета, технические параметры, "
                 "требования и национальный режим.")
    return "\n".join(lines)
