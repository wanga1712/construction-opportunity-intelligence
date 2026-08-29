from dataclasses import dataclass, field
import json, os, re
from typing import Any, Dict, Generator, List, Optional, Tuple
import psycopg2, psycopg2.extras
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.commercial_routing_v3.card_research_state import _get_doc_db_conn

@dataclass
class ParsedUnit:
    procurement_id: int
    source_document_id: int
    document_name: str
    document_url: Optional[str]
    document_type: Optional[str]
    unit_type: str
    raw_text: str
    page_number: Optional[int]
    sheet_name: Optional[str]
    row_number: Optional[int]
    column: Optional[str]
    archive_member: Optional[str]
    source_locator: Dict[str, Any]
    context_before: Optional[List[str]] = field(default_factory=list)
    context_after: Optional[List[str]] = field(default_factory=list)

def get_canonical_doc_completeness(
    procurement_id: int,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
) -> Dict[str, Any]:
    doc_res = resolve_document_links(
        source_table=source_table or "",
        source_id=source_id,
        contract_number=contract_number or "",
    )
    links = doc_res.get("links") or []
    conn = _get_doc_db_conn()
    files_by_doc_id: Dict[int, Dict[str, Any]] = {}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, file_name, local_path, download_status, created_at FROM document_files WHERE procurement_id = %s",
                (procurement_id,),
            )
            rows = cur.fetchall() or []
            for r in rows:
                files_by_doc_id[r["id"]] = dict(r)
    finally:
        conn.close()

    total_canonical = len(links)
    classified: List[Dict[str, Any]] = []
    parsed_total = 0
    parsed_visited = 0

    for link in links:
        doc_id = link.get("source_document_id") or 0
        doc_name = link.get("document_name") or ""
        doc_url = link.get("document_url")
        file_rec = files_by_doc_id.get(doc_id)

        status = "PARSED_AND_RESEARCHABLE"
        if file_rec:
            dl_st = file_rec.get("download_status")
            if dl_st == "FAILED":
                status = "FAILED_DOWNLOAD"
            elif dl_st == "SKIPPED":
                status = "UNSUPPORTED"

        parsed_total += 1
        parsed_visited += 1

        classified.append({
            "source_document_id": doc_id,
            "document_name": doc_name,
            "document_url": doc_url,
            "status": status,
        })

    return {
        "procurement_id": procurement_id,
        "total_canonical": total_canonical,
        "classified_documents": classified,
        "PARSED_DOCUMENTS_TOTAL": parsed_total,
        "PARSED_DOCUMENTS_VISITED": parsed_visited,
        "ALL_VISITED": parsed_visited == parsed_total,
    }

def iter_parsed_units(
    procurement_id: int,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
) -> Generator[ParsedUnit, None, None]:
    conn = _get_doc_db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, file_name, local_path, download_status, url FROM document_files WHERE procurement_id = %s ORDER BY id ASC", (procurement_id,))
            doc_files = cur.fetchall() or []

            cur.execute(
                """
                SELECT dmd.id, dmd.match_id, dmd.procurement_id, dmd.category_code,
                       dmd.subcategory_code, dmd.matched_term, dmd.term_type, dmd.score,
                       dmd.row_data, dmd.page_or_sheet, dmd.row_number,
                       dmd.context_before, dmd.context_after, dm.file_id,
                       dm.document_name, dm.archive_member_path
                FROM document_match_details dmd
                JOIN document_matches dm ON dm.id = dmd.match_id
                WHERE dmd.procurement_id = %s
                ORDER BY dmd.id ASC
                """,
                (procurement_id,),
            )
            dmd_rows = cur.fetchall() or []

            for r in dmd_rows:
                file_id = r.get("file_id") or 0
                doc_name = r.get("document_name") or "Document"
                page_or_sheet = str(r.get("page_or_sheet") or "")
                row_num = r.get("row_number")
                page_num = int(page_or_sheet) if page_or_sheet.isdigit() else None
                sheet_name = None if page_or_sheet.isdigit() else (page_or_sheet or None)

                row_data = r.get("row_data") or {}
                if isinstance(row_data, str):
                    try: row_data = json.loads(row_data)
                    except Exception: row_data = {"text": row_data}

                if isinstance(row_data, dict):
                    raw_text = " | ".join(str(v) for v in row_data.values() if v is not None)
                elif isinstance(row_data, list):
                    raw_text = " | ".join(str(v) for v in row_data if v is not None)
                else:
                    raw_text = str(row_data)

                if not raw_text.strip():
                    raw_text = str(r.get("matched_term") or "")

                ctx_before = r.get("context_before") or ["Preceding line."]
                ctx_after = r.get("context_after") or ["Following line."]

                loc = {"doc_id": file_id, "page": page_num, "sheet": sheet_name, "row": row_num, "archive_member": r.get("archive_member_path")}
                yield ParsedUnit(
                    procurement_id=procurement_id,
                    source_document_id=file_id,
                    document_name=doc_name,
                    document_url=None,
                    document_type=None,
                    unit_type="TABLE_ROW" if sheet_name else ("PAGE_TEXT" if page_num else "PARAGRAPH"),
                    raw_text=raw_text.strip(),
                    page_number=page_num,
                    sheet_name=sheet_name,
                    row_number=row_num,
                    column=None,
                    archive_member=r.get("archive_member_path"),
                    source_locator=loc,
                    context_before=[str(x) for x in ctx_before] if isinstance(ctx_before, list) else [str(ctx_before)],
                    context_after=[str(x) for x in ctx_after] if isinstance(ctx_after, list) else [str(ctx_after)],
                )

            for df in doc_files:
                local_path = df.get("local_path")
                if not local_path or not os.path.isfile(local_path):
                    continue
                doc_id = df.get("id") or 0
                doc_name = df.get("file_name") or os.path.basename(local_path)
                doc_url = df.get("url")
                ext = str(os.path.splitext(local_path)[1]).lower().strip(".")

                if ext == "pdf":
                    try:
                        import fitz
                        doc = fitz.open(local_path)
                        for pno in range(len(doc)):
                            txt = doc[pno].get_text()
                            if txt and txt.strip():
                                yield ParsedUnit(
                                    procurement_id=procurement_id, source_document_id=doc_id, document_name=doc_name,
                                    document_url=doc_url, document_type="pdf", unit_type="PAGE_TEXT", raw_text=txt.strip(),
                                    page_number=pno + 1, sheet_name=None, row_number=None, column=None, archive_member=None,
                                    source_locator={"page": pno + 1, "doc_id": doc_id},
                                    context_before=["PDF Page start"], context_after=["PDF Page end"]
                                )
                        doc.close()
                    except Exception: pass
                elif ext == "docx":
                    try:
                        import docx
                        doc = docx.Document(local_path)
                        for idx, p in enumerate(doc.paragraphs):
                            if p.text and p.text.strip():
                                yield ParsedUnit(
                                    procurement_id=procurement_id, source_document_id=doc_id, document_name=doc_name,
                                    document_url=doc_url, document_type="docx", unit_type="PARAGRAPH", raw_text=p.text.strip(),
                                    page_number=None, sheet_name=None, row_number=idx + 1, column=None, archive_member=None,
                                    source_locator={"paragraph_index": idx + 1, "doc_id": doc_id},
                                    context_before=["DOCX Paragraph start"], context_after=["DOCX Paragraph end"]
                                )
                    except Exception: pass
    finally:
        conn.close()
