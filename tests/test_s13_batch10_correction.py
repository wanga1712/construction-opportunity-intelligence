from __future__ import annotations

import inspect
from pathlib import Path

import pytest


def test_child_hash_is_deterministic_and_path_sensitive() -> None:
    from tender_documents_research.document_processor.downloader import Downloader

    task_dir = Path("/tmp/task")
    parent = "a" * 64
    first = Downloader._child_url_hash(parent, task_dir / "nested" / "a.docx", task_dir)
    repeat = Downloader._child_url_hash(parent, task_dir / "nested" / "a.docx", task_dir)
    other_path = Downloader._child_url_hash(parent, task_dir / "other" / "a.docx", task_dir)
    other_parent = Downloader._child_url_hash("b" * 64, task_dir / "nested" / "a.docx", task_dir)

    assert first == repeat
    assert first != other_path
    assert first != other_parent
    assert len(first) == 64


def test_state_repository_rolls_back_and_reuses_connection() -> None:
    from tender_documents_research.document_processor.backends.state_repository import S13V2StateRepository

    class Cursor:
        def __init__(self) -> None:
            self.fail = True
            self.rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args):
            if self.fail:
                self.fail = False
                raise RuntimeError("intentional SQL failure")

        def fetchone(self):
            return None

    class Connection:
        closed = False

        def __init__(self) -> None:
            self.cursor_obj = Cursor()
            self.rollbacks = 0
            self.commits = 0

        def cursor(self):
            return self.cursor_obj

        def rollback(self):
            self.rollbacks += 1

        def commit(self):
            self.commits += 1

    conn = Connection()
    repo = S13V2StateRepository({}, pipeline_generation="TEST")
    repo._conn = conn

    with pytest.raises(RuntimeError, match="intentional SQL failure"):
        repo.ensure_download_file(1, 2, "table", "url", "hash", "name")
    assert conn.rollbacks == 1

    repo.ensure_download_file(1, 2, "table", "url", "hash", "name")
    assert conn.commits == 1
    assert conn.rollbacks == 1


def test_dwrr_claim_does_not_lock_union() -> None:
    from tender_documents_research.document_processor.backends.queue_repository import S13V2QueueRepository

    source = inspect.getsource(S13V2QueueRepository.claim_batch)
    assert 'select_sql = " UNION ALL"' not in source
    assert "subpools = [" in source
    assert all(name in source for name in ('"GOLD"', '"SILVER"', '"BRONZE"', '"WOOD"'))
    assert "SKIP LOCKED" in source
    assert "select_from_pool" in source
