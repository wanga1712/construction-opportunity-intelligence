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
        if not path or not os.path.exists(path) or not path.lower().endswith(".docx"):
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


def _classify(rows: List[List[str]]) -> Optional[str]:
    head = _header(rows)
    if "характеристик" in head and ("значени" in head or "единица" in head):
        return "tech"
    if "требован" in head and ("национальн" in head or "окпд" in head or "режим" in head):
        return "requirements"
    if ("наименован" in head or "наименование" in head) and (
        "кол-во" in head or "количество" in head or "окпд" in head or "реестр" in head
    ):
        return "spec"
    return None


def extract_tables(local_paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Спека / техпараметры / требования по всем .docx закупки."""
    out: Dict[str, List[Dict[str, Any]]] = {"spec": [], "tech": [], "requirements": []}
    for path in local_paths:
        if not path or not os.path.exists(path) or not path.lower().endswith(".docx"):
            continue
        name = os.path.basename(path)
        for rows in _docx_tables(path):
            kind = _classify(rows)
            if not kind:
                continue
            header = rows[0]
            for row in rows[1:]:
                if not any(c.strip() for c in row):
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
