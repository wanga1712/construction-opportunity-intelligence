"""WAVE 1B: ALL LOCAL DOCUMENTS (независимо от DOCUMENT_SELECTION_V3).

Технические ограничения (не коммерческие):
  local_present = true (local_path есть, local_deleted_at IS NULL)
  parseable artifact (.docx/.xlsx/.xlsm/.pdf/.doc/.xls)
  not known-corrupt (error_message не содержит CORRUPT/INVALID)
  physical file dedup: один физический файл парсим один раз, provenance
  сохраняем на все документы/закупки, где он прикреплён.

HTTP=0. Документы, уже обработанные в WAVE 1A (та же generation), не гоняем.
CRM/queue/UI/lifecycle не трогаются.

Запуск на S13 (воркерный venv!):
  export DOCUMENT_PIPELINE_GENERATION=S13_V4_EXHAUSTIVE_CONTEXT
  bash -c '... /opt/tender_documents_research/.venv/bin/python \
      /opt/CRM_Streamlit/scripts/run_all_local_reprocess_v1b.py'
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/tender_documents_research")
sys.path.insert(0, "/opt/CRM_Streamlit")

import psycopg2  # noqa: E402

from document_processor.parse_extractors import extract_and_persist
from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta
from document_processor.parser_factory import ParserFactory
from src.services.crm_db_runtime import require_crm_db_connect_kwargs  # noqa: E402

GENERATION = os.getenv("DOCUMENT_PIPELINE_GENERATION", "S13_V4_EXHAUSTIVE_CONTEXT")
PARSEABLE = (".docx", ".xlsx", ".xlsm", ".pdf", ".doc", ".xls")
CORRUPT_MARKERS = ("CORRUPT", "INVALID_FILE", "PACKAGE_NOT_FOUND", "UNSUPPORTED_ZIP")

logging.basicConfig(level=logging.ERROR)


def main() -> int:
    ckw = dict(require_crm_db_connect_kwargs())
    di_kw = dict(host=ckw["host"], port=int(ckw["port"]), user=ckw["user"],
                 password=ckw["password"],
                 dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"))

    # 1. все локальные документы + дедуп по физическому файлу
    conn = psycopg2.connect(**di_kw)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, procurement_id, file_name, local_path, physical_download_key, error_message
          FROM document_files
         WHERE local_path IS NOT NULL AND local_deleted_at IS NULL
           AND download_status = 'COMPLETED'
         ORDER BY id
    """)
    all_rows = cur.fetchall()
    conn.close()

    physical = {}
    selected = []
    skipped_corrupt = skipped_format = 0
    for file_id, pid, name, path, pkey, err in all_rows:
        low = str(name or "").lower()
        if not low.endswith(PARSEABLE):
            skipped_format += 1
            continue
        if err and any(m in str(err).upper() for m in CORRUPT_MARKERS):
            skipped_corrupt += 1
            continue
        if not Path(path).exists():
            continue
        key = pkey or path
        physical.setdefault(key, []).append(
            {"id": file_id, "procurement_id": pid, "file_name": name, "local_path": path})

    for key, group in physical.items():
        primary = group[0]
        primary["attached_file_ids"] = [g["id"] for g in group]
        primary["attached_procurements"] = sorted({g["procurement_id"] for g in group})
        selected.append(primary)

    # 2. исключить уже обработанные в WAVE 1A по version-scoped outcome-памяти
    #    ключ: source_document_id + EMBEDDED_EXTRACTOR_V1 + COALESCE(category_code,'')
    conn = psycopg2.connect(**di_kw)
    cur = conn.cursor()
    cur.execute("""SELECT source_document_id, COALESCE(category_code, '')
                     FROM document_extraction_outcomes
                    WHERE extractor_version = 'EMBEDDED_EXTRACTOR_V1'""")
    done_1a = {(int(r[0]), str(r[1])) for r in cur.fetchall()}
    conn.close()
    wave1b = selected
    print("WAVE1A_OUTCOME_PAIRS=%d" % len(done_1a))
    print("WAVE1B_ALL_LOCAL_ADDITIONAL_DOCS=%d" % len(wave1b))
    print("PHYSICAL_DEDUP_SAVED=%d" % (len(all_rows) - len(selected)))
    print("SKIPPED_FORMAT=%d SKIPPED_CORRUPT=%d" % (skipped_format, skipped_corrupt))

    # 3. категория закупки (read-only CRM)
    crm = psycopg2.connect(**ckw)
    cc = crm.cursor()
    pids = sorted({d["procurement_id"] for d in wave1b})
    cat_by_pid = defaultdict(list)
    for chunk_start in range(0, len(pids), 5000):
        chunk = pids[chunk_start:chunk_start + 5000]
        cc.execute("""SELECT procurement_id, commercial_category_code
                        FROM crm_procurement_category_opportunities
                       WHERE status='CURRENT' AND procurement_id = ANY(%s)""", (chunk,))
        for pid, cat in cc.fetchall():
            cat_by_pid[int(pid)].append(str(cat))
    crm.close()

    # 4. прогон: parse -> extract_and_persist (структурные факты + атрибуты)
    pf = ParserFactory()
    counters = Counter()
    facts_by_scope = Counter()
    non_selected_facts = Counter()
    by_doc_class = Counter()
    by_ext = Counter()
    for doc in wave1b:
        path = Path(doc["local_path"])
        cats = cat_by_pid.get(doc["procurement_id"]) or ["unknown"]
        name_low = str(doc["file_name"] or "").lower()
        is_estimate = any(k in name_low for k in ("смет", "расчет нмцк", "расчёт нмцк", "вор"))
        is_techspec = any(k in name_low for k in ("тех", "тз", "специфик", "ооз", "описание объекта"))
        is_xls = path.suffix.lower() in (".xlsx", ".xls", ".xlsm")
        if is_estimate:
            counters["ESTIMATE_DOCS_PARSED"] += 1
        if is_techspec:
            counters["TECH_SPEC_DOCS_PARSED"] += 1
        if is_xls:
            counters["XLSX_XLS_DOCS_PARSED"] += 1
        parser = get_rich_parser(pf, path) if supports_rich_meta(path) else pf.get_parser(path)
        if parser is None:
            counters["UNSUPPORTED"] += 1
            continue
        try:
            text, meta = parse_file_with_meta(parser, path)
        except Exception:
            counters["PARSE_FAILED"] += 1
            continue
        if not text:
            counters["NO_TEXT"] += 1
            continue
        counters["DOCUMENTS_LOCAL_REPROCESSED"] += 1
        found_any = False
        for cat in cats:
            # пару (документ, категория) не повторяем, но ДОБАВЛЯЕМ новые категории
            if (doc["id"], "" if cat == "unknown" else cat) in done_1a:
                counters["PAIR_ALREADY_DONE"] += 1
                continue
            res = extract_and_persist(path, text, doc["procurement_id"], doc["file_name"],
                                      category_code=(None if cat == "unknown" else cat),
                                      source_document_id=doc["id"],
                                      physical_key=doc["local_path"], line_meta=meta,
                                      track="EMBEDDED_MATERIAL")
            n = int(res.get("embedded") or 0)
            if n:
                found_any = True
                non_selected_facts[cat] += n
                by_doc_class["ESTIMATE" if is_estimate else
                             ("TECH_SPEC" if is_techspec else "OTHER")] += n
                by_ext[path.suffix.lower() or "?"] += n
                if is_estimate:
                    counters["FACTS_FROM_ESTIMATE"] += n
                if is_techspec:
                    counters["FACTS_FROM_TECH_SPEC"] += n
                if is_xls:
                    counters["FACTS_FROM_XLSX_XLS"] += n
        if found_any:
            counters["FACTS_FOUND"] += 1
        else:
            counters["NO_FACTS"] += 1

    # 5. structured entities/attributes, созданные этой волной (по procurement)
    conn = psycopg2.connect(**di_kw)
    cur = conn.cursor()
    seen_pids = tuple(sorted({d["procurement_id"] for d in wave1b})) or (0,)
    cur.execute("""SELECT count(*) FROM structured_entities WHERE procurement_id = ANY(%s)""",
                (list(seen_pids),))
    counters["STRUCTURED_ENTITIES"] = int(cur.fetchone()[0] or 0)
    cur.execute("""SELECT count(*) FROM structured_attributes a
                     JOIN structured_entities e ON e.id = a.entity_id
                    WHERE e.procurement_id = ANY(%s)""", (list(seen_pids),))
    counters["TECH_ATTRIBUTES"] = int(cur.fetchone()[0] or 0)
    conn.close()

    print("WAVE1B_RESULT " + json.dumps(counters, ensure_ascii=False))
    print("FACTS_FROM_NON_SELECTED " + json.dumps(dict(non_selected_facts),
                                                  ensure_ascii=False))
    print("FACTS_FROM_NON_SELECTED_BY_DOC_CLASS " + json.dumps(dict(by_doc_class),
                                                               ensure_ascii=False))
    print("FACTS_FROM_NON_SELECTED_BY_EXT " + json.dumps(dict(by_ext), ensure_ascii=False))
    print("HTTP_REQUESTS=0 CRM_WRITES=0 QUEUE_WRITES=0 UI_CHANGES=0")
    with open("/tmp/all_local_reprocess_v1b.json", "w", encoding="utf-8") as fh:
        json.dump({"generation": GENERATION, "counters": dict(counters),
                   "facts_by_category_non_selected": dict(non_selected_facts)}, fh,
                  ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
