
from pathlib import Path
from types import SimpleNamespace

import pytest

from document_processor.daemon import DocumentProcessorDaemon
from document_processor.downloader import Downloader
from document_processor.dto import ProcessingOutcome, TaskProcessResult


class _Repo:
    def __init__(self, status=None, local_path=None):
        self.status = status
        self.local_path = local_path
        self.marked = []
        self.attempts = []
        self.ensure = []
        self.finalize = []

    def ensure_download_file(self, queue_id, procurement_id, table_source, url, url_hash, file_name, source_id=None):
        self.ensure.append((queue_id, procurement_id, source_id, url_hash, file_name))

    def get_file_status(self, procurement_id, table_source, file_name, url_hash):
        if self.status:
            return (self.status, self.local_path)
        return None

    def mark_file_status(self, procurement_id, table_source, file_name, url_hash, status, worker_id=None):
        self.marked.append((procurement_id, file_name, url_hash, status))
        self.status = status

    def finalize_download_status(self, procurement_id, table_source, file_name, url_hash, success, error_message=None, local_path=None):
        self.finalize.append((procurement_id, file_name, url_hash, success, error_message, local_path))
        self.status = "COMPLETED" if success else "FAILED"
        self.local_path = str(local_path) if local_path else self.local_path

    def record_download_attempt(self, *args, **kwargs):
        self.attempts.append((args, kwargs))


class _HttpClient:
    def __init__(self):
        self.gets = 0

    def sanitize_name(self, value):
        return value

    def predict_filename(self, url):
        return "source.zip"


def _downloader(tmp_path, storage_root, repo, download_bytes=b"new"):
    d = Downloader.__new__(Downloader)
    d.base_dir = storage_root / "downloads-open"
    d.base_dir.mkdir(parents=True, exist_ok=True)
    d.approved_storage_root = storage_root.resolve()
    d.state_repo = repo
    d.http_client = _HttpClient()
    d.archive_extractor = SimpleNamespace(is_archive=lambda p: False)
    d.logger = SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    d._is_rar_part = lambda path: False

    def _download_single(task_dir, url, suggested_filename=None):
        d.http_client.gets += 1
        if download_bytes is None:
            return None
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / (suggested_filename or "source.zip")
        path.write_bytes(download_bytes)
        return path

    d._download_single = _download_single
    return d


def test_s13_single_task_path_enters_s13_pipeline_not_legacy_task_kwargs():
    daemon = DocumentProcessorDaemon.__new__(DocumentProcessorDaemon)
    daemon.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    daemon.match_engine = object()
    calls = {"prefetch": 0, "s13": 0, "legacy": 0, "persist": 0, "completed": 0}

    daemon.pipeline = SimpleNamespace(
        prefetch_task=lambda *args, **kwargs: SimpleNamespace(files=[Path("fixture.txt")], failed_count=0, failures=[]),
        process_task_with_files=lambda *args, **kwargs: calls.__setitem__("legacy", calls["legacy"] + 1),
    )

    def process_task(**kwargs):
        calls["s13"] += 1
        assert kwargs["queue_id"] == 1
        assert kwargs["procurement_id"] == 1282
        assert kwargs["contract_reg_number"] == "0173200001424001779"
        assert kwargs["table_source"] == "reestr_contract_44_fz_awarded"
        assert kwargs["files"] == [Path("fixture.txt")]
        return TaskProcessResult(procurement_id=1282, queue_id=1, outcome=ProcessingOutcome.SUCCESS, files=[SimpleNamespace(status="COMPLETED")])

    daemon.s13_pipeline = SimpleNamespace(process_task=process_task)
    daemon.s13_persistence = SimpleNamespace(persist_task_result=lambda result: calls.__setitem__("persist", calls["persist"] + 1))
    daemon.s13_backend = SimpleNamespace(queue=SimpleNamespace(mark_completed=lambda task_id: calls.__setitem__("completed", calls["completed"] + 1), mark_failed=lambda *a, **k: None, mark_no_links=lambda *a, **k: None, mark_pending=lambda *a, **k: None))

    daemon._process_s13v2_task({
        "id": 1,
        "procurement_id": 1282,
        "source_id": 316812,
        "source_table": "reestr_contract_44_fz_awarded",
        "contract_number": "0173200001424001779",
    })

    assert calls["s13"] == 1
    assert calls["legacy"] == 0
    assert calls["persist"] == 1
    assert calls["completed"] == 0  # persistence owns atomic completion guard


def test_s13_download_root_uses_storage_root_and_invalid_root_fails_closed(tmp_path, monkeypatch):
    daemon = DocumentProcessorDaemon.__new__(DocumentProcessorDaemon)
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("DOCUMENT_STORAGE_ROOT", str(root))
    monkeypatch.delenv("DOCUMENT_DOWNLOAD_DIR", raising=False)
    assert daemon._resolve_download_base_dir("S13_V2") == root / "downloads-open"

    monkeypatch.setenv("DOCUMENT_DOWNLOAD_DIR", str(tmp_path / "elsewhere"))
    with pytest.raises(RuntimeError):
        daemon._resolve_download_base_dir("S13_V2")

    monkeypatch.delenv("DOCUMENT_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("DOCUMENT_DOWNLOAD_DIR", raising=False)
    with pytest.raises(RuntimeError):
        daemon._resolve_download_base_dir("S13_V2")


def test_s13_off_root_completed_row_is_not_reused_and_redownloads_to_data(tmp_path):
    data_root = tmp_path / "data"
    off_root = tmp_path / "opt" / "downloads" / "1"
    off_root.mkdir(parents=True)
    off_file = off_root / "source.zip"
    off_file.write_bytes(b"old")
    repo = _Repo(status="COMPLETED", local_path=str(off_file))
    d = _downloader(tmp_path, data_root, repo, b"new")

    files, failure = d._process_single_link(1, data_root / "downloads-open" / "1", "https://example.invalid/source.zip", "source.zip", 1282, "source_table", None, None, source_id=316812)

    assert failure is None
    assert d.http_client.gets == 1
    assert repo.marked[-1][-1] == "PENDING"
    assert files[0].resolve().is_relative_to(data_root.resolve())
    assert repo.finalize[-1][5].resolve().is_relative_to(data_root.resolve())


def test_s13_valid_data_completed_row_reuse_get_0(tmp_path):
    data_root = tmp_path / "data"
    data_file = data_root / "downloads-open" / "1" / "source.zip"
    data_file.parent.mkdir(parents=True)
    data_file.write_bytes(b"cached")
    repo = _Repo(status="COMPLETED", local_path=str(data_file))
    d = _downloader(tmp_path, data_root, repo, b"new")

    files, failure = d._process_single_link(1, data_file.parent, "https://example.invalid/source.zip", "source.zip", 1282, "source_table", None, None, source_id=316812)

    assert failure is None
    assert files == [data_file]
    assert d.http_client.gets == 0
    assert repo.attempts[0][0][5] == "SKIPPED"
