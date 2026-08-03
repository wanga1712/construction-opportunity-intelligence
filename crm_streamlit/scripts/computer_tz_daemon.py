"""Daemon: open computer OKPD tenders → download TZ → shared parsers → supplier card.

Parallel to materials tender-docs-daemon. Uses the same PDF/DOCX/DOC/XLSX engines
from /opt/tender_documents_research, but selects only OKPD 26.20* and only
non-awarded registry tables by default.

  cd /opt/CRM_Streamlit
  .venv/bin/python scripts/computer_tz_daemon.py --once --only-open
"""
from __future__ import annotations

import argparse
import re
import ssl
import sys
import time
import urllib.request
import os
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bootstrap import setup_source_path  # noqa: E402

setup_source_path()

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from loguru import logger  # noqa: E402

from modules.crm.repositories.tender_repository import TenderDetailRepository  # noqa: E402
from src.services.computer_doc_extract import (  # noqa: E402
    combine_document_texts,
    extract_text_from_bytes,
)
from src.services.computer_tz_ai import analyze_tz_to_supplier_card  # noqa: E402
from src.services.computers_service import (  # noqa: E402
    ensure_computer_cards_schema,
    load_computer_cards,
    load_computer_tenders,
    replace_computer_items,
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
    r"(техн|тз|задани|специф|требован|конфигурац|характеристик|приложение|"
    r"описан|извещен|\.pdf|\.docx?|\.xlsx?|\.zip)",
    re.IGNORECASE,
)


def _normalize_items(card: dict, row) -> list[dict]:
    items = card.get("items")
    normalized: list[dict] = []
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            normalized.append(
                {
                    "category": it.get("category") or card.get("equipment_type") or "other",
                    "name": it.get("name") or row.name,
                    "qty": it.get("qty"),
                    "unit": it.get("unit") or "шт",
                    "specs": it.get("specs") or [],
                }
            )
    if normalized:
        return normalized
    qty = card.get("qty")
    return [
        {
            "category": card.get("equipment_type") or "other",
            "name": row.name,
            "qty": qty if qty is not None else 1,
            "unit": "шт",
            "specs": card.get("must_have") or [],
        }
    ]


def _download(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "CRM-ComputerTZ/1.1"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _pick_tz_documents(docs: list, *, limit: int = 12, strict_tz_only: bool = True) -> list:
    preferred = []
    rest = []
    for d in docs:
        name = str(getattr(d, "file_name", None) or (d.get("file_name") if isinstance(d, dict) else "") or "")
        url = getattr(d, "url", None) if not isinstance(d, dict) else d.get("url")
        if not url:
            continue
        item = {"file_name": name or "document.bin", "url": url}
        if _TZ_NAME_RE.search(name or ""):
            preferred.append(item)
        else:
            rest.append(item)
    if strict_tz_only:
        return preferred[:limit]
    return (preferred + rest)[:limit]


def process_one(tender_db, crm_db, row, *, force: bool = False, strict_tz_only: bool = True) -> str:
    cards = load_computer_cards(crm_db, [row.key])
    existing = cards.get(row.key) or {}
    # Skip only fully ready cards with extracted text; re-parse partials when extractors improve.
    if (
        not force
        and existing.get("status") == "ready"
        and existing.get("supplier_card")
        and (existing.get("tz_text_excerpt") or "").strip()
        and "извлечь не удалось" not in (existing.get("tz_text_excerpt") or "")
    ):
        return "skip_ready"

    cfg = tender_db.connection_manager.config
    repo = TenderDetailRepository(
        cfg.host, cfg.database, cfg.user, cfg.password, cfg.port,
    )
    docs = repo.get_documents(row.tender_id, row.registry_type)
    picked = _pick_tz_documents(docs, strict_tz_only=strict_tz_only)
    if not picked:
        status_no_docs = "no_docs"
        no_docs_message = "Нет ссылок на документацию"
        if strict_tz_only:
            status_no_docs = "no_tz_docs"
            no_docs_message = "Нет документов с признаками ТЗ/спецификации"
        save_computer_card(
            crm_db,
            object_key=row.key,
            payload={
                "tender_id": row.tender_id,
                "registry_type": row.registry_type,
                "contract_number": row.contract_number,
                "okpd_code": row.okpd_code,
                "status": status_no_docs,
                "tz_file_names": [],
                "error_message": no_docs_message,
            },
        )
        return status_no_docs

    chunks: List[tuple[str, str]] = []
    names: List[str] = []
    for doc in picked:
        try:
            raw = _download(doc["url"])
            names.append(doc["file_name"])
            text = extract_text_from_bytes(raw, doc["file_name"])
            if text.strip():
                chunks.append((doc["file_name"], text))
                logger.info(
                    f"{row.key} parsed {doc['file_name']}: {len(text)} chars"
                )
            else:
                logger.warning(f"{row.key} empty parse: {doc['file_name']}")
        except Exception as exc:
            logger.warning(f"download/parse fail {doc.get('file_name')}: {exc}")

    combined = combine_document_texts(chunks)
    if not combined:
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
                "tz_text_excerpt": combined[:6000],
                "supplier_card": card,
                "model_name": card.get("model_name"),
                "model_version": card.get("model_version"),
            },
        )
        replace_computer_items(
            crm_db,
            object_key=row.key,
            tender_id=row.tender_id,
            registry_type=row.registry_type,
            items=_normalize_items(card, row),
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
                "tz_text_excerpt": combined[:6000] if combined else None,
                "error_message": str(exc)[:500],
            },
        )
        return "error"


