import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from document_processor.downloader import Downloader
from document_processor.backends.state_repository import S7StateRepository
from document_processor.concurrency_manager import DownloadCoordinator
from urllib.parse import urlparse

@pytest.fixture
def temp_data_dir(tmp_path):
    os.environ['DOCUMENT_STORAGE_ROOT'] = str(tmp_path)
    os.environ['TMPDIR'] = str(tmp_path / 'temp')
    yield tmp_path

def test_resume_semantics_get_0(temp_data_dir):
    # Setup mocks
    mock_http_client = MagicMock()
    mock_http_client.get_head.return_value = (200, 1024, 'abc')
    mock_http_client.try_download_direct.return_value = temp_data_dir / 'downloaded.pdf'

    mock_state_repo = MagicMock(spec=S7StateRepository)
    mock_state_repo.check_file_exists.return_value = True

    # Pre-create a 'durable local file'
    task_dir = temp_data_dir / 'tender_monitor' / 'test_dir'
    task_dir.mkdir(parents=True)
    durable_file = task_dir / '123_test.pdf'
    durable_file.write_text('dummy content')

    downloader = Downloader(
        http_client=mock_http_client,
        download_coordinator=MagicMock(),
        state_repo=mock_state_repo,
        logger=MagicMock()
    )

    # First attempt: file already exists locally and in db (state_repo.check_file_exists=True)
    url = 'http://example.com/test.pdf'
    url_hash = 'abc123hash'
    
    # We patch the internals if necessary, but the logic should return the existing file without GET
    # Let's check how downloader actually does it
    res_files, fail = downloader.process_url(
        url=url,
        task_dir=task_dir,
        tender_id=123,
        table_source='tender_monitor',
        bypass_proxy=False,
        suggested_filename='test.pdf'
    )

    # Validate that we did NOT call any HTTP GET (try_download_direct or with_proxy)
    mock_http_client.try_download_direct.assert_not_called()
    mock_http_client.try_download_with_proxy.assert_not_called()
    assert fail is None
    assert len(res_files) == 1
