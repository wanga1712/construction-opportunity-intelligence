#!/bin/bash
set -eu
cd /opt/CRM_Streamlit_rescue

PYTHONPATH=/opt/CRM_Streamlit_rescue:/opt/pythonProject89 \
/opt/CRM_Streamlit/.venv313/bin/python << 'PYEOF'
path_loop = "/opt/CRM_Streamlit_rescue/src/services/commercial_routing_v3/autonomous_learning_loop.py"

with open(path_loop, "r", encoding="utf-8") as f:
    code = f.read()

target = '''    def format_evidence_for_prompt(self, evidence: List[Dict[str, Any]]) -> str:
        """Format database evidence rows into a canonical text structure for LLM prompts."""
        evidence_lines = []
        for ev in evidence:
            evidence_lines.append(
                f"- Doc: {ev.get('document_name')}, Page/Sheet: {ev.get('page_or_sheet') or 'N/A'}, "
                f"Row: {ev.get('row_number') or 'N/A'}, Text: {ev.get('row_data') or 'N/A'}, "
                f"Matched: {ev.get('matched_term') or 'N/A'}, "
                f"Cat/Subcat: {ev.get('category_code')}/{ev.get('subcategory_code')}"
            )
        return "\\n".join(evidence_lines)'''

replacement = '''    def format_evidence_for_prompt(self, evidence: List[Dict[str, Any]]) -> str:
        """Format database evidence rows into a grouped, deduplicated canonical text packet."""
        if not evidence:
            return "No document match evidence found."

        # Group by document
        by_doc: Dict[str, List[Dict[str, Any]]] = {}
        for ev in evidence:
            doc_name = ev.get("document_name") or "Unknown Document"
            by_doc.setdefault(doc_name, []).append(ev)

        lines = []
        for doc_name, doc_evs in by_doc.items():
            lines.append(f"=== DOCUMENT: {doc_name} ({len(doc_evs)} matches) ===")
            seen_texts = set()
            for ev in doc_evs[:30]:  # up to 30 top matches per document
                txt = str(ev.get("row_data") or "").strip()
                matched = str(ev.get("matched_term") or "").strip()
                key = (txt, matched)
                if key in seen_texts:
                    continue
                seen_texts.add(key)
                loc = f"Page/Sheet: {ev.get('page_or_sheet') or 'N/A'}, Row: {ev.get('row_number') or 'N/A'}"
                cat_info = f"Cat/Subcat: {ev.get('category_code') or 'N/A'}/{ev.get('subcategory_code') or 'N/A'}"
                lines.append(f"  - [{loc}] Matched: '{matched}' | {cat_info} | Text: {txt[:250]}")

        res = "\\n".join(lines)
        if len(res) > 15000:
            res = res[:15000] + "\\n... [evidence context truncated to 15k budget]"
        return res'''

assert target in code, "format_evidence_for_prompt target not found"

code = code.replace(target, replacement)

with open(path_loop, "w", encoding="utf-8") as f:
    f.write(code)

print("UPDATED format_evidence_for_prompt IN autonomous_learning_loop.py WITH GROUPED & DEDUPLICATED PACKET BUILDER!")
PYEOF
