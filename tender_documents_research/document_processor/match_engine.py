import re
from typing import Any, Dict, List, Optional
from rapidfuzz import fuzz
import logging

from document_processor.dto import MatchResult, MatchDetailResult
from document_processor.matching.table_row_matcher import TableRowMatcher
from document_processor.matching.table_row_enricher import TableRowEnricher
from document_processor.matching.composite_drainage_rule import match_composite_drainage
from document_processor.matching.normalization import normalize_ocr_line
from document_processor.matching.dto_mapper import to_match_detail

logger = logging.getLogger(__name__)

class MatchEngine:
    """
    Pure compute MatchEngine. ZERO side effects. ZERO database writes.
    Accepts text and configuration (keywords, stop phrases, etc).
    Returns DTOs.
    """
    def __init__(
        self,
        keywords: List[str],
        stop_phrases: List[str] = None,
        custom_thresholds: Dict[str, int] = None,
        min_score: int = 75,
        match_table_all_rows: bool = True,
        match_table_enrich: bool = True,
        keyword_meta: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        self.keywords = list(keywords or [])
        self.stop_phrases = stop_phrases or []
        self.custom_thresholds = custom_thresholds or {}
        self.min_score = min_score
        self.match_table_all_rows = match_table_all_rows
        self.match_table_enrich = match_table_enrich
        self.keyword_meta = keyword_meta or {}
        self._table_row_matcher = TableRowMatcher()

    def _is_blocked_by_stop_phrase(self, keyword: str, text_lower: str) -> bool:
        for phrase in self.stop_phrases:
            if keyword in phrase and phrase in text_lower:
                return True
        return False



    def process_text(self, text: str, line_meta: Optional[Dict[int, Dict[str, Any]]] = None) -> List[MatchDetailResult]:
        if not self.keywords:
            return []

        text_lower = text.lower()
        lines = text.splitlines()
        lines_lower = [normalize_ocr_line(ln.lower()) for ln in lines]

        combined_lines = list(lines_lower)
        combined_originals = list(lines)
        for i in range(len(lines_lower) - 1):
            merged = lines_lower[i].rstrip() + ' ' + lines_lower[i + 1].lstrip()
            merged = re.sub(r'\s+', ' ', merged).strip()
            if merged:
                combined_lines.append(merged)
                combined_originals.append(lines[i].rstrip() + ' ' + lines[i + 1].lstrip())

        matches: List[Dict[str, Any]] = []
        meta = line_meta or {}
        table_line_numbers = self._table_row_matcher.table_line_numbers(meta)
        use_table_multi = bool(table_line_numbers) and self.match_table_all_rows

        try:
            compound_matches = match_composite_drainage(lines, line_meta=meta)
            if compound_matches:
                matches.extend(compound_matches)
        except Exception as exc:
            logger.error(f"compound_rule composite_drainage error: {exc}", exc_info=True)

        bm_strict_pattern = re.compile(r'^бм\s*[-]?\s*\d+')
        total_lines = len(lines_lower)
        if total_lines == 0:
            return []

        for keyword in self.keywords:
            if use_table_multi:
                matches.extend(
                    self._table_row_matcher.match_keyword(
                        keyword,
                        lines=lines,
                        lines_lower=lines_lower,
                        meta=meta,
                        min_score=self.min_score,
                        custom_thresholds=self.custom_thresholds,
                        normalize_line=normalize_ocr_line,
                        is_blocked_by_stop_phrase=self._is_blocked_by_stop_phrase,
                        text_lower=text_lower,
                        bm_strict_pattern=bm_strict_pattern,
                    )
                )
                continue

            is_bm_keyword = bool(bm_strict_pattern.match(keyword))
            use_strict_match = is_bm_keyword or len(keyword) <= 5
            match_method = "EXACT" if use_strict_match else "UNKNOWN"

            if use_strict_match:
                found_exact = False
                best_score = 0
                best_line_idx = -1

                pattern = r'(^|\s|[^a-zA-Z0-9а-яА-Я])' + re.escape(keyword) + r'($|\s|[^a-zA-Z0-9а-яА-Я])'

                for idx, line_text in enumerate(lines_lower):
                    if re.search(pattern, line_text):
                        found_exact = True
                        best_score = 100
                        best_line_idx = idx
                        break

                if not found_exact:
                    continue
            else:
                required_score = self.custom_thresholds.get(keyword, self.min_score)

                if self._is_blocked_by_stop_phrase(keyword, text_lower):
                    continue

                best_score = 0
                best_line_idx = -1

                kw_len = len(keyword)
                kw_words = keyword.split()
                min_line_len = max(3, int(kw_len * 0.3))

                for idx, line in enumerate(combined_lines):
                    line_len = len(line)
                    if line_len < min_line_len:
                        continue

                    if line_len < kw_len * 1.5:
                        score = int(fuzz.ratio(keyword, line))
                        curr_method = "FUZZY_RATIO"
                    else:
                        score = int(fuzz.token_set_ratio(keyword, line))
                        curr_method = "FUZZY_TOKEN_SET"

                    if score > best_score:
                        best_score = score
                        best_line_idx = idx
                        match_method = curr_method

                if best_score < required_score:
                    if best_score >= 50 and len(kw_words) >= 2 and best_line_idx >= 0:
                        matched_line_lower = combined_lines[best_line_idx]
                        meaningful_words = [w for w in kw_words if len(w) >= 2 and any(ch.isalpha() for ch in w)]
                        if not meaningful_words:
                            meaningful_words = [w for w in kw_words if len(w) >= 3 and not w.isdigit()]
                        words_present = 0
                        for w in meaningful_words:
                            if w in matched_line_lower:
                                words_present += 1
                            else:
                                stem_len = max(4, int(len(w) * 0.7))
                                stem = w[:stem_len]
                                if stem in matched_line_lower:
                                    words_present += 1
                                else:
                                    w_norm = normalize_ocr_line(w)
                                    if w_norm != w and w_norm in matched_line_lower:
                                        words_present += 1
                        if meaningful_words:
                            coverage = words_present / len(meaningful_words)
                            if coverage >= 0.8:
                                best_score = required_score
                                match_method = "STEM_PREFIX"
                            else:
                                continue
                        else:
                            continue
                    else:
                        continue

                if len(kw_words) >= 2 and best_line_idx >= 0:
                    matched_line_lower = combined_lines[best_line_idx]
                    words_present = 0
                    meaningful_words = [w for w in kw_words if len(w) >= 2 and any(ch.isalpha() for ch in w)]
                    if not meaningful_words:
                        meaningful_words = [w for w in kw_words if len(w) >= 3 and not w.isdigit()]

                    for w in meaningful_words:
                        if w in matched_line_lower:
                            words_present += 1
                        else:
                            stem_len = max(4, int(len(w) * 0.7))
                            stem = w[:stem_len]
                            if stem in matched_line_lower:
                                words_present += 1
                            else:
                                w_norm = normalize_ocr_line(w)
                                if w_norm != w and w_norm in matched_line_lower:
                                    words_present += 1

                    if meaningful_words:
                        coverage = words_present / len(meaningful_words)
                        if coverage < 0.7:
                            continue

                if best_line_idx >= 0:
                    kw_numbers = [w for w in kw_words if w.isdigit()]
                    if kw_numbers:
                        matched_line_lower = combined_lines[best_line_idx]
                        for num in kw_numbers:
                            pattern = r'(?:^|\b)' + re.escape(num) + r'(?:\b|$)'
                            if not re.search(pattern, matched_line_lower):
                                best_score = 0
                                break
                        if best_score == 0:
                            continue

            if best_line_idx < len(lines):
                matched_line = lines[best_line_idx]
                line_number = best_line_idx + 1
            elif best_line_idx < len(combined_originals):
                matched_line = combined_originals[best_line_idx]
                line_number = (best_line_idx - len(lines)) + 1
            else:
                matched_line = ""
                line_number = -1

            level = "green" if best_score >= 95 else "yellow"
            item: Dict[str, Any] = {
                "keyword": keyword,
                "score": best_score,
                "level": level,
                "line_number": line_number,
                "matched_line": matched_line,
                "match_method": match_method,
                "validation_status": "UNKNOWN",
            }
            if line_number in meta:
                extra = meta[line_number]
                for k, v in extra.items():
                    item[k] = v
                cells = extra.get("cells")
                if isinstance(cells, list) and cells:
                    best_cell_score = -1
                    best_cell = None

                    if use_strict_match:
                        strict_pattern = r'(^|\s|[^a-zA-Z0-9а-яА-Я])' + re.escape(keyword) + r'($|\s|[^a-zA-Z0-9а-яА-Я])'
                        for c in cells:
                            t = str(c.get("text", "")).lower()
                            if not t:
                                continue
                            if re.search(strict_pattern, t):
                                best_cell = c
                                best_cell_score = 100
                                break

                    if not best_cell:
                        for c in cells:
                            t = str(c.get("text", "")).lower()
                            if not t:
                                continue
                            if len(t) < len(keyword) * 0.6:
                                continue
                            if len(t) < len(keyword):
                                sc = fuzz.ratio(keyword, t)
                            else:
                                sc = fuzz.partial_ratio(keyword, t)
                            if sc > best_cell_score:
                                best_cell_score = sc
                                best_cell = c

                    if best_cell:
                        item["matched_cell_text"] = best_cell.get("text")
                        if "column_letter" not in item and best_cell.get("column_letter"):
                            item["column_letter"] = best_cell.get("column_letter")
                        if "cell_address" not in item and best_cell.get("cell_address"):
                            item["cell_address"] = best_cell.get("cell_address")
            matches.append(item)

        if matches:
            if use_table_multi:
                best_per_line_keyword: Dict[tuple[int, str], Dict[str, Any]] = {}
                for m in matches:
                    key = (int(m.get("line_number", -1)), str(m.get("keyword", "")))
                    if (
                        key not in best_per_line_keyword
                        or m["score"] > best_per_line_keyword[key]["score"]
                    ):
                        best_per_line_keyword[key] = m
                matches = list(best_per_line_keyword.values())
            else:
                best_per_line: Dict[int, Dict[str, Any]] = {}
                for m in matches:
                    ln = m.get("line_number", -1)
                    if ln not in best_per_line or m["score"] > best_per_line[ln]["score"]:
                        best_per_line[ln] = m
                matches = list(best_per_line.values())

        if matches and self.match_table_enrich:
            try:
                matches = TableRowEnricher().enrich(matches, lines, meta)
            except Exception as exc:
                logger.error(f"Table enrich error: {exc}", exc_info=True)

        return [to_match_detail(m, self.keyword_meta) for m in matches]
