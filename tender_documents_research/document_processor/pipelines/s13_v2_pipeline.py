import os
from pathlib import Path
from document_processor.pdf_processor import parse_pdf_incremental
from document_processor.parse_utils import get_rich_parser, parse_file_with_meta, supports_rich_meta

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
        match_engine
    ):
        """
        Pure compute processing for S13_V2. No DB writes.
        Returns dto.TaskProcessResult.
        """
        from document_processor.dto import TaskProcessResult, ProcessingOutcome, FileProcessResult, MatchResult, EvidenceResult
        from document_processor.file_skip_list import should_skip_file

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

        for path in files:
            if should_skip_file(path.name):
                result.files.append(FileProcessResult(
                    file_name=path.name,
                    status="SKIPPED",
                    error_message="Skipped by file_skip_list"
                ))
                continue

            file_res = FileProcessResult(file_name=path.name, status="PROCESSING")
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
                    parser = (
                        get_rich_parser(self.parser_factory, path)
                        if supports_rich_meta(path)
                        else self.parser_factory.get_parser(path)
                    )
                    if parser is None:
                        raise RuntimeError(f"Неподдерживаемый формат: {path.name}")

                    text, line_meta = parse_file_with_meta(parser, path)

                if not finished_fully:
                    file_res.status = "FAILED"
                    file_res.error_message = "Прервано по лимиту памяти (S13_V2 не поддерживает resume)"
                elif not text:
                    file_res.status = "COMPLETED"
                else:
                    file_res.status = "COMPLETED"
                    matches_dtos = match_engine.process_text(text, line_meta)
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
