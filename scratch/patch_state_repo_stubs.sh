#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/backends/state_repository.py'
with open(filepath, 'r') as f:
    content = f.read()

# Add stub methods to S13V2StateRepository after list_file_statuses
old = '    def list_file_statuses(self, procurement_id: int, table_source: str, raise_on_error: bool = False):'
new = '''    # ─── Resumable download stubs (S13_V2 clean-slate: no resume logic needed) ─
    def get_progress_cursor(self, tender_id: int, table_source: str, file_name: str):
        """S13_V2 stub: no resume cursor tracking. Always returns None."""
        return None

    def get_processed_status(self, tender_id: int, table_source: str, file_name: str):
        """S13_V2 stub: no resume status tracking. Always returns None."""
        return None

    def mark_pending_resume(self, tender_id: int, table_source: str, file_name: str, cursor, error_message: str = None) -> int:
        """S13_V2 stub: return 0 attempts to prevent error_memory escalation."""
        return 0

    def mark_error_memory(self, tender_id: int, table_source: str, file_name: str, error_message: str):
        """S13_V2 stub: no-op for memory error tracking."""
        pass
    # ─────────────────────────────────────────────────────────────────────────

    def list_file_statuses(self, procurement_id: int, table_source: str, raise_on_error: bool = False):'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print('PATCHED S13V2StateRepository: added resume stub methods')
else:
    print('PATTERN NOT FOUND')
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/backends/state_repository.py && echo "SYNTAX_OK"
