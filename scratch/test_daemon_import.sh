#!/bin/bash
PYTHONPATH=/opt/tender_documents_research /opt/tender_documents_research/.venv/bin/python -c "from document_processor.daemon import main; print('DAEMON_IMPORT_OK')" 2>&1
