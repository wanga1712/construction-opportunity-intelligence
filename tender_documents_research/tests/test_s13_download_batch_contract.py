
from pathlib import Path
from types import SimpleNamespace

from document_processor.downloader import DownloadBatchResult, Downloader
from document_processor.task_pipeline import TaskPipeline


class _NoLenBatch(DownloadBatchResult):
    pass


class _PipelineDownloader:
    def __init__(self):
        self.calls = []

    def build_registry_link(self, table_source, contract_number):
        return "https://example.invalid/card"

    def get_links(self, contract_reg_number, table_source):
        return [("https://example.invalid/file.pdf", "file.pdf")]

    def download_and_extract(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _NoLenBatch(
            source_links_count=1,
            attempted_count=1,
            downloaded_count=1,
            skipped_count=0,
            failed_count=0,
            files=[Path("file.pdf")],
            failures=[],
        )


class _FakeStateRepo:
    def __init__(self):
        self.ensure_calls = []
        self.finalize_calls = []
        self.attempts = []
        self.status = None
        self.local_path = None

    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name, source_id=None):
        self.ensure_calls.append((queue_id, procurement_id, table_source, url, url_hash, file_name, source_id))

    def get_file_status(self, procurement_id, table_source, file_name, url_hash):
        if self.status:
            return (self.status, self.local_path)
        return None

    def mark_file_status(self, *args, **kwargs):
        pass

    def finalize_download_status(self, procurement_id, table_source, file_name, url_hash, success, error_message=None, local_path=None):
        self.finalize_calls.append((procurement_id, table_source, file_name, url_hash, success, error_message, local_path))
        self.status = "COMPLETED" if success else "FAILED"
        self.local_path = str(local_path) if local_path else None

    def record_download_attempt(self, queue_id, procurement_id, source_url, url_hash, attempt_number, result, error_class=None, http_status=None, bytes_received=None, duration_ms=None):
        self.attempts.append((queue_id, procurement_id, source_url, url_hash, attempt_number, result, error_class, http_status, bytes_received, duration_ms))


class _ArchiveExtractor:
    def is_archive(self, path):
        return path.suffix == ".zip"


class _HttpClient:
    def sanitize_name(self, name):
        return name

    def predict_filename(self, url):
        return "predicted.zip"


def test_prefetch_task_returns_batch_and_uses_explicit_files_count():
    downloader = _PipelineDownloader()
    pipeline = TaskPipeline(
        db=None,
        downloader=downloader,
        parser_factory=None,
        matcher=None,
        enhancer=None,
        worker_id=16,
        failed_uploads_dir=Path("/tmp"),
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None),
        is_over_memory_limit=lambda: False,
    )

    batch = pipeline.prefetch_task(
        1,
        "0173200001424001779",
        "reestr_contract_44_fz_awarded",
        procurement_id=1282,
        source_id=316812,
    )

    assert isinstance(batch, DownloadBatchResult)
    assert batch.files == [Path("file.pdf")]
    assert downloader.calls[0][1]["procurement_id"] == 1282
    assert downloader.calls[0][1]["source_id"] == 316812


def _make_downloader(tmp_path, repo, download_result):
    downloader = Downloader.__new__(Downloader)
    downloader.state_repo = repo
    downloader.http_client = _HttpClient()
    downloader.archive_extractor = _ArchiveExtractor()
    downloader.logger = SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    downloader._is_rar_part = lambda path: False

    def _download_single(task_dir, url, suggested_filename=None):
        if download_result is None:
            return None
        path = task_dir / (suggested_filename or "predicted.zip")
        path.write_bytes(download_result)
        return path

    downloader._download_single = _download_single
    return downloader


def test_s13_download_persists_queue_procurement_id_source_id_and_success_attempt(tmp_path):
    repo = _FakeStateRepo()
    downloader = _make_downloader(tmp_path, repo, b"zip-bytes")

    files, failure = downloader._process_single_link(
        1,
        tmp_path,
        "https://zakupki.gov.ru/file.zip",
        "source.zip",
        1282,
        "reestr_contract_44_fz_awarded",
        None,
        None,
        source_id=316812,
    )

    assert failure is None
    assert files and files[0].exists()
    assert repo.ensure_calls[0][1] == 1282
    assert repo.ensure_calls[0][-1] == 316812
    assert repo.finalize_calls[0][0] == 1282
    assert repo.finalize_calls[0][4] is True
    assert repo.attempts[0][1] == 1282
    assert repo.attempts[0][5] == "SUCCESS"
    assert repo.attempts[0][8] == len(b"zip-bytes")


def test_s13_download_attempts_record_transient_and_permanent_failures(tmp_path):
    for url, expected_error_class in [
        ("https://zakupki.gov.ru/missing.zip", "TRANSIENT"),
        ("https://example.invalid/missing.zip", "PERMANENT"),
    ]:
        repo = _FakeStateRepo()
        downloader = _make_downloader(tmp_path, repo, None)
        files, failure = downloader._process_single_link(
            1,
            tmp_path,
            url,
            "missing.zip",
            1282,
            "reestr_contract_44_fz_awarded",
            None,
            None,
            source_id=316812,
        )
        assert files == []
        assert failure is not None
        assert repo.finalize_calls[-1][4] is False
        assert repo.attempts
        assert all(a[5] == "FAILED" for a in repo.attempts)
        assert repo.attempts[-1][6] == expected_error_class


def test_completed_file_reuse_records_skipped_and_does_not_call_http(tmp_path):
    repo = _FakeStateRepo()
    cached = tmp_path / "source.zip"
    cached.write_bytes(b"cached")
    repo.status = "COMPLETED"
    repo.local_path = str(cached)
    downloader = _make_downloader(tmp_path, repo, None)
    called = {"http": 0}

    def _download_single(*args, **kwargs):
        called["http"] += 1
        return None

    downloader._download_single = _download_single
    files, failure = downloader._process_single_link(
        1,
        tmp_path,
        "https://zakupki.gov.ru/file.zip",
        "source.zip",
        1282,
        "reestr_contract_44_fz_awarded",
        None,
        None,
        source_id=316812,
    )

    assert failure is None
    assert files == [cached]
    assert called["http"] == 0
    assert repo.attempts[0][5] == "SKIPPED"
