#!/usr/bin/env python3
"""
Cleanly updates _build_visible_document_context_pair in context_validator.py.
Defines markers first, then calculates doc_header_overhead including marker budget.
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

new_pair_fn = '''def _build_visible_document_context_pair(
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

    prefix_marker = "...[контекст до совпадения сокращён]...\\n"
    suffix_marker = "\\n...[контекст после совпадения сокращён]..."
    mline_marker = " ...[строка совпадения сокращена]..."

    doc_header_overhead = len("[ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]\\n\\n>>> НАЙДЕННАЯ СТРОКА: \\n") + len(prefix_marker) + len(suffix_marker) + len(mline_marker) + 10
    avail_budget = max_doc_budget - doc_header_overhead
    if avail_budget < 50:
        avail_budget = 50

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
            used_after = after_text[:avail_after_net] if avail_after_net > 0 else ""
        else:
            used_after = after_text
    elif len(after_text) <= half_budget:
        used_after = after_text
        avail_before = avail_for_before_after - len(used_after)
        if len(before_text) > avail_before:
            avail_before_net = avail_before - len(prefix_marker)
            if avail_before_net < 0: avail_before_net = 0
            used_before = before_text[-avail_before_net:] if avail_before_net > 0 else ""
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

val_src = val_src[:p_start] + new_pair_fn + "\n\n" + val_src[p_end:]

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Cleanly updated _build_visible_document_context_pair in context_validator.py")
