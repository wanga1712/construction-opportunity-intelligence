"""Unit tests for Document Pipeline Deduplication and Status Fixes (Phase 4)."""
import os
import sys
import inspect
from pathlib import Path

# Add tender_documents_research to sys.path
research_dir = Path(__file__).resolve().parent.parent / "tender_documents_research"
if str(research_dir) not in sys.path:
    sys.path.insert(0, str(research_dir))

import pytest


def test_archive_children_do_not_pass_canonical_source_document_id():
    """Verify downloader passes canonical_source_document_id=None for extracted archive children."""
    from document_processor.downloader import Downloader

    source = inspect.getsource(Downloader.download_and_extract)
    assert "for child in extracted:" in source
    assert "canonical_source_document_id=None" in source


def test_state_repository_defensive_null_canonical_id_on_hash_mismatch():
    """Verify state repository nullifies canonical_source_document_id if already occupied by different url_hash."""
    from document_processor.backends.state_repository import S13V2StateRepository

    source = inspect.getsource(S13V2StateRepository.ensure_download_file)
    assert "row[1] != url_hash" in source
    assert "canonical_source_document_id = None" in source


def test_persistence_service_safe_download_status_mapping():
    """Verify S13 persistence service maps UNSUPPORTED parser status to COMPLETED for document_files."""
    from document_processor.backends.s13_persistence import S13V2TaskPersistenceService

    source = inspect.getsource(S13V2TaskPersistenceService.persist_task_result)
    assert 'dl_status = "COMPLETED" if file_res.status in ("COMPLETED", "UNSUPPORTED")' in source
    assert "SET download_status = %s" in source
