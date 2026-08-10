import re
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from rapidfuzz import fuzz

from database_work.database_connection import DatabaseManager
from utils.logger_config import get_logger
from document_processor.match_repository import MatchRepository
from document_processor.matching.table_row_matcher import TableRowMatcher
from document_processor.matching.table_row_enricher import TableRowEnricher
from document_processor.matching.composite_drainage_rule import match_composite_drainage
from document_processor.crm_taxonomy_loader import load_keyword_index

# Таблица замены латинских омоглифов на кириллицу (lowercase)
_LATIN_TO_CYRILLIC = str.maketrans({
    'a': 'а', 'b': 'в', 'c': 'с', 'e': 'е',
    'h': 'н', 'k': 'к', 'm': 'м', 'n': 'п',
    'o': 'о', 'p': 'р', 't': 'т', 'x': 'х', 'y': 'у',
})

# Паттерн: стык буквы и цифры без пробела (ПУ91 → ПУ 91, В25 → В 25)
_LETTER_DIGIT_BOUNDARY = re.compile(r'([а-яёa-z])([0-9])', re.IGNORECASE)
_DIGIT_LETTER_BOUNDARY = re.compile(r'([0-9])([а-яёa-z])', re.IGNORECASE)


def _normalize_ocr_line(line: str) -> str:
    """
    Нормализация строки для лучшего fuzzy-matching OCR-текста:
    1. Если слово содержит смесь латиницы и кириллицы → заменить латинские
       омоглифы на кириллические (a→а, c→с, e→е, o→о, p→р, x→х, y→у).
    2. Вставить пробел на стыке буквы и цифры (ПУ91 → ПУ 91).
    """
    # 1. Homoglyph normalization: только для слов со смешанными скриптами
    words = line.split()
    normalized_words = []
    for w in words:
        has_cyr = any('а' <= ch <= 'я' or ch == 'ё' for ch in w)
        has_lat = any('a' <= ch <= 'z' for ch in w)
        if has_cyr and has_lat:
            # Смешанное слово — OCR-артефакт, заменяем латиницу → кириллица
            w = w.translate(_LATIN_TO_CYRILLIC)
        normalized_words.append(w)
    result = ' '.join(normalized_words)

    # 2. Дефисы/тире → пробелы (ПУ-500-ФЛЕКС → ПУ 500 ФЛЕКС)
    result = re.sub(r'[\-\u2013\u2014]+', ' ', result)

    # 3. Пробел на стыке буква↔цифра
    result = _LETTER_DIGIT_BOUNDARY.sub(r'\1 \2', result)
    result = _DIGIT_LETTER_BOUNDARY.sub(r'\1 \2', result)

    # Схлопываем множественные пробелы
    result = re.sub(r'\s+', ' ', result).strip()

    return result


def _extract_json_phrases(data: Any, out: List[str]) -> None:
    if data is None:
        return
    if isinstance(data, str):
        value = data.strip()
        if value:
            out.append(value.lower())
        return
    if isinstance(data, (list, tuple)):
        for item in data:
            _extract_json_phrases(item, out)
        return
    if isinstance(data, dict):
        if "keywords" in data:
            _extract_json_phrases(data.get("keywords"), out)
        for key, value in data.items():
            if key == "keywords":
                continue
            _extract_json_phrases(value, out)


