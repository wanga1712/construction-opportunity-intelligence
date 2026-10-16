import os
import time
from pathlib import Path
from typing import Optional, Tuple
from document_processor.pdf_processor import parse_pdf_incremental
from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta


def _archive_parent_identity(path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (parent_file_name, parent_local_path, archive_member_path) for extracted members.

    S13 extraction keeps source archives durable in the task directory and extracts
    members either directly under the task directory or under a directory named
    after the archive stem. We anchor derived parser results to that durable
    source archive while preserving the member relative path separately.

    NOTE (ARCHIVE_MEMBER_PARSE_CONTEXT_V1): this resolved-by-name rule only holds
    when the extracted directory is named after the archive. For nested/chained
    archives (e.g. an archive whose members live under `<member-stem>/…`) the real
    source archive cannot be recovered from the path, and returning a name that
    has no `document_files` row breaks persistence anchoring. Member→plan binding
    is therefore established by `physical_download_key` in the daemon, not here.
    """
    archive_exts = (".zip", ".rar", ".r00")
    try:
        cur = path.parent
        while cur != cur.parent:
            for ext in archive_exts:
                candidate = cur.with_suffix(ext)
                if candidate.exists() and candidate.is_file():
                    try:
                        member_path = path.relative_to(cur).as_posix()
                    except ValueError:
                        member_path = path.name
                    return candidate.name, str(candidate), member_path
            # Stop at common task directory shape after walking a few levels.
            if cur.parent == cur:
                break
            cur = cur.parent
    except Exception:
        return None, None, None
    return None, None, None

class S13V2Pipeline:
    def __init__(self, parser_factory, downloader, logger, is_over_memory_limit):
        self.parser_factory = parser_factory
        self.downloader = downloader
        self.logger = logger
        self.is_over_memory_limit = is_over_memory_limit

    def process_task(
        self,
        queue_id: int,
        procurement_id: int,
        contract_reg_number: str,
        table_source: str,
        files: list[Path],
        match_engine,
        category_codes: list | None = None,
        soft_fallback_file_names: set | None = None,
        selected_doc_context: dict | None = None,
    ):
        """
        Pure compute processing for S13_V2. No DB writes.
        Returns dto.TaskProcessResult.
        """
        from document_processor.dto import TaskProcessResult, ProcessingOutcome, FileProcessResult, MatchResult, EvidenceResult
        from document_processor.file_skip_list import should_skip_file

        # DOCUMENT_SELECTION_V3: only explicitly planned soft-fallback documents
        # (queue plan selection_type=SOFT_FALLBACK, ID-scoped) may bypass the
        # filename semantic skip. HARD_SKIP is never bypassed.
        bypass_names = {
            str(n).strip().lower() for n in (soft_fallback_file_names or set()) if n
        }
        doc_ctx = selected_doc_context or {}
        soft_bypass_used = 0

        def _skip(name: str) -> bool:
            nonlocal soft_bypass_used
            if not should_skip_file(name):
                return False
            if str(name).strip().lower() in bypass_names:
                soft_bypass_used += 1
                self.logger.info(
                    f"[{procurement_id}] SOFT_FALLBACK explicit bypass: {name}"
                )
                return False
            return True

        result = TaskProcessResult(
            procurement_id=procurement_id,
            queue_id=queue_id,
            outcome=ProcessingOutcome.SUCCESS,
            files=[],
            evidence=[]
        )

        if not files:
            result.error_message = "Не удалось скачать ни один документ"
            result.outcome = ProcessingOutcome.FAILED
            return result

        # HEAVY guard (HEAVY lane): a pathological archive must fail with an
        # explicit reason instead of holding the worker in PROCESSING.
        member_cap = int(os.getenv("HEAVY_MEMBER_CAP", "300"))
        size_cap = int(os.getenv("HEAVY_UNPACKED_SIZE_CAP_BYTES", str(1024 * 1024 * 1024)))
        time_cap = float(os.getenv("HEAVY_WALL_CLOCK_SECONDS", "1800"))
        if len(files) > member_cap:
            result.error_message = f"FAILED_HEAVY_MEMBER_CAP: members={len(files)} cap={member_cap}"
            result.outcome = ProcessingOutcome.FAILED
            return result
        unpacked_bytes = 0
        for _p in files:
            try:
                unpacked_bytes += _p.stat().st_size
            except Exception:
                pass
        if size_cap and unpacked_bytes > size_cap:
            result.error_message = (
                f"FAILED_HEAVY_SIZE_CAP: unpacked_bytes={unpacked_bytes} cap={size_cap}"
            )
            result.outcome = ProcessingOutcome.FAILED
            return result
        started_monotonic = time.monotonic()

        for path in files:
            if time_cap and (time.monotonic() - started_monotonic) > time_cap:
                result.error_message = (
                    f"FAILED_HEAVY_WALL_CLOCK_CAP: seconds>{int(time_cap)} "
                    f"after {len(result.files)} files"
                )
                result.outcome = ProcessingOutcome.FAILED
                return result
            if _skip(path.name):
                parent_name, parent_path, member_path = _archive_parent_identity(path)
                result.files.append(FileProcessResult(
                    file_name=path.name,
                    status="SKIPPED",
                    error_message="Skipped by file_skip_list",
                    local_path=str(path),
                    parent_file_name=parent_name,
                    parent_local_path=parent_path,
                    archive_member_path=member_path,
                ))
                continue

            parent_name, parent_path, member_path = _archive_parent_identity(path)
            file_res = FileProcessResult(
                file_name=path.name,
                status="PROCESSING",
                local_path=str(path),
                parent_file_name=parent_name,
                parent_local_path=parent_path,
                archive_member_path=member_path,
            )
            try:
                text = ""
                line_meta = None
                finished_fully = True

                use_pdf_ocr = (
                    path.suffix.lower() == ".pdf"
                    and os.getenv("ENABLE_OCR", "0") == "1"
                    and os.getenv("ENABLE_OCR_PAGED", "1") == "1"
                )
                if use_pdf_ocr:
                    text, line_meta, finished_fully = parse_pdf_incremental(
                        path,
                        None, # tender_id = None so no DB writes during PDF processing
                        table_source,
                        self.downloader,
                        self.logger,
                        self.is_over_memory_limit,
                    )
                    if text is None:
                        raise RuntimeError("Ошибка при открытии/чтении PDF (возможно файл поврежден или зашифрован)")
                else:
                    # UNSUPPORTED_DOC_RECOVERY_V1: `.xls`/`.rtf` (и подобные) парсеров не
                    # имеют — конвертируем через soffice в `.xlsx`/`.docx` и разбираем
                    # результат; provenance остаётся по исходному `path.name`.
                    from document_processor.format_converter import convert_if_needed

                    parse_path = convert_if_needed(path)
                    parser = (
                        get_rich_parser(self.parser_factory, parse_path)
                        if supports_rich_meta(parse_path)
                        else self.parser_factory.get_parser(parse_path)
                    )
                    if parser is None:
                        file_res.status = "UNSUPPORTED"
                        file_res.error_message = f"Unsupported format: {path.suffix.lower() or path.name}"
                        result.files.append(file_res)
                        continue

                    text, line_meta = parse_file_with_meta(parser, parse_path)

                # Parse-time extraction (estimate tables + project metadata).
                # Retention removes raw files after 3 days, so anything we may
                # need later must be captured now, while the file is on disk.
                try:
                    from document_processor.parse_extractors import extract_and_persist

                    # ARCHIVE_MEMBER_PARSE_CONTEXT_V1: an extracted archive member is not a
                    # planned document by itself, so its own name is absent from
                    # selected_doc_context. Fall back to the parent archive's context
                    # (category / source_document_id / physical_key / track) so the member
                    # reaches _persist_embedded with a category_code. No value is invented:
                    # if the parent is not in the plan, ctx stays empty as before.
                    ctx = doc_ctx.get(str(path.name).strip().lower())
                    if not ctx and parent_name:
                        ctx = doc_ctx.get(str(parent_name).strip().lower())
                    ctx = ctx or {}
                    extract_and_persist(
                        parse_path, text, procurement_id, path.name,
                        category_code=ctx.get("category"),
                        source_document_id=ctx.get("source_document_id"),
                        physical_key=ctx.get("physical_key"),
                        track=ctx.get("track"),
                        line_meta=line_meta,
                    )
                except Exception as exc:  # never break parsing
                    self.logger.warning(
                        f"[{procurement_id}] parse-time extraction skipped: {exc}"
                    )

                if not finished_fully:
                    file_res.status = "FAILED"
                    file_res.error_message = "Прервано по лимиту памяти (S13_V2 не поддерживает resume)"
                elif not text:
                    file_res.status = "COMPLETED"
                else:
                    file_res.status = "COMPLETED"
                    engine = match_engine.for_categories(category_codes) if category_codes else match_engine
                    matches_dtos = engine.process_text(text, line_meta)
                    cat_map = {}
                    for d in matches_dtos:
                        if d.category_code not in cat_map:
                            cat_map[d.category_code] = []
                        cat_map[d.category_code].append(d)

                    for cat, details in cat_map.items():
                        score = max(d.score for d in details)
                        file_res.matches.append(MatchResult(
                            category_code=cat,
                            match_count=len(details),
                            score=score,
                            details=details
                        ))

            except Exception as e:
                file_res.status = "FAILED"
                file_res.error_message = str(e)

            result.files.append(file_res)

        # Calculate evidence using the new EvidenceAggregator
        from document_processor.evidence_aggregator import EvidenceAggregator
        result.evidence = EvidenceAggregator.aggregate(result.files)

        return result
