#!/usr/bin/env python3
"""
Applies R3-4F-B-C Pure Source & Hard Budget Closure to context_validator.py.
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

# Replace _build_visible_document_context_pair and build_context_payload in val_src
new_pair_helper = '''def _build_visible_document_context_pair(
    candidate: Dict[str, Any],
    max_doc_budget: int,
) -> Tuple[str, str]:
    """Builds EXACT visible document section AND pure visible source text pair.

    Returns:
      (visible_doc_section_str, visible_source_text_str)

    visible_doc_section_str: formatted section with UI headers and truncation markers for Qwen prompt.
    visible_source_text_str: pure factual retained document text ONLY (without ANY generated markers/headers) for quote verification.
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
    avail_budget = max_doc_budget - doc_header_overhead
    if avail_budget < 50:
        avail_budget = 50

    prefix_marker = "...[контекст до совпадения сокращён]...\\n"
    suffix_marker = "\\n...[контекст после совпадения сокращён]..."
    mline_marker = " ...[строка совпадения сокращена]..."

    max_mline_len = avail_budget - 30
    if max_mline_len < 50:
        max_mline_len = 50

    display_retained_mline = matched_line
    pure_source_mline = matched_line

    if len(matched_line) > max_mline_len:
        eff_len = max_mline_len - len(mline_marker)
        if eff_len < 30: eff_len = 30
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
            display_retained_mline = f"{p_mark}{sub}{s_mark}"
            pure_source_mline = sub
        else:
            half = eff_len // 2
            mid = len(matched_line) // 2
            start = max(0, mid - half)
            end = start + eff_len
            sub = matched_line[start:end]
            p_mark = "...[строка совпадения сокращена]... " if start > 0 else ""
            s_mark = " ...[строка совпадения сокращена]..." if end < len(matched_line) else ""
            display_retained_mline = f"{p_mark}{sub}{s_mark}"
            pure_source_mline = sub

    avail_for_before_after = avail_budget - len(display_retained_mline)
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

    doc_section_str = (
        f"[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n"
        f"{p_str}{used_before}\\n"
        f">>> НАЙДЕННАЯ СТРОКА: {display_retained_mline}\\n"
        f"{used_after}{s_str}\\n"
    )

    # Pure factual source text ONLY (zero generated markers/headers) for quote verification
    pure_parts = []
    if used_before: pure_parts.append(used_before)
    if pure_source_mline: pure_parts.append(pure_source_mline)
    if used_after: pure_parts.append(used_after)
    visible_source_text_str = "\\n".join(pure_parts)

    return doc_section_str, visible_source_text_str'''

p_start = val_src.find("def _build_visible_document_context_pair(")
p_end = val_src.find("def build_visible_document_context(")
assert p_start != -1 and p_end != -1, "Could not find _build_visible_document_context_pair"

val_src = val_src[:p_start] + new_pair_helper + "\n\n" + val_src[p_end:]

# Update build_context_payload method with dynamic metadata bounding & impossible budget check
new_payload_method = '''    def build_context_payload(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Unified single-execution-path context builder for model prompt AND quote verification.

        Guarantees that:
        1. Prompt document context == verifier visible document context (built ONCE per candidate).
        2. Total context_block length <= max_context_chars without blind prefix/suffix clipping.
        3. All dynamic metadata (title, OKPD, category, subcategory, term, doc_name) is deterministically bounded.
        """
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

        # Bound dynamic metadata for display to prevent pathological metadata from inflating prompt/question
        pid_disp = str(pid)[:30]
        okpd_code_disp = str(okpd_code)[:30]
        okpd_name_disp = str(okpd_name)[:30] + "..." if len(str(okpd_name)) > 30 else str(okpd_name)
        p_title_disp = str(p_title)[:40] + "..." if len(str(p_title)) > 40 else str(p_title)

        cat_code_disp = str(cat_code)[:30]
        cat_name_disp = str(cat_name)[:40] + "..." if len(str(cat_name)) > 40 else str(cat_name)
        sub_code_disp = str(sub_code)[:30]
        sub_name_disp = str(sub_name)[:40] + "..." if len(str(sub_name)) > 40 else str(sub_name)

        term_disp = str(term)[:40] + "..." if len(str(term)) > 40 else str(term)
        doc_name_disp = str(doc_name)[:40] + "..." if len(str(doc_name)) > 40 else str(doc_name)
        doc_loc_disp = str(doc_loc)[:30]

        # Bounded Question Block
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name_disp}\\" (категория \\"{cat_name_disp}\\", термин \\"{term_disp}\\" )?\\n"
            f"- ВАЖНО: Документальные доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Названия закупки, категории и терминов из раздела метаданных не являются доказательствами.\\n"
            f"- Если подкатегория прямо подтверждается спецификацией, позицией ВОР, описанием товара или характеристиками -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если созвучие/адрес/название организации/нецелевой товар -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если контекст обрезан или совершенно неоднозначен -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\\n"
            f"Ответь строго JSON."
        )

        # Bounded Metadata Header
        meta_block = (
            f"[ТЕНДЕР]\\n"
            f"ID: {pid_disp}\\n"
            f"ОКПД2: {okpd_code_disp} ({okpd_name_disp})\\n"
            f"Наименование закупки: {p_title_disp}\\n\\n"
            f"[ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]\\n"
            f"Категория: {cat_name_disp} ({cat_code_disp})\\n"
            f"Подкатегория: {sub_name_disp} ({sub_code_disp})\\n"
            f"Искомый термин: {term_disp}\\n"
            f"Документ: {doc_name_disp} {doc_loc_disp}\\n\\n"
        )

        fixed_overhead = len(meta_block) + len(question_block)
        min_required_budget = fixed_overhead + len("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n") + 50

        if self.max_context_chars < min_required_budget:
            raise ValueError(f"Impossible context budget: max_context_chars={self.max_context_chars} is smaller than required minimum overhead {min_required_budget}")

        max_doc_budget = self.max_context_chars - fixed_overhead
        doc_section, visible_source_text = _build_visible_document_context_pair(candidate, max_doc_budget)

        context_block = f"{meta_block}{doc_section}{question_block}"

        if len(context_block) > self.max_context_chars:
            overflow = len(context_block) - self.max_context_chars
            doc_section, visible_source_text = _build_visible_document_context_pair(candidate, max_doc_budget - overflow)
            context_block = f"{meta_block}{doc_section}{question_block}"
            if len(context_block) > self.max_context_chars:
                raise ValueError(f"Final context_block length {len(context_block)} exceeds max_context_chars {self.max_context_chars}")

        return {
            "context_block": context_block,
            "visible_doc_section": doc_section,
            "visible_source_text": visible_source_text,
        }'''

b_payload_start = val_src.find("    def build_context_payload(")
b_payload_end = val_src.find("    def build_context_block(")
assert b_payload_start != -1 and b_payload_end != -1, "Could not find build_context_payload boundaries"

val_src = val_src[:b_payload_start] + new_payload_method + "\n\n" + val_src[b_payload_end:]

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully updated context_validator.py for R3-4F-B-C pure source and hard budget closure")
