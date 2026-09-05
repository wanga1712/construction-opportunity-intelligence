#!/usr/bin/env python3
"""
Full application of R3-4F-B Document Context Trust Boundary Repair.
Updates context_validator.py and context_validator_service.py.
"""
import os
import re

VAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

# 1. Update context_validator.py
with open(VAL_PATH, "r", encoding="utf-8") as f:
    val_src = f.read()

# Make sure version constants are v3
val_src = val_src.replace('VALIDATOR_VERSION = "v2"', 'VALIDATOR_VERSION = "v3"')
val_src = val_src.replace('VALIDATOR_VERSION = "v1"', 'VALIDATOR_VERSION = "v3"')
val_src = val_src.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V2"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V3"')
val_src = val_src.replace('VALIDATION_METHOD = "QWEN_CONTEXT_V1"', 'VALIDATION_METHOD = "QWEN_CONTEXT_V3"')
val_src = val_src.replace('PROMPT_VERSION = "context_validator_v2"', 'PROMPT_VERSION = "context_validator_v3"')
val_src = val_src.replace('PROMPT_VERSION = "context_validator_v1"', 'PROMPT_VERSION = "context_validator_v3"')

# Insert build_document_context helper function
doc_ctx_helper = '''
def build_document_context(candidate: Dict[str, Any]) -> str:
    """Single authority for documentary factual text ONLY.

    Contains ONLY context_before, matched_line, and context_after.
    Excludes all metadata (procurement title, OKPD, category, subcategory, term,
    stop-phrase lists, questions, system instructions).
    """
    c_hydrated = hydrate_candidate_context(candidate)
    before_list = c_hydrated.get("context_before") or []
    after_list = c_hydrated.get("context_after") or []
    m_line = c_hydrated.get("matched_line") or ""

    if isinstance(before_list, str):
        if before_list.startswith("[") and before_list.endswith("]"):
            try:
                before_list = json.loads(before_list)
            except Exception:
                pass
    before_str = "\\n".join(str(x) for x in before_list if x) if isinstance(before_list, list) else str(before_list)

    if isinstance(after_list, str):
        if after_list.startswith("[") and after_list.endswith("]"):
            try:
                after_list = json.loads(after_list)
            except Exception:
                pass
    after_str = "\\n".join(str(x) for x in after_list if x) if isinstance(after_list, list) else str(after_list)

    parts = []
    if before_str:
        parts.append(before_str)
    if m_line:
        parts.append(m_line)
    if after_str:
        parts.append(after_str)

    return "\\n".join(parts)
'''

if "def build_document_context(" not in val_src:
    idx = val_src.find("def hydrate_candidate_context(")
    assert idx != -1, "hydrate_candidate_context not found"
    val_src = val_src[:idx] + doc_ctx_helper + "\n\n" + val_src[idx:]

# Update build_context_block method
new_build_context_block = '''    def build_context_block(self, candidate: Dict[str, Any]) -> str:
        """Constructs a bounded, informative context block for Qwen with centered budget."""
        candidate = hydrate_candidate_context(candidate)
        pid = candidate.get("procurement_id", "")
        okpd_code = candidate.get("procurement_okpd_code", "")
        okpd_name = candidate.get("procurement_okpd_name", "")
        p_title = candidate.get("procurement_title", "")

        cat_code = candidate.get("category_code", "")
        cat_name = candidate.get("category_name", cat_code)
        sub_code = candidate.get("subcategory_code", "")
        sub_name = candidate.get("subcategory_name", sub_code)

        term = candidate.get("matched_term", "")
        doc_name = candidate.get("document_name", "")
        page_sheet = candidate.get("page_or_sheet", "")
        row_num = candidate.get("row_number", "")
        doc_loc = f"{page_sheet}:{row_num}" if page_sheet or row_num else ""

        # Metadata Header (Fixed)
        meta_block = (
            f"[ТЕНДЕР]\\n"
            f"ID: {pid}\\n"
            f"ОКПД2: {okpd_code} ({okpd_name})\\n"
            f"Наименование закупки: {p_title}\\n\\n"
            f"[ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]\\n"
            f"Категория: {cat_name} ({cat_code})\\n"
            f"Подкатегория: {sub_name} ({sub_code})\\n"
            f"Искомый термин: {term}\\n"
            f"Документ: {doc_name} {doc_loc}\\n\\n"
        )

        # Question / Instructions Footer (Fixed) - NO negative phrase list included!
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name}\\" (категория \\"{cat_name}\\", термин \\"{term}\\" )?\\n"
            f"- ВАЖНО: Документальные доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Названия закупки, категории и терминов из раздела метаданных не являются доказательствами.\\n"
            f"- Если подкатегория прямо подтверждается спецификацией, позицией ВОР, описанием товара или характеристиками -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если созвучие/адрес/название организации/нецелевой товар -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если контекст обрезан или совершенно неоднозначен -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\\n"
            f"Ответь строго JSON."
        )

        matched_line = _candidate_matched_line(candidate)
        before_list = candidate.get("context_before") or []
        after_list = candidate.get("context_after") or []

        if isinstance(before_list, str):
            if before_list.startswith("[") and before_list.endswith("]"):
                try: before_list = json.loads(before_list)
                except Exception: pass
        before_lines = [str(x).strip() for x in before_list if str(x).strip()] if isinstance(before_list, list) else [str(before_list).strip()] if str(before_list).strip() else []

        if isinstance(after_list, str):
            if after_list.startswith("[") and after_list.endswith("]"):
                try: after_list = json.loads(after_list)
                except Exception: pass
        after_lines = [str(x).strip() for x in after_list if str(x).strip()] if isinstance(after_list, list) else [str(after_list).strip()] if str(after_list).strip() else []

        # Centered Budgeting Allocation
        fixed_len = len(meta_block) + len(question_block) + len("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n")
        
        max_matched_len = self.max_context_chars - fixed_len - 100
        if max_matched_len < 200:
            max_matched_len = 200

        if len(matched_line) > max_matched_len:
            matched_line = matched_line[:max_matched_len] + " ...[строка совпадения сокращена]..."

        avail_for_context = self.max_context_chars - fixed_len - len(matched_line)
        if avail_for_context < 0:
            avail_for_context = 0

        half_budget = avail_for_context // 2
        before_text = "\\n".join(before_lines)
        after_text = "\\n".join(after_lines)

        if len(before_text) <= half_budget:
            used_before = before_text
            avail_after = avail_for_context - len(used_before)
            used_after = after_text[:avail_after] if len(after_text) > avail_after else after_text
        elif len(after_text) <= half_budget:
            used_after = after_text
            avail_before = avail_for_context - len(used_after)
            used_before = before_text[-avail_before:] if len(before_text) > avail_before else before_text
        else:
            used_before = before_text[-half_budget:]
            used_after = after_text[:half_budget]

        before_prefix = "...[контекст до совпадения сокращён]...\\n" if len(used_before) < len(before_text) else ""
        after_suffix = "\\n...[контекст после совпадения сокращён]..." if len(used_after) < len(after_text) else ""

        doc_section = (
            f"[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n"
            f"{before_prefix}{used_before}\\n"
            f">>> НАЙДЕННАЯ СТРОКА: {matched_line}\\n"
            f"{used_after}{after_suffix}\\n"
        )

        return f"{meta_block}{doc_section}{question_block}"'''