def run_batch(*, limit: int, only_open: bool, force: bool, strict_tz_only: bool) -> dict:
    tender_db = _tender_db()
    crm_db = _crm_db()
    ensure_computer_cards_schema(crm_db)
    rows = load_computer_tenders(tender_db, limit=limit, only_open=only_open)
    logger.info(
        f"computers batch: only_open={only_open} candidates={len(rows)} "
        f"(OKPD 26.20*; open = not awarded/completed)"
    )
    stats = {
        "total": len(rows),
        "ready": 0,
        "partial": 0,
        "skip_ready": 0,
        "no_docs": 0,
        "no_tz_docs": 0,
        "error": 0,
    }
    for row in rows:
        result = process_one(tender_db, crm_db, row, force=force, strict_tz_only=strict_tz_only)
        stats[result] = stats.get(result, 0) + 1
        logger.info(f"{row.key} → {result} | {row.okpd_code} | {row.name[:80]}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Computer TZ → supplier card daemon")
    parser.add_argument("--once", action="store_true", help="Single batch then exit")
    parser.add_argument("--loop", action="store_true", help="Run forever")
    parser.add_argument("--interval", type=int, default=900, help="Seconds between loops")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--only-open",
        action="store_true",
        default=False,
        help="Only non-awarded registry tables (default)",
    )
    parser.add_argument(
        "--include-awarded",
        action="store_true",
        help="Also process awarded/completed computer tenders",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--strict-tz-only",
        action="store_true",
        help="Parse only files that look like TZ/spec (recommended for computers).",
    )
    parser.add_argument(
        "--allow-non-tz-fallback",
        action="store_true",
        help="Fallback to non-TZ docs if no TZ-named files found.",
    )
    args = parser.parse_args()
    strict_tz_only = True
    if os.getenv("COMPUTER_TZ_STRICT_ONLY", "1") == "0":
        strict_tz_only = False
    if args.strict_tz_only:
        strict_tz_only = True
    if args.allow_non_tz_fallback:
        strict_tz_only = False


    only_open = not args.include_awarded
    if args.only_open:
        only_open = True

    if not args.once and not args.loop:
        args.once = True

    while True:
        stats = run_batch(
            limit=args.limit,
            only_open=only_open,
            force=args.force,
            strict_tz_only=strict_tz_only,
        )
        logger.info(f"batch done: {stats}")
        if args.once or not args.loop:
            break
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
