#!/bin/bash
set -e

echo "=== Step 1: Setup production deploy directory ==="
# The code lives at /opt/CRM_Streamlit/tender_documents_research/
# The service expects it at /opt/tender_documents_research/
# Solution: populate /opt/tender_documents_research/ with symlinks + create venv there

DEPLOY_DIR=/opt/tender_documents_research
CODE_DIR=/opt/CRM_Streamlit/tender_documents_research

# Create symlink for document_processor module
ln -sf $CODE_DIR/document_processor $DEPLOY_DIR/document_processor 2>/dev/null || echo "symlink exists or failed"
ln -sf $CODE_DIR/requirements.txt $DEPLOY_DIR/requirements.txt 2>/dev/null || echo "req symlink"
ln -sf $CODE_DIR/smart_text_extractor.py $DEPLOY_DIR/smart_text_extractor.py 2>/dev/null || echo "smart_text symlink"
ls -la $DEPLOY_DIR/

echo ""
echo "=== Step 2: Create venv at /opt/tender_documents_research/.venv ==="
if [ ! -f $DEPLOY_DIR/.venv/bin/python ]; then
    python3 -m venv $DEPLOY_DIR/.venv
    echo "Venv created"
else
    echo "Venv already exists"
fi

echo ""
echo "=== Step 3: Install dependencies ==="
$DEPLOY_DIR/.venv/bin/pip install -q --upgrade pip
$DEPLOY_DIR/.venv/bin/pip install -q psycopg2-binary requests openpyxl pdfplumber python-docx loguru rapidfuzz pdf2image pytesseract psutil python-dotenv PyPDF2
echo "DEPS_INSTALLED=OK"

echo ""
echo "=== Step 4: Check fitz/pymupdf ==="
$DEPLOY_DIR/.venv/bin/pip install -q pymupdf 2>&1 | tail -3
$DEPLOY_DIR/.venv/bin/python -c "import fitz; print('fitz OK')" 2>&1 || echo "fitz not available (not critical)"

echo ""
echo "=== Step 5: Verify daemon can import ==="
PYTHONPATH=$DEPLOY_DIR $DEPLOY_DIR/.venv/bin/python -c "from document_processor.daemon import main; print('DAEMON_IMPORT_OK')" 2>&1

echo ""
echo "=== Step 6: Setup env file ==="
# The service reads /opt/tender_documents_research/.env
# Add CRM app credentials for writing to document_intelligence
cat > /tmp/tender_docs_env_addon <<'ENVEOF'
S13_DOCUMENT_DB_HOST=127.0.0.1
S13_DOCUMENT_DB_PORT=5432
S13_DOCUMENT_DB_NAME=document_intelligence
S13_DOCUMENT_DB_USER=doc_worker
S13_DOCUMENT_DB_PASSWORD=F6VaPWQIIYgDF3I8_kBTyDJhYpzWw1bT
CRM_DB_HOST=127.0.0.1
CRM_DB_PORT=5432
CRM_DB_DATABASE=crm
CRM_DB_USER=crm_app
CRM_DB_PASSWORD=X17B3n5hbANQSRt6i7WIyy0lJudX
ENVEOF

# Create/update the .env file in deploy dir
if [ -f $DEPLOY_DIR/.env ]; then
    echo "Existing .env:"
    cat $DEPLOY_DIR/.env
else
    cp /tmp/tender_docs_env_addon $DEPLOY_DIR/.env
    echo "Created $DEPLOY_DIR/.env"
fi

echo ""
echo "DEPLOY_SETUP_COMPLETE=YES"
