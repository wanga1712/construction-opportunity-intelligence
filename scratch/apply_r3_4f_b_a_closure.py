#!/usr/bin/env python3
"""
Applies R3-4F-B-A Model-Visible Document Context Alignment Repair to context_validator.py.
"""
import os

VAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator.py",
)

with open(VAL_PATH, "r", encoding="utf-8") as f:
    val_src = f.read()

# Replace build_document_context with build_source_document_context and build_visible_document_context
new_authorities = '''def build_source_document_context(candidate: Dict[str, Any]) -> str:
    """Full hydrated source factual document text (unbounded).

    Contains all context_before, matched_line, and context_after.
    Used for audit and full source inspection.
    """
    c_hydrated = hydrate_candidate_context(candidate)
    before_list = c_hydrated.get("context_before") or []
    after_list = c_hydrated.get("context_after") or []
    m_line = c_hydrated.get("matched_line") or ""

    if isinstance(before_list, str):
        if before_list.startswith("[") and before_list.endswith("]"):
            try: before_list = json.loads(before_list)
            except Exception: pass
    before_str = "\\n".join(str(x) for x in before_list if x) if isinstance(before_list, list) else str(before_list)

    if isinstance(after_list, str):
        if after_list.startswith("[") and after_list.endswith("]"):
            try: after_list = json.loads(after_list)
            except Exception: pass
    after_str = "\\n".join(str(x) for x in after_list if x) if isinstance(after_list, list) else str(after_list)

    parts = []
    if before_str: parts.append(before_str)
    if m_line: parts.append(m_line)
    if after_str: parts.append(after_str)

    return "\\n".join(parts)


def build_visible_document_context(
    candidate: Dict[str, Any],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    fixed_overhead: int = 0,
) -> str:
    """Single authority for the EXACT bounded documentary text shown to Qwen in prompt.

    Quote verification MUST validate against this text ONLY.
    Includes truncation markers inside character budget and centers long matched lines.
    """
    c_hydrated = hydrate_candidate_context(candidate)
    matched_line = _candidate_matched_line(c_hydrated)
    matched_term = str(c_hydrated.get("matched_term") or "").strip().lower()

    before_list = c_hydrated.get("context_before") or []
    after_list = c_hydrated.get("context_after") or []

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

    doc_header_overhead = len("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n")
    max_doc_budget = max_context_chars - fixed_overhead - doc_header_overhead
    if max_doc_budget < 100:
        max_doc_budget = 100

    prefix_marker = "...[контекст до совпадения сокращён]...\\n"
    suffix_marker = "\\n...[контекст после совпадения сокращён]..."
    mline_marker = " ...[строка совпадения сокращена]..."

    max_mline_len = max_doc_budget - 50
    if max_mline_len < 100:
        max_mline_len = 100

    if len(matched_line) > max_mline_len:
        eff_len = max_mline_len - len(mline_marker)
        if eff_len < 50: eff_len = 50
        term_idx = matched_line.lower().find(matched_term) if matched_term else -1
        if term_idx != -1:
            half = eff_len // 2
            start = max(0, term_idx - half)
            end = start + eff_len
            if end > len(matched_line):
                end = len(matched_line)
                start = max(0, end - eff_len)
            sub = matched_line[start:end]
            p_mark = "...[строка совпадения сокращена]... " if start > 0 else ""
            s_mark = " ...[строка совпадения сокращена]..." if end < len(matched_line) else ""
            matched_line = f"{p_mark}{sub}{s_mark}"
        else:
            half = eff_len // 2
            mid = len(matched_line) // 2
            start = max(0, mid - half)
            end = start + eff_len
            sub = matched_line[start:end]
            p_mark = "...[строка совпадения сокращена]... " if start > 0 else ""
            s_mark = " ...[строка совпадения сокращена]..." if end < len(matched_line) else ""
            matched_line = f"{p_mark}{sub}{s_mark}"

    avail_for_before_after = max_doc_budget - len(matched_line)
    if avail_for_before_after < 0:
        avail_for_before_after = 0

    before_text = "\\n".join(before_lines)
    after_text = "\\n".join(after_lines)

    half_budget = avail_for_before_after // 2

    if len(before_text) <= half_budget:
        used_before = before_text
        avail_after = avail_for_before_after - len(used_before)
        if len(after_text) > avail_after:
            avail_after_net = avail_after - len(suffix_marker)
            if avail_after_net < 0: avail_after_net = 0
            used_after = after_text[:avail_after_net]
        else:
            used_after = after_text
    elif len(after_text) <= half_budget:
        used_after = after_text
        avail_before = avail_for_before_after - len(used_after)
        if len(before_text) > avail_before:
            avail_before_net = avail_before - len(prefix_marker)
            if avail_before_net < 0: avail_before_net = 0
            used_before = before_text[-avail_before_net:]
        else:
            used_before = before_text
    else:
        net_half_before = half_budget - len(prefix_marker)
        net_half_after = half_budget - len(suffix_marker)
        if net_half_before < 0: net_half_before = 0
        if net_half_after < 0: net_half_after = 0
        used_before = before_text[-net_half_before:] if net_half_before > 0 else ""
        used_after = after_text[:net_half_after] if net_half_after > 0 else ""

    p_str = prefix_marker if len(used_before) < len(before_text) else ""
    s_str = suffix_marker if len(used_after) < len(after_text) else ""

    return (
        f"[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n"
        f"{p_str}{used_before}\\n"
        f">>> НАЙДЕННАЯ СТРОКА: {matched_line}\\n"
        f"{used_after}{s_str}\\n"
    )


def build_document_context(candidate: Dict[str, Any]) -> str:
    """Backward-compatible alias for build_visible_document_context."""
    return build_visible_document_context(candidate)'''