class KeywordMatcher:
    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()
        self.logger = get_logger()
        self.repository = MatchRepository(self.db)
        self._table_row_matcher = TableRowMatcher()
        self.keywords: List[str] = []
        self.stop_phrases: List[str] = []
        self.extra_phrases: List[str] = []
        try:
            self.min_score = int(os.getenv("MATCH_MIN_SCORE", "75"))
        except Exception:
            self.min_score = 75
        self.custom_thresholds: Dict[str, int] = {}
        self.keyword_meta: Dict[str, Dict[str, Any]] = {}
        self._load_keywords()
        self._load_extra_phrases()
        self._load_custom_thresholds()
        self._load_stop_phrases()
        try:
            self.logger.info(f"keywords_loaded: total={len(self.keywords)} extra={len(self.extra_phrases)} stop={len(self.stop_phrases)} min_score={self.min_score}")
            # Дамп ключевых слов в файл для диагностики
            debug_path = Path("keywords_debug.txt")
            with debug_path.open("w", encoding="utf-8") as f:
                f.write(f"# Total: {len(self.keywords)}, Extra: {len(self.extra_phrases)}, Stop: {len(self.stop_phrases)}\n")
                f.write(f"# Min score: {self.min_score}\n\n")
                for i, kw in enumerate(self.keywords, 1):
                    f.write(f"{i}. {kw}\n")
            self.logger.info(f"Ключевые слова сохранены в {debug_path.absolute()}")
        except Exception:
            pass

    def _load_keywords(self) -> None:
        """????????? ????????? ????? ?? CRM-??????????, ? ?? ?? product_catalog_2."""
        try:
            keyword_index = load_keyword_index(contour_code="procurement")
        except Exception as exc:
            self.logger.error(f"?????? ??? ???????? CRM-??????????: {exc}", exc_info=True)
            keyword_index = {}

        if not keyword_index:
            self.logger.warning("CRM taxonomy keywords are empty")
            self.keywords = []
            self.keyword_meta = {}
            return

        ordered = sorted(
            keyword_index.items(),
            key=lambda pair: (int(pair[1].get("weight") or 0), len(pair[0])),
            reverse=True,
        )
        self.keywords = [keyword for keyword, _ in ordered if len(keyword) >= 3]
        self.keyword_meta = {keyword: meta for keyword, meta in ordered if len(keyword) >= 3}
        self.logger.info(f"CRM taxonomy keywords loaded: {len(self.keywords)}")

    def _load_custom_thresholds(self) -> None:
        """Загружает индивидуальные пороги совпадения для фраз из keyword_thresholds.json"""
        path_env = os.getenv("KEYWORD_THRESHOLDS_JSON")
        candidates: List[Path] = []
        if path_env:
            candidates.append(Path(path_env))
        candidates.append(Path("keyword_thresholds.json"))

        for path in candidates:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, (int, float)):
                            self.custom_thresholds[k.lower().strip()] = int(v)
            except Exception as e:
                self.logger.error(f"Ошибка загрузки порогов из {path}: {e}")

        if self.custom_thresholds:
            self.logger.info(f"Загружено {len(self.custom_thresholds)} индивидуальных порогов совпадения")
            # Добавляем фразы из порогов в общий список, если их там нет
            for phrase in self.custom_thresholds.keys():
                if phrase not in self.keywords:
                    self.keywords.append(phrase)

    def _load_extra_phrases(self) -> None:
        path_env = os.getenv("DOCUMENT_EXTRA_PHRASES_JSON")
        candidates: List[Path] = []
        if path_env:
            candidates.append(Path(path_env))
        candidates.append(Path("user_keywords.json"))
        phrases: List[str] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            _extract_json_phrases(data, phrases)
        env_extra = os.getenv("EXTRA_KEYWORDS")
        if env_extra:
            for item in env_extra.split(","):
                v = item.strip()
                if v:
                    phrases.append(v.lower())
        if phrases:
            self.extra_phrases = list(dict.fromkeys(phrases))
            self.keywords = list(dict.fromkeys(self.keywords + self.extra_phrases))

    def _load_stop_phrases(self) -> None:
        sql = "SELECT phrase FROM document_stop_phrases WHERE phrase IS NOT NULL"
        try:
            rows = self.db.execute_query("tender_monitor", sql, fetch=True) or []
        except Exception as exc:
            self.logger.error(f"Ошибка при загрузке стоп-фраз: {exc}", exc_info=True)
            self.stop_phrases = []
            return
        items: List[str] = []
        for row in rows:
            value = row[0]
            if isinstance(value, str):
                value = value.strip()
                if value:
                    items.append(value.lower())
        self.stop_phrases = list(dict.fromkeys(items))

    def _is_blocked_by_stop_phrase(self, keyword: str, text_lower: str) -> bool:
        for phrase in self.stop_phrases:
            if keyword in phrase and phrase in text_lower:
                return True
        return False

    def process_text(self, text: str, line_meta: Optional[Dict[int, Dict[str, Any]]] = None, category_scores: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        if not self.keywords:
            self.logger.warning("No keywords loaded! process_text returning empty.")
            return []

        # Log first 5 keywords for debug if needed, or just count
        if len(text) > 0:
             self.logger.info(f"Processing text len={len(text)} against {len(self.keywords)} keywords")

        text_lower = text.lower()
        lines = text.splitlines()
        # Нормализация OCR-артефактов: омоглифы + дефисы + пробелы буква↔цифра
        lines_lower = [_normalize_ocr_line(ln.lower()) for ln in lines]

        # Склеиваем соседние строки для поиска ключевых слов, разбитых по строкам
        # (часто в PDF/OCR одна фраза разделена переносом)
        combined_lines = list(lines_lower)  # копия
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
        use_table_multi = (
            bool(table_line_numbers)
            and os.getenv("MATCH_TABLE_ALL_ROWS", "1") == "1"
        )
        if use_table_multi:
            self.logger.debug(
                f"Table multi-match: {len(table_line_numbers)} table rows detected"
            )
        try:
            compound_matches = match_composite_drainage(lines, line_meta=meta)
            if compound_matches:
                matches.extend(compound_matches)
                self.logger.info(
                    f"compound_rule composite_drainage: matches={len(compound_matches)}"
                )
        except Exception as exc:
            self.logger.error(f"compound_rule composite_drainage error: {exc}", exc_info=True)

        # Regex для проверки строгих "БМ" + цифры.
        # Например: "бм 0332", "бм0332", "бм-0332"
        bm_strict_pattern = re.compile(r'^бм\s*[-]?\s*\d+')

        # Optimization: pre-calculate total lines to avoid len() calls
        total_lines = len(lines_lower)
        if total_lines == 0:
            return []

        self.logger.debug(f"Matching {len(self.keywords)} keywords against {total_lines} lines")

        import os as _os
        _skip_threshold = float(_os.getenv("CLASSIFIER_SKIP_THRESHOLD", "1"))
        _lite_threshold = float(_os.getenv("CLASSIFIER_LITE_THRESHOLD", "4"))
        for keyword in self.keywords:
            keyword_meta = self.keyword_meta.get(keyword) or {}
            keyword_negative_phrases = keyword_meta.get("negative_phrases") or []
            # Category pre-filter: skip (<skip_threshold) or lite-mode (<lite_threshold)
            _lite_mode = False
            if category_scores:
                _codes = keyword_meta.get("category_codes") or []
                if _codes:
                    _cat_score = category_scores.get(_codes[0], 10.0)
                    if _cat_score < _skip_threshold:
                        continue
                    _lite_mode = _cat_score < _lite_threshold
            if use_table_multi:
                matches.extend(
                    self._table_row_matcher.match_keyword(
                        keyword,
                        lines=lines,
                        lines_lower=lines_lower,
                        meta=meta,
                        min_score=max(self.min_score, 90) if _lite_mode else self.min_score,
                        custom_thresholds=self.custom_thresholds,
                        normalize_line=_normalize_ocr_line,
                        is_blocked_by_stop_phrase=self._is_blocked_by_stop_phrase,
                        text_lower=text_lower,
                        bm_strict_pattern=bm_strict_pattern,
                    )
                )
                continue

            # Check if keyword STARTS with "bm" pattern
            is_bm_keyword = bool(bm_strict_pattern.match(keyword))

            # Use strict matching for:
            # 1. "BM" keywords (special requirement)
            # 2. Short keywords (<= 5 chars) to avoid false positives with partial_ratio
            #    (e.g. "act" matching "factor", "75.00" matching "175.00")
            # 3. Lite mode: low LLM priority category (exact match only, no fuzzy)
            use_strict_match = is_bm_keyword or len(keyword) <= 5 or _lite_mode

            if use_strict_match:
                found_exact = False
                best_score = 0
                best_line_idx = -1

                # Ищем точное вхождение ключевого слова в строках с учетом границ слова
                # Чтобы "бм 0332" НЕ находилось внутри "бм 03321"
                pattern = r'(^|\s|[^a-zA-Z0-9а-яА-Я])' + re.escape(keyword) + r'($|\s|[^a-zA-Z0-9а-яА-Я])'

                for idx, line_text in enumerate(lines_lower):
                    if re.search(pattern, line_text):
                        found_exact = True
                        best_score = 100
                        best_line_idx = idx
                        break # Нашли точное совпадение - достаточно

                if not found_exact:
                    continue
            else:
                # Стандартная логика fuzzy matching
                required_score = self.custom_thresholds.get(keyword, self.min_score)

                # Проверка стоп-фраз перед тяжелыми вычислениями
                if self._is_blocked_by_stop_phrase(keyword, text_lower):
                    continue

                # Ищем строку с наивысшим score
                best_score = 0
                best_line_idx = -1

                kw_len = len(keyword)
                kw_words = keyword.split()
                # Минимальная длина строки — 30% от длины keyword
                min_line_len = max(3, int(kw_len * 0.3))

                for idx, line in enumerate(combined_lines):
                    line_len = len(line)
                    if line_len < min_line_len:
                        continue

                    # Выбираем scorer:
                    # - Если строка короткая (сравнима с keyword) -> fuzz.ratio
                    # - Если строка длинная -> fuzz.token_set_ratio (вместо partial_ratio)
                    #   token_set_ratio лучше работает с перестановками и лишними словами,
                    #   но не матчит "обрывки" как partial_ratio.
                    if line_len < kw_len * 1.5:
                        score = fuzz.ratio(keyword, line)
                    else:
                        score = fuzz.token_set_ratio(keyword, line)

                    if score > best_score:
                        best_score = score
                        best_line_idx = idx

                if best_score < required_score:
                    # Fallback: если score между 50 и threshold, проверяем stem coverage
                    # Это помогает с русским склонением: "композитных" → stem "композитн"
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
                                    # рм3→рм 3, 1к→1 к (нормализация разделяет буквы и цифры)
                                    w_norm = _normalize_ocr_line(w)
                                    if w_norm != w and w_norm in matched_line_lower:
                                        words_present += 1
                        if meaningful_words:
                            coverage = words_present / len(meaningful_words)
                            if coverage >= 0.8:
                                # Все корни слов найдены — принимаем как yellow match
                                best_score = required_score  # Повышаем до порога
                            else:
                                continue
                        else:
                            continue
                    else:
                        continue

                # Дополнительная проверка покрытия слов для многословных keywords
                # Включаем 2-буквенные alpha слова (пу, эп, кв — важные идентификаторы)
                if len(kw_words) >= 2 and best_line_idx >= 0:
                    matched_line_lower = combined_lines[best_line_idx]
                    words_present = 0
                    meaningful_words = [w for w in kw_words if len(w) >= 2 and any(ch.isalpha() for ch in w)]
                    if not meaningful_words:
                        meaningful_words = [w for w in kw_words if len(w) >= 3 and not w.isdigit()]

                    for w in meaningful_words:
                        # Сначала точное вхождение
                        if w in matched_line_lower:
                            words_present += 1
                        else:
                            # Нечёткая проверка: корень слова (первые N символов)
                            # "композитные" ↔ "композитных" (корень "композитн")
                            stem_len = max(4, int(len(w) * 0.7))
                            stem = w[:stem_len]
                            if stem in matched_line_lower:
                                words_present += 1
                            else:
                                # рм3→рм 3, 1к→1 к (нормализация разделяет буквы и цифры)
                                w_norm = _normalize_ocr_line(w)
                                if w_norm != w and w_norm in matched_line_lower:
                                    words_present += 1

                    if meaningful_words:
                        coverage = words_present / len(meaningful_words)
                        if coverage < 0.7:
                            continue

                # Проверка числовых токенов: ВСЕ числа из keyword должны быть в строке
                # "манопокс 331" НЕ должен матчить "манопокс 334"
                # "денстоп пу 500" НЕ должен матчить "Денстоп ЭП 500" если ПУ≠ЭП
                if best_line_idx >= 0:
                    kw_numbers = [w for w in kw_words if w.isdigit()]
                    if kw_numbers:
                        matched_line_lower = combined_lines[best_line_idx]
                        for num in kw_numbers:
                            # Regex word boundary — находит "500" в "500," и "91."
                            pattern = r'(?:^|\b)' + re.escape(num) + r'(?:\b|$)'
                            if not re.search(pattern, matched_line_lower):
                                best_score = 0
                                break
                        if best_score == 0:
                            continue

            # Определяем исходную строку для результата
            if best_line_idx < len(lines):
                matched_line = lines[best_line_idx]
                line_number = best_line_idx + 1
            elif best_line_idx < len(combined_originals):
                matched_line = combined_originals[best_line_idx]
                # Для склеенных строк: номер = первая из двух склеенных
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
            }
            if keyword_meta:
                item["taxonomy"] = {
                    "category_code": (keyword_meta.get("category_codes") or [None])[0],
                    "category_name": (keyword_meta.get("category_names") or [None])[0],
                    "subcategory_code": (keyword_meta.get("subcategory_codes") or [None])[0],
                    "subcategory_name": (keyword_meta.get("subcategory_names") or [None])[0],
                    "term_type": keyword_meta.get("term_type"),
                    "negative_phrases": keyword_meta.get("negative_phrases") or [],
                }
            if line_number in meta:
                extra = meta[line_number]
                for k, v in extra.items():
                    item[k] = v
                cells = extra.get("cells")
                if isinstance(cells, list) and cells:
                    best_cell_score = -1
                    best_cell = None

                    # Если использовался строгий поиск (use_strict_match),
                    # сначала ищем ячейку, которая строго содержит keyword.
                    # Это исправит ситуацию, когда строка найдена (т.к. keyword есть),
                    # но best_cell выбирается неправильно (не та ячейка).
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

                    # Если строгий поиск не нашел ячейку (или не использовался), используем fuzzy
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

        # Дедупликация: для таблиц сохраняем все keyword на строке;
        # для обычного текста — одно лучшее совпадение на строку.
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

        # Обогащение таблиц: row_data, заголовки, контекст ±N строк
        if matches and os.getenv("MATCH_TABLE_ENRICH", "1") == "1":
            try:
                matches = TableRowEnricher().enrich(matches, lines, meta)
            except Exception as exc:
                self.logger.error(f"Table enrich error: {exc}", exc_info=True)

        # Умное извлечение текста (если включено)
        if os.getenv("ENABLE_SMART_EXTRACTION", "0") == "1" and matches:
            try:
                from smart_text_extractor import improve_existing_matches
                matches = improve_existing_matches(matches)
                self.logger.debug(f"Smart text extraction applied to {len(matches)} matches")
            except Exception as e:
                self.logger.error(f"Smart extraction error: {e}")
                # Продолжаем с оригинальными совпадениями

        return matches

    def save_matches(
        self,
        tender_id: int,
        registry_type: str,
        file_name: str,
        matches: List[Dict[str, Any]],
        yandex_path: Optional[str] = None,
        worker_id: int = 0,
        processing_time_seconds: float = 0.0,
        total_files_processed: int = 0,
        total_size_bytes: int = 0,
        folder_name: Optional[str] = None,
        merge_existing: bool = False,
    ) -> None:
        self.repository.save_matches(
            tender_id, registry_type, file_name, matches, yandex_path,
            worker_id, processing_time_seconds, total_files_processed, total_size_bytes,
            folder_name,
            merge_existing=merge_existing,
        )

    def save_file_error(
        self,
        tender_id: int,
        registry_type: str,
        file_name: str,
        error_reason: str,
        worker_id: int = 0,
        folder_name: Optional[str] = None,
    ) -> None:
        self.repository.save_file_error(
            tender_id, registry_type, file_name, error_reason, worker_id, folder_name,
        )
