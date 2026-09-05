#!/bin/bash
# Fix queue_repository.py - replace escaped triple-quotes with real triple-quotes
FILE="/opt/CRM_Streamlit/tender_documents_research/document_processor/backends/queue_repository.py"
cp $FILE ${FILE}.bak_20260829

# Count the occurrences
echo "BEFORE_FIX: $(grep -c '\\\"\\\"\\\"' $FILE) escaped triple-quotes"

# Replace \\\"\\\"\\\" with """ in-place
# The actual file has literal backslash-quote sequences
sed -i 's/\\\"\\\"\\\"$/"""/g' $FILE
# Also handle those at start of expressions
sed -i 's/^                \\\"\\\"\\\"$/                """/g' $FILE

# But sed replacement might be tricky with these patterns. Let's use python instead.
python3 << 'PYEOF'
import re

filepath = '/opt/CRM_Streamlit/tender_documents_research/document_processor/backends/queue_repository.py'
with open(filepath, 'r') as f:
    content = f.read()

# The file has literally: \"\"\" (backslash double-quote triple times)
# but we need: """  
# Check what's in the file
problem = '\\"\\"\\"'
solution = '"""'
count = content.count(problem)
print(f'Found {count} instances of escaped triple-quotes')

fixed = content.replace(problem, solution)
with open(filepath, 'w') as f:
    f.write(fixed)
print('FIXED')
PYEOF

echo ""
python3 -m py_compile $FILE && echo "SYNTAX_OK" || echo "SYNTAX_STILL_BROKEN"