old_build_doc_ctx = '''def build_document_context(candidate: Dict[str, Any]) -> str:
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

    return "\\n".join(parts)'''

assert old_build_doc_ctx in val_src, "old_build_doc_ctx not found in val_src"
val_src = val_src.replace(old_build_doc_ctx, new_authorities, 1)

# Now replace build_context_block to embed build_visible_document_context and guarantee hard <= max_context_chars
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

        # Question / Instructions Footer (Fixed)
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name}\\" (категория \\"{cat_name}\\", термин \\"{term}\\" )?\\n"
            f"- ВАЖНО: Документальные доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Названия закупки, категории и терминов из раздела метаданных не являются доказательствами.\\n"
            f"- Если подкатегория прямо подтверждается спецификацией, позицией ВОР, описанием товара или характеристиками -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если созвучие/адрес/название организации/нецелевой товар -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если контекст обрезан или совершенно неоднозначен -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\\n"
            f"Ответь строго JSON."
        )

        fixed_overhead = len(meta_block) + len(question_block)
        doc_section = build_visible_document_context(
            candidate,
            max_context_chars=self.max_context_chars,
            fixed_overhead=fixed_overhead,
        )

        block = f"{meta_block}{doc_section}{question_block}"
        if len(block) > self.max_context_chars:
            block = block[: self.max_context_chars]

        return block'''

b_start = val_src.find("    def build_context_block(")
b_end = val_src.find("    def _verify_and_gate_decision(")
assert b_start != -1 and b_end != -1, "Could not find build_context_block boundaries"
val_src = val_src[:b_start] + new_build_context_block + "\n\n" + val_src[b_end:]

# Update _verify_and_gate_decision to verify supporting_quote ONLY against build_visible_document_context
new_gate = '''        quote = str(raw_decision.get("supporting_quote") or "").strip()
        reason = str(raw_decision.get("reason") or "").strip()

        # Document context trust boundary verification against EXACT VISIBLE_DOCUMENT_CONTEXT
        visible_doc_context = build_visible_document_context(
            candidate,
            max_context_chars=self.max_context_chars,
            fixed_overhead=0,
        )
        norm_visible_context = _normalize_whitespace(visible_doc_context)

        if decision in ("CONFIRMED", "REJECTED"):
            if not quote:
                decision = "UNKNOWN"
                reason_code = "MISSING_SUPPORTING_QUOTE"
                confidence = 0.0
                reason = f"Decision {decision} requires explicit non-empty supporting_quote from document context"
            else:
                norm_quote = _normalize_whitespace(quote)
                if norm_quote not in norm_visible_context:
                    decision = "UNKNOWN"
                    reason_code = "HALLUCINATED_QUOTE"
                    confidence = 0.0
                    reason = f"Supporting quote not found in model-visible document context: {quote[:60]}"'''

g_start = val_src.find("        quote = str(raw_decision.get(\"supporting_quote\")")
g_end = val_src.find("        # Confidence gating")
assert g_start != -1 and g_end != -1, "Could not find _verify_and_gate_decision quote section"
val_src = val_src[:g_start] + new_gate + "\n\n" + val_src[g_end:]

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully updated context_validator.py for R3-4F-B-A closure")
