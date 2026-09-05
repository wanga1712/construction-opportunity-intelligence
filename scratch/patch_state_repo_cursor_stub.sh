#!/bin/bash
python3 << 'PYEOF'
filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/backends/state_repository.py'
with open(filepath, 'r') as f:
    content = f.read()

# Add stub to ProcessingStateRepository (base class)
old_base = '''    def mark_error_memory(self, tender_id: int, table_source: str, file_name: str, error_message: str):
        """S13_V2 stub: no-op for memory error tracking."""
        pass'''

new_base = '''    def mark_error_memory(self, tender_id: int, table_source: str, file_name: str, error_message: str):
        """S13_V2 stub: no-op for memory error tracking."""
        pass

    def set_progress_cursor(self, tender_id: int, table_source: str, file_name: str, cursor: int) -> None:
        """S13_V2 stub: no-op for progress cursor tracking."""
        pass'''

# Add stub to S13V2StateRepository (concrete class)
old_concrete = '''    def mark_error_memory(self, tender_id: int, table_source: str, file_name: str, error_message: str):
        pass'''

new_concrete = '''    def mark_error_memory(self, tender_id: int, table_source: str, file_name: str, error_message: str):
        pass

    def set_progress_cursor(self, tender_id: int, table_source: str, file_name: str, cursor: int) -> None:
        pass'''

if old_base in content:
    content = content.replace(old_base, new_base, 1)
    print("Base class patched.")
else:
    print("Base class pattern not found!")

if old_concrete in content:
    content = content.replace(old_concrete, new_concrete, 1)
    print("Concrete class patched.")
else:
    print("Concrete class pattern not found!")

with open(filepath, 'w') as f:
    f.write(content)
print("SUCCESS: State repository progress cursor stubs added.")
PYEOF

python3 -m py_compile /opt/CRM_Streamlit/tender_documents_research/document_processor/backends/state_repository.py && echo "SYNTAX_OK"
