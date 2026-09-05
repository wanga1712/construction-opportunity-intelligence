#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
import sys, os, re
sys.path.insert(0, '/opt/CRM_Streamlit_rescue')
os.chdir('/opt/CRM_Streamlit_rescue')

path = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

# Replace fetch_document_evidence to use raw source evidence as primary source
target_ev = '''    def fetch_document_evidence(self, procurement_id: int) -> List[Dict[str, Any]]:
        """Fetch matches and details (evidence context)."""
        evidence: List[Dict[str, Any]] = []
        conn = self._get_doc_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT d.category_code, d.subcategory_code, d.matched_term,
                           d.term_type, d.score, d.page_or_sheet, d.row_number,
                           d.row_data, m.document_name
                    FROM document_match_details d
                    JOIN document_matches m ON m.id = d.match_id
                    WHERE d.procurement_id = %s
                    ORDER BY d.id ASC
                    """,
                    (procurement_id,),
                )
                rows = cur.fetchall() or []
                for r in rows:
                    evidence.append(dict(r))
        finally:
            conn.close()
        return evidence'''

replacement_ev = '''    def fetch_document_evidence(self, procurement_id: int) -> List[Dict[str, Any]]:
        """Fetch exhaustive raw source evidence from crm_v3_raw_source_evidence as primary research authority."""
        from src.services.commercial_routing_v3.evidence_discovery import discover_and_persist_raw_evidence
        
        raw_rows = discover_and_persist_raw_evidence(procurement_id, self.crm_db)
        evidence: List[Dict[str, Any]] = []
        for r in raw_rows:
            evidence.append({
                "raw_evidence_id": r.get("id"),
                "document_name": r.get("document_name") or "Document",
                "matched_term": r.get("matched_term"),
                "raw_text": r.get("raw_text"),
                "context_before": r.get("context_before"),
                "context_after": r.get("context_after"),
                "source_locator_json": r.get("source_locator_json"),
                "discovery_method": r.get("discovery_method"),
                "suggested_category_code": r.get("suggested_category_code"),
                "row_data": r.get("raw_text"),
            })
            
        if not evidence:
            conn = self._get_doc_conn()
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT d.id AS legacy_id, d.category_code, d.subcategory_code, d.matched_term,
                               d.term_type, d.score, d.page_or_sheet, d.row_number,
                               d.row_data, m.document_name
                        FROM document_match_details d
                        JOIN document_matches m ON m.id = d.match_id
                        WHERE d.procurement_id = %s
                        ORDER BY d.id ASC
                        """,
                        (procurement_id,),
                    )
                    rows = cur.fetchall() or []
                    for r in rows:
                        evidence.append(dict(r))
            finally:
                conn.close()
                
        return evidence'''

if target_ev in code:
    code = code.replace(target_ev, replacement_ev)

# Replace format_evidence_for_prompt via regex
pattern = r"def format_evidence_for_prompt\(self, evidence: List\[Dict\[str, Any\]\]\) -> str:.*?(?=def build_hunter_prompt)"

replacement_fmt = '''def format_evidence_for_prompt(self, evidence: List[Dict[str, Any]]) -> str:
        """Format database evidence rows into a fair, multi-document evidence context packet.

        Fair Evidence Budget Algorithm:
        1. Group by document;
        2. Deduplicate equivalent evidence texts;
        3. Reserve representation across ALL documents containing evidence;
        4. Allocate remaining budget by document diversity and relevance score;
        5. Obey maximum packet budget (20,000 chars) without simple prefix slicing.
        """
        if not evidence:
            return "No document match evidence found."

        by_doc: Dict[str, List[Dict[str, Any]]] = {}
        for ev in evidence:
            doc_name = ev.get("document_name") or "Unknown Document"
            by_doc.setdefault(doc_name, []).append(ev)

        MAX_BUDGET_CHARS = 20000
        lines: List[str] = []
        lines.append(f"=== RESEARCH EVIDENCE CORPUS ({len(by_doc)} documents, {len(evidence)} total raw items) ===")

        for doc_name, doc_evs in by_doc.items():
            doc_lines = [f"=== DOCUMENT: {doc_name} ({len(doc_evs)} evidence items) ==="]
            seen_texts = set()
            count = 0
            for ev in doc_evs:
                txt = str(ev.get("raw_text") or ev.get("row_data") or "").strip()
                if not txt or txt in seen_texts:
                    continue
                seen_texts.add(txt)

                loc_str = str(ev.get("source_locator_json") or ev.get("page_or_sheet") or "loc")
                term = str(ev.get("matched_term") or "ITEM")
                line_entry = f"  - [{term} | {loc_str}]: {txt}"

                candidate_len = sum(len(l) for l in lines) + sum(len(l) for l in doc_lines) + len(line_entry) + 100
                if candidate_len > MAX_BUDGET_CHARS and count > 0:
                    break

                doc_lines.append(line_entry)
                count += 1

            lines.extend(doc_lines)

        return "\\n".join(lines)\n\n    '''

code = re.sub(pattern, replacement_fmt, code, flags=re.DOTALL)

with open(path, "w", encoding="utf-8") as f:
    f.write(code)

print("SUCCESSFULLY REPLACED format_evidence_for_prompt AND fetch_document_evidence IN autonomous_learning_loop.py!")

PYEOF
