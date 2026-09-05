"""Daemon: computer OKPD tenders → download TZ → Ollama → supplier card.

Run on <S13_SSH_USER> (S13):
  cd /opt/CRM_Streamlit && python scripts/computer_tz_daemon.py --once
  python scripts/computer_tz_daemon.py --loop --interval 900

systemd unit (optional): crm-computer-tz.service / .timer
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from loguru import logger  # noqa: E402

from modules.crm.repositories.tender_repository import TenderDetailRepository  # noqa: E402
from src.services.computer_tz_ai import analyze_tz_to_supplier_card  # noqa: E402
from src.services.computers_service import (  # noqa: E402
    ensure_computer_cards_schema,
    load_computer_cards,
    load_computer_tenders,
    save_computer_card,
)
from src.services.db_bootstrap import connect_databases  # noqa: E402


def _crm_db():
    _radar, tender, crm, _warn = connect_databases()
    return crm


def _tender_db():
    _radar, tender, crm, _warn = connect_databases()
    return tender


_TZ_NAME_RE = re.compile(
    r"(техн|тз|задани|специф|требован|конфигурац|характеристик|приложение)",
    re.IGNORECASE,
)


def _extract_text_from_bytes(data: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt") or name.endswith(".csv"):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".docx"):
        try:
            import zipfile
            from xml.etree import ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                xml = zf.read("word/document.xml")
            root = ET.fromstring(xml)
            texts = [
                node.text
                for node in root.iter()
                if node.text and node.tag.endswith("}t")
            ]
            return "\n".join(texts)
        except Exception as exc:
            logger.warning(f"docx extract failed {filename}: {exc}")
            return ""
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:40]:
                parts.append(page.extract_text() or "")
            return "\n".join(parts)
        except Exception:
            try:
                import PyPDF2  # type: ignore

                reader = PyPDF2.PdfReader(io.BytesIO(data))
                parts = [p.extract_text() or "" for p in reader.pages[:40]]
                return "\n".join(parts)
            except Exception as exc:
                logger.warning(f"pdf extract failed {filename}: {exc}")
                return ""
    return ""


def _download(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CRM-ComputerTZ/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _pick_tz_documents(docs: list) -> list:
    preferred = []
    rest = []
    for d in docs:
        name = str(getattr(d, "file_name", None) or d.get("file_name") if isinstance(d, dict) else "")
        url = getattr(d, "url", None) if not isinstance(d, dict) else d.get("url")
        if not url:
            continue
        item = {"file_name": name, "url": url}
        if _TZ_NAME_RE.search(name or ""):
            preferred.append(item)
        else:
            rest.append(item)
    return (preferred or rest)[:5]


def process_one(tender_db, crm_db, row, *, force: bool = False) -> str:
    cards = load_computer_cards(crm_db, [row.key])
    existing = cards.get(row.key) or {}
    if not force and existing.get("status") == "ready" and existing.get("supplier_card"):
        return "skip_ready"

    cfg = tender_db.connection_manager.config
    repo = TenderDetailRepository(
        cfg.host, cfg.database, cfg.user, cfg.password, cfg.port,
    )
    docs = repo.get_documents(row.tender_id, row.registry_type)
    picked = _pick_tz_documents(docs)
    if not picked:
        save_computer_card(
            crm_db,
            object_key=row.key,
            payload={
                "tender_id": row.tender_id,
                "registry_type": row.registry_type,
                "contract_number": row.contract_number,
                "okpd_code": row.okpd_code,
                "status": "no_docs",
                "tz_file_names": [],
                "error_message": "Нет ссылок на документацию",
            },
        )
        return "no_docs"

    texts: List[str] = []
    names: List[str] = []
    for doc in picked:
        try:
            raw = _download(doc["url"])
            text = _extract_text_from_bytes(raw, doc["file_name"])
            names.append(doc["file_name"])
            if text.strip():
                texts.append(f"=== {doc['file_name']} ===\n{text}")
        except Exception as exc:
            logger.warning(f"download fail {doc.get('file_name')}: {exc}")

    combined = "\n\n".join(texts).strip()
    if not combined:
        # Still ask model with metadata + filenames — better than nothing
        combined = (
            f"Тексты файлов извлечь не удалось. Имена документов: {', '.join(names)}. "
            f"Название закупки: {row.name}. ОКПД: {row.okpd_code} {row.okpd_name or ''}."
        )
        status_prefix = "partial"
    else:
        status_prefix = "ready"

    try:
        card = analyze_tz_to_supplier_card(
            auction_name=row.name,
            okpd_code=row.okpd_code or "",
            okpd_name=row.okpd_name or "",
            price=str(row.initial_price or ""),
            customer=row.customer_name or "",
            tz_text=combined,
            timeout=180,
        )
        save_computer_card(
            crm_db,
            object_key=row.key,
            payload={
                "tender_id": row.tender_id,
                "registry_type": row.registry_type,
                "contract_number": row.contract_number,
                "okpd_code": row.okpd_code,
                "status": status_prefix,
                "tz_file_names": names,
                "tz_text_excerpt": combined[:4000],
                "supplier_card": card,
                "model_name": card.get("model_name"),
                "model_version": card.get("model_version"),
            },
        )
        return status_prefix
    except Exception as exc:
        save_computer_card(
            crm_db,
            object_key=row.key,
            payload={
                "tender_id": row.tender_id,
                "registry_type": row.registry_type,
                "contract_number": row.contract_number,
                "okpd_code": row.okpd_code,
                "status": "error",
                "tz_file_names": names,
                "tz_text_excerpt": combined[:4000] if combined else None,
                "error_message": str(exc)[:500],
            },
        )
        return "error"


def run_batch(*, limit: int, only_open: bool, force: bool) -> dict:
    tender_db = _tender_db()
    crm_db = _crm_db()
    ensure_computer_cards_schema(crm_db)
    rows = load_computer_tenders(tender_db, limit=limit, only_open=only_open)
    stats = {"total": len(rows), "ready": 0, "partial": 0, "skip_ready": 0, "no_docs": 0, "error": 0}
    for row in rows:
        result = process_one(tender_db, crm_db, row, force=force)
        stats[result] = stats.get(result, 0) + 1
        logger.info(f"{row.key} → {result} | {row.okpd_code} | {row.name[:80]}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Computer TZ → supplier card daemon")
    parser.add_argument("--once", action="store_true", help="Single batch then exit")
    parser.add_argument("--loop", action="store_true", help="Run forever")
    parser.add_argument("--interval", type=int, default=900, help="Seconds between loops")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--only-open", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.once and not args.loop:
        args.once = True

    while True:
        stats = run_batch(limit=args.limit, only_open=args.only_open, force=args.force)
        logger.info(f"batch done: {stats}")
        if args.once or not args.loop:
            break
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
