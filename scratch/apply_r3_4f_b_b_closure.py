#!/usr/bin/env python3
"""
Applies R3-4F-B-B Exact Prompt Evidence Boundary Closure to context_validator.py.
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

# Replace document context helpers with unified visible source & doc section pair generator
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


def _build_visible_document_context_pair(
    candidate: Dict[str, Any],
    max_doc_budget: int,
) -> Tuple[str, str]:
    """Builds EXACT visible document section AND pure visible source text pair.

    Returns:
      (visible_doc_section_str, visible_source_text_str)

    visible_doc_section_str: formatted section with UI headers and truncation markers for Qwen prompt.
    visible_source_text_str: pure factual retained document text ONLY (without generated markers/headers) for quote verification.
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

    retained_mline = matched_line
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
            retained_mline = f"{p_mark}{sub}{s_mark}"
        else:
            half = eff_len // 2
            mid = len(matched_line) // 2
            start = max(0, mid - half)
            end = start + eff_len
            sub = matched_line[start:end]
            p_mark = "...[строка совпадения сокращена]... " if start > 0 else ""
            s_mark = " ...[строка совпадения сокращена]..." if end < len(matched_line) else ""
            retained_mline = f"{p_mark}{sub}{s_mark}"

    avail_for_before_after = avail_budget - len(retained_mline)
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
        f">>> НАЙДЕННАЯ СТРОКА: {retained_mline}\\n"
        f"{used_after}{s_str}\\n"
    )

    # Pure factual source text ONLY (no generated headers/markers) for quote verification
    pure_parts = []
    if used_before: pure_parts.append(used_before)
    if retained_mline: pure_parts.append(retained_mline)
    if used_after: pure_parts.append(used_after)
    visible_source_text_str = "\\n".join(pure_parts)

    return doc_section_str, visible_source_text_str


def build_visible_document_context(
    candidate: Dict[str, Any],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    fixed_overhead: int = 0,
) -> str:
    """Single authority for the EXACT bounded documentary section shown in prompt."""
    max_doc_budget = max_context_chars - fixed_overhead
    doc_section, _ = _build_visible_document_context_pair(candidate, max_doc_budget)
    return doc_section


