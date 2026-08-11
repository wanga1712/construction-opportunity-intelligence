import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from document_processor.downloader import Downloader

@pytest.fixture
def temp_data_dir(tmp_path):
    os.environ['DOCUMENT_STORAGE_ROOT'] = str(tmp_path)
    os.environ['TMPDIR'] = str(tmp_path / 'temp')
    os.environ['REPROCESS_COMPLETED'] = '0'
    yield tmp_path

@patch('document_processor.downloader.HttpFileClient')
@patch('document_processor.downloader.DownloadCoordinator')
def test_resume_semantics_get_0(mock_coord_class, mock_http_client_class, temp_data_dir):
    mock_http_client = mock_http_client_class.return_value
    mock_http_client.get_head.return_value = (200, 1024, 'abc')
    mock_http_client.try_download_direct.return_value = temp_data_dir / 'downloaded.pdf'
    mock_http_client.predict_filename.return_value = 'test.pdf'
    mock_http_client.sanitize_name.return_value = 'test.pdf'
    
    mock_coord = mock_coord_class.return_value
    mock_coord.wait_for_slot.return_value = None

    mock_state_repo = MagicMock()
    # Mock get_file_status to return COMPLETED so we skip downloading
    mock_state_repo.get_file_status.return_value = ('COMPLETED',)
    
    mock_db = MagicMock()
    
    # Pre-create a 'durable local file' in all possible task_dirs
    (temp_data_dir / '123').mkdir(parents=True, exist_ok=True)
    (temp_data_dir / '123' / 'test.pdf').write_text('dummy content')
    
    (temp_data_dir / 'tender_monitor' / '123').mkdir(parents=True, exist_ok=True)
    (temp_data_dir / 'tender_monitor' / '123' / 'test.pdf').write_text('dummy content')
    
    (temp_data_dir / 'tender_documents_research' / '123').mkdir(parents=True, exist_ok=True)
    (temp_data_dir / 'tender_documents_research' / '123' / 'test.pdf').write_text('dummy content')

    downloader = Downloader(
        base_dir=temp_data_dir,
        db=mock_db,
        state_repo=mock_state_repo,
    )
    # Inject our mock
    downloader.http_client = mock_http_client
    downloader.download_coordinator = mock_coord

    url = 'http://example.com/test.pdf'
    
    res = downloader.download_and_extract(
        task_id=123,
        links=[(url, 'test.pdf')],
        table_source='tender_monitor',
        contract_number='123'
    )

    # Validate that we did NOT call any HTTP GET
    mock_http_client.try_download_direct.assert_not_called()
    mock_http_client.try_download_with_proxy.assert_not_called()
    assert res.failed_count == 0
