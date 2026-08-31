import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from document_processor.parsers.pdf_table_extractor import PdfTableExtractor


def _is_garbage_text(text: str) -> bool:
    """Текст с неверной кодировкой/шрифтом — нужен OCR."""
    if not text:
        return False

    total = len(text)
    if total < 50:
        return False

    cyrillic = sum(1 for ch in text if "а" <= ch <= "я" or "А" <= ch <= "Я" or ch in "ёЁ")
    latin = sum(1 for ch in text if "a" <= ch <= "z" or "A" <= ch <= "Z")

    if cyrillic / total < 0.05 and latin / total > 0.4:
        return True
    return False


def _ocr_page_text(path: Path, page_idx: int, logger) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError as exc:
        logger.error(f"OCR библиотеки не установлены: {exc}")
        return ""

    try:
        images = convert_from_path(str(path), first_page=page_idx + 1, last_page=page_idx + 1)
    except Exception as exc:
        logger.error(f"Ошибка конвертации PDF в изображение стр. {page_idx}: {exc}")
        return ""

    chunks: list[str] = []
    for img in images:
        try:
            ocr_text = pytesseract.image_to_string(img, lang="rus+eng", config="--psm 6")
        except Exception as exc:
            logger.error(f"OCR ошибка стр. {page_idx}: {exc}")
            continue
        if ocr_text:
            chunks.append(ocr_text)
    return "\n".join(chunks)


def parse_pdf_incremental(
    path: Path,
    tender_id: Optional[int],
    table_source: str,
    downloader,
    logger,
    is_over_memory_limit: Callable[[], bool],
) -> Tuple[str, Optional[Dict[int, Dict[str, Any]]], bool]:
    """
    Постраничный парсинг PDF с таблицами и OCR.
    Возвращает (текст, line_meta, флаг полного завершения).
    """
    try:
        import pdfplumber
        from PyPDF2 import PdfReader
    except ImportError as exc:
        logger.error(f"PDF библиотеки не установлены: {exc}")
        return "", None, False

    start_page = 0
    if tender_id is not None:
        start_page = downloader.state_repo.get_progress_cursor(tender_id, table_source, path.name) or 0

    try:
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
    except Exception as exc:
        logger.error(f"Не удалось открыть PDF {path.name}: {exc}")
        return "", None, False

    parts: list[str] = []
    line_meta: Dict[int, Dict[str, Any]] = {}
    table_extractor = PdfTableExtractor()
    use_ocr = os.getenv("ENABLE_OCR", "0") == "1"

    try:
        pdf = pdfplumber.open(str(path))
    except Exception as exc:
        logger.error(f"pdfplumber не открыл {path.name}: {exc}")
        pdf = None

    try:
        for page_idx in range(start_page, total_pages):
            if is_over_memory_limit():
                logger.warning(f"Память: прерываем OCR {path.name} на странице {page_idx}")
                if tender_id is not None:
                    downloader.state_repo.set_progress_cursor(
                        tender_id, table_source, path.name, page_idx
                    )
                return "\n".join(parts), line_meta or None, False

            page_number = page_idx + 1
            page = pdf.pages[page_idx] if pdf and page_idx < len(pdf.pages) else None
            plain_text = ""
            rows_added = 0

            if page is not None:
                try:
                    plain_text, rows_added = table_extractor.extract_page(
                        page,
                        page_number,
                        parts,
                        line_meta,
                        include_plain_text=False,
                    )
                    probe_text = plain_text
                    if not probe_text.strip():
                        try:
                            probe_text = page.extract_text() or ""
                        except Exception:
                            probe_text = ""
                    plain_text = probe_text

                    if plain_text.strip() and not _is_garbage_text(plain_text):
                        table_extractor.append_plain_page(
                            plain_text, page_number, parts, line_meta
                        )
                except Exception as exc:
                    logger.error(f"Ошибка извлечения стр. {page_number} в {path.name}: {exc}")

            need_ocr = use_ocr and rows_added == 0 and (
                not plain_text.strip() or _is_garbage_text(plain_text)
            )
            if need_ocr:
                if _is_garbage_text(plain_text):
                    logger.warning(
                        f"Мусорный текст на стр. {page_number} в {path.name}, запускаем OCR"
                    )
                ocr_text = _ocr_page_text(path, page_idx, logger)
                if ocr_text.strip():
                    table_extractor.append_ocr_page(ocr_text, page_number, parts, line_meta)
            elif rows_added == 0 and not plain_text.strip() and page is None:
                fallback_text = ""
                try:
                    fallback_text = reader.pages[page_idx].extract_text() or ""
                except Exception:
                    pass
                if fallback_text.strip() and not _is_garbage_text(fallback_text):
                    table_extractor.append_ocr_page(
                        fallback_text, page_number, parts, line_meta
                    )

            if tender_id is not None:
                downloader.state_repo.set_progress_cursor(
                    tender_id, table_source, path.name, page_number
                )
    finally:
        if pdf is not None:
            try:
                pdf.close()
            except Exception:
                pass

    return "\n".join(parts), line_meta or None, True