def build_document_context(candidate: Dict[str, Any]) -> str:
    """Backward-compatible alias for build_visible_document_context."""
    return build_visible_document_context(candidate)'''

old_authorities_start = val_src.find("def build_source_document_context(")
old_authorities_end = val_src.find("def hydrate_candidate_context(")
assert old_authorities_start != -1 and old_authorities_end != -1, "Could not locate authorities section"

val_src = val_src[:old_authorities_start] + new_authorities + "\n\n" + val_src[old_authorities_end:]

# Replace build_context_block and add build_context_payload method
new_payload_methods = '''    def build_context_payload(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Unified single-execution-path context builder for model prompt AND quote verification.

        Guarantees that:
        1. Prompt document context == verifier visible document context (built ONCE per candidate).
        2. Total context_block length <= max_context_chars without blind prefix/suffix clipping.
        3. Pathological metadata is truncated cleanly to preserve document context & question blocks.
        """
        if self.max_context_chars < 300:
            raise ValueError(f"Impossible context budget: max_context_chars={self.max_context_chars} is below minimum 300")

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

        # Fixed Question Block
        question_block = (
            f"\\n[ВОПРОС]\\n"
            f"Подтверждает ли данный фрагмент документа закупку/применение материалов или работ для подкатегории \\"{sub_name}\\" (категория \\"{cat_name}\\", термин \\"{term}\\" )?\\n"
            f"- ВАЖНО: Документальные доказательства берутся ИСКЛЮЧИТЕЛЬНО из раздела [ДОКУМЕНТАЛЬНЫЙ КОНТЕКСТ]. Названия закупки, категории и терминов из раздела метаданных не являются доказательствами.\\n"
            f"- Если подкатегория прямо подтверждается спецификацией, позицией ВОР, описанием товара или характеристиками -> 'CONFIRMED', confidence: 0.80-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если созвучие/адрес/название организации/нецелевой товар -> 'REJECTED', confidence: 0.85-1.0, supporting_quote: обязательная дословная цитата из документа.\\n"
            f"- Если контекст обрезан или совершенно неоднозначен -> 'UNKNOWN', confidence: 0.0, reason_code: 'INSUFFICIENT_CONTEXT'.\\n"
            f"Ответь строго JSON."
        )

        # Pathological Metadata Handling: Ensure metadata overhead leaves at least 300 chars for document context
        min_doc_budget = 300
        max_meta_budget = self.max_context_chars - len(question_block) - min_doc_budget
        if max_meta_budget < 120:
            max_meta_budget = 120

        # Construct raw metadata header
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

        if len(meta_block) > max_meta_budget:
            # Safely truncate verbose metadata fields (p_title, okpd_name, doc_name)
            p_title_sub = str(p_title)[:40] + "..." if len(str(p_title)) > 40 else str(p_title)
            okpd_name_sub = str(okpd_name)[:30] + "..." if len(str(okpd_name)) > 30 else str(okpd_name)
            doc_name_sub = str(doc_name)[:40] + "..." if len(str(doc_name)) > 40 else str(doc_name)
            meta_block = (
                f"[ТЕНДЕР]\\n"
                f"ID: {pid}\\n"
                f"ОКПД2: {okpd_code} ({okpd_name_sub})\\n"
                f"Наименование закупки: {p_title_sub}\\n\\n"
                f"[ЦЕЛЕВАЯ КАТЕГОРИЯ CRM]\\n"
                f"Категория: {cat_name} ({cat_code})\\n"
                f"Подкатегория: {sub_name} ({sub_code})\\n"
                f"Искомый термин: {term}\\n"
                f"Документ: {doc_name_sub} {doc_loc}\\n\\n"
            )

        fixed_overhead = len(meta_block) + len(question_block)
        max_doc_budget = self.max_context_chars - fixed_overhead

        doc_section, visible_source_text = _build_visible_document_context_pair(candidate, max_doc_budget)

        context_block = f"{meta_block}{doc_section}{question_block}"

        # Invariant check: Hard limit guaranteed without blind clipping
        if len(context_block) > self.max_context_chars:
            # Extra safety truncation of doc section only if needed
            trim_len = len(context_block) - self.max_context_chars
            doc_section, visible_source_text = _build_visible_document_context_pair(candidate, max_doc_budget - trim_len - 10)
            context_block = f"{meta_block}{doc_section}{question_block}"

        return {
            "context_block": context_block,
            "visible_doc_section": doc_section,
            "visible_source_text": visible_source_text,
        }

    def build_context_block(self, candidate: Dict[str, Any]) -> str:
        """Constructs a bounded, informative context block for Qwen (backward-compatible wrapper)."""
        payload = self.build_context_payload(candidate)
        return payload["context_block"]'''

b_start = val_src.find("    def build_context_block(")
b_end = val_src.find("    def _verify_and_gate_decision(")
assert b_start != -1 and b_end != -1, "Could not find build_context_block boundaries"
val_src = val_src[:b_start] + new_payload_methods + "\n\n" + val_src[b_end:]

# Replace _verify_and_gate_decision and validate_single to pass visible_source_text directly
new_gate_and_validate = '''    def _verify_and_gate_decision(
        self,
        raw_decision: Dict[str, Any],
        candidate: Dict[str, Any],
        visible_source_text: str,
    ) -> Dict[str, Any]:
        """Applies conservative threshold gating, quote verification against visible_source_text, and fail-closed defaults."""
        detail_id = candidate.get("detail_id") or candidate.get("id")
        cat_code = candidate.get("category_code")
        sub_code = candidate.get("subcategory_code")

        decision = str(raw_decision.get("decision") or "UNKNOWN").upper().strip()
        if decision not in VALID_DECISIONS:
            decision = "UNKNOWN"
            reason_code = "INVALID_DECISION_ENUM"
        else:
            reason_code = str(raw_decision.get("reason_code") or "UNSPECIFIED")

        try:
            confidence = float(raw_decision.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0

        quote = str(raw_decision.get("supporting_quote") or "").strip()
        reason = str(raw_decision.get("reason") or "").strip()

        # Document context trust boundary verification against EXACT visible_source_text (built ONCE per candidate)
        norm_visible_source = _normalize_whitespace(visible_source_text)

        if decision in ("CONFIRMED", "REJECTED"):
            if not quote:
                decision = "UNKNOWN"
                reason_code = "MISSING_SUPPORTING_QUOTE"
                confidence = 0.0
                reason = f"Decision {decision} requires explicit non-empty supporting_quote from document context"
            else:
                norm_quote = _normalize_whitespace(quote)
                if norm_quote not in norm_visible_source:
                    decision = "UNKNOWN"
                    reason_code = "HALLUCINATED_QUOTE"
                    confidence = 0.0
                    reason = f"Supporting quote not found in prompt-visible documentary source: {quote[:60]}"

        # Confidence gating
        if decision == "CONFIRMED" and confidence < self.confirm_threshold:
            decision = "UNKNOWN"
            reason_code = "LOW_CONFIDENCE"
            reason = f"Confidence {confidence:.2f} below CONFIRM_THRESHOLD {self.confirm_threshold:.2f}"
        elif decision == "REJECTED" and confidence < self.reject_threshold:
            decision = "UNKNOWN"
            reason_code = "LOW_CONFIDENCE"
            reason = f"Confidence {confidence:.2f} below REJECT_THRESHOLD {self.reject_threshold:.2f}"

        return {
            "detail_id": detail_id,
            "procurement_id": candidate.get("procurement_id"),
            "category_code": cat_code,  # IMMUTABLE
            "subcategory_code": sub_code,  # IMMUTABLE
            "decision": decision,
            "confidence": confidence,
            "supporting_quote": quote,
            "reason_code": reason_code,
            "reason": reason,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "validator_name": VALIDATOR_NAME,
            "validator_version": VALIDATOR_VERSION,
            "validation_method": VALIDATION_METHOD,
        }

    def validate_single(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Validates a single candidate using unified context payload."""
        payload = self.build_context_payload(candidate)
        context_block = payload["context_block"]
        visible_source_text = payload["visible_source_text"]

        prompt = (
            f"Проанализируй совпадение и определи, подтверждает ли оно категорию.\\n\\n"
            f"{context_block}\\n\\n"
            f"Верни результат в формате JSON."
        )

        try:
            resp_text = self._ai_caller(prompt)
            match = re.search(r"\\{.*\\}", resp_text, re.DOTALL)
            if not match:
                raw_decision = {"decision": "UNKNOWN", "reason_code": "INVALID_JSON", "confidence": 0.0}
            else:
                try:
                    raw_decision = json.loads(match.group(0))
                except Exception as ex:
                    raw_decision = {"decision": "UNKNOWN", "reason_code": "JSON_PARSE_ERROR", "confidence": 0.0, "reason": str(ex)}
        except Exception as ex:
            logger.error(f"AI caller failed for detail_id {candidate.get('detail_id')}: {ex}")
            raw_decision = {"decision": "UNKNOWN", "reason_code": "MODEL_CALL_FAILED", "confidence": 0.0, "reason": str(ex)}

        return self._verify_and_gate_decision(raw_decision, candidate, visible_source_text)'''

g_start = val_src.find("    def _verify_and_gate_decision(")
assert g_start != -1, "Could not find _verify_and_gate_decision"
val_src = val_src[:g_start] + new_gate_and_validate + "\n"

with open(VAL_PATH, "w", encoding="utf-8") as f:
    f.write(val_src)

print("Successfully updated context_validator.py for R3-4F-B-B closure")