# Replace build_context_block in val_src
b_start = val_src.find("    def build_context_block(")
b_end = val_src.find("    def _verify_and_gate_decision(")
assert b_start != -1 and b_end != -1, "Could not find build_context_block boundaries"
val_src = val_src[:b_start] + new_build_context_block + "\n\n" + val_src[b_end:]

# Update _verify_and_gate_decision method to enforce non-empty quote & document_context scope
new_gate = '''        quote = str(raw_decision.get("supporting_quote") or "").strip()
        reason = str(raw_decision.get("reason") or "").strip()

        # Document context trust boundary verification
        doc_context_only = build_document_context(candidate)
        norm_doc_context = _normalize_whitespace(doc_context_only)

        if decision in ("CONFIRMED", "REJECTED"):
            if not quote:
                decision = "UNKNOWN"
                reason_code = "MISSING_SUPPORTING_QUOTE"
                confidence = 0.0
                reason = f"Decision {decision} requires explicit non-empty supporting_quote from document context"
            else:
                norm_quote = _normalize_whitespace(quote)
                if norm_quote not in norm_doc_context:
                    decision = "UNKNOWN"
                    reason_code = "HALLUCINATED_QUOTE"
                    confidence = 0.0
                    reason = f"Supporting quote not found in document context: {quote[:60]}"'''

g_start = val_src.find("        quote = str(raw_decision.get(\"supporting_quote\")")
g_end = val_src.find("        # Confidence gating")
assert g_start != -1 and g_end != -1, "Could not find _verify_and_gate_decision quote section"
val_src = val_src[:g_start] + new_gate + "\n\n" + val_src[g_end:]

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully updated context_validator.py")

# 2. Update context_validator_service.py for v3 evidence provenance
with open(SERVICE_PATH, "r", encoding="utf-8") as f:
    service_src = f.read()

old_rebuild_isolation = '''        v2_trusted = [
            r
            for r in confirmed_rows
            if str(r.get("validator_version") or "").lower() == "v2"
            and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V2"
        ]

        v1_trusted = [
            r
            for r in confirmed_rows
            if str(r.get("validator_version") or "").lower() == "v1"
            and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V1"
        ]

        if v2_trusted:
            target_rows = v2_trusted
            val_ver = "v2"
            val_method = "QWEN_CONTEXT_V2"
        elif v1_trusted:
            target_rows = v1_trusted
            val_ver = "v1"
            val_method = "QWEN_CONTEXT_V1"
        else:'''

new_rebuild_isolation = '''        v3_trusted = [
            r
            for r in confirmed_rows
            if str(r.get("validator_version") or "").lower() == "v3"
            and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V3"
        ]

        v2_trusted = [
            r
            for r in confirmed_rows
            if str(r.get("validator_version") or "").lower() == "v2"
            and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V2"
        ]

        v1_trusted = [
            r
            for r in confirmed_rows
            if str(r.get("validator_version") or "").lower() == "v1"
            and str(r.get("validation_method") or "").upper() == "QWEN_CONTEXT_V1"
        ]

        if v3_trusted:
            target_rows = v3_trusted
            val_ver = "v3"
            val_method = "QWEN_CONTEXT_V3"
        elif v2_trusted:
            target_rows = v2_trusted
            val_ver = "v2"
            val_method = "QWEN_CONTEXT_V2"
        elif v1_trusted:
            target_rows = v1_trusted
            val_ver = "v1"
            val_method = "QWEN_CONTEXT_V1"
        else:'''

assert old_rebuild_isolation in service_src, "old_rebuild_isolation not found in context_validator_service.py"
service_src = service_src.replace(old_rebuild_isolation, new_rebuild_isolation, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(service_src)

print("Successfully updated context_validator_service.py for v3 evidence provenance")
