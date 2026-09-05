#!/usr/bin/env python3
"""Audit database authorities for categories, commercial medals, facts, quantities, prices, and evidence."""

import os
import sys
from typing import Dict, Any, List

def audit_authorities():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    # S13 connection
    s13_conn = psycopg2.connect(
        host=os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.getenv("S13_DOCUMENT_DB_PASSWORD", "S13_Sec_9901_Docs!")
    )
    
    report = {}
    
    with s13_conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Check tables in document_intelligence
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
        tables = [r['tablename'] for r in cur.fetchall()]
        report['S13_TABLES'] = tables
        
        # Check columns of structured_entities if present
        if 'structured_entities' in tables:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='structured_entities';")
            report['STRUCTURED_ENTITIES_COLS'] = [r['column_name'] for r in cur.fetchall()]
            
        # Check columns of document_match_details if present
        if 'document_match_details' in tables:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='document_match_details';")
            report['MATCH_DETAILS_COLS'] = [r['column_name'] for r in cur.fetchall()]

        # Check columns of document_evidence if present
        if 'document_evidence' in tables:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='document_evidence';")
            report['EVIDENCE_COLS'] = [r['column_name'] for r in cur.fetchall()]

    s13_conn.close()
    return report

if __name__ == "__main__":
    rep = audit_authorities()
    print("AUTHORITY AUDIT REPORT:")
    for k, v in rep.items():
        print(f"  {k}: {v}")
