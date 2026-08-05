#!/usr/bin/env python3
"""
Умное извлечение релевантных фрагментов текста для совпадений
Решает проблемы:
1. Слишком длинные строки
2. Нечитаемый текст из Excel/PDF
3. Отсутствие контекста
4. Дублирование информации
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from rapidfuzz import fuzz


class SmartTextExtractor:
    """Умное извлечение релевантных фрагментов текста"""

    def __init__(self):
        self.max_fragment_length = 200  # Максимальная длина фрагмента
        self.context_words = 5          # Слов контекста с каждой стороны
        self.min_fragment_length = 20   # Минимальная длина фрагмента

    def extract_best_fragment(self, keyword: str, matched_line: str, score: float) -> Dict[str, Any]:
        """
        Извлекает лучший фрагмент для совпадения

        Returns:
            {
                'original_line': str,           # Оригинальная строка
                'clean_fragment': str,          # Очищенный фрагмент
                'highlighted_fragment': str,    # Фрагмент с подсветкой
                'context_before': str,          # Контекст до
                'context_after': str,           # Контекст после
                'match_position': int,          # Позиция совпадения
                'confidence': str,              # Уровень уверенности
                'extraction_method': str        # Метод извлечения
            }
        """

        # Очищаем исходную строку
        clean_line = self._clean_text(matched_line)

        # Находим лучшую позицию совпадения
        match_pos, match_method = self._find_best_match_position(keyword, clean_line)

        # Извлекаем фрагмент с контекстом
        fragment_info = self._extract_fragment_with_context(
            keyword, clean_line, match_pos, match_method
        )

        # Определяем уровень уверенности
        confidence = self._determine_confidence(score, len(fragment_info['clean_fragment']))

        return {
            'original_line': matched_line,
            'clean_fragment': fragment_info['clean_fragment'],
            'highlighted_fragment': fragment_info['highlighted_fragment'],
            'context_before': fragment_info['context_before'],
            'context_after': fragment_info['context_after'],
            'match_position': match_pos,
            'confidence': confidence,
            'extraction_method': match_method
        }

    def _clean_text(self, text: str) -> str:
        """Очищает текст от артефактов форматирования и OCR"""
        if not text:
            return ""

        # Убираем HTML теги
        text = re.sub(r'<[^>]+>', ' ', text)

        # Убираем служебные символы Excel/PDF
        text = re.sub(r'[│┌┐└┘├┤┬┴┼─═║╔╗╚╝╠╣╦╩╬]', ' ', text)

        # OCR артефакты: слипшиеся слова типа "БОбмазочная" -> "Б Обмазочная"
        # Разбиваем по границе строчная->заглавная внутри слова (кириллица и латиница)
        text = re.sub(r'([а-яa-z])([А-ЯA-Z])', r'\1 \2', text)

        # OCR артефакты: цифра слипшаяся со словом "2слоями" -> "2 слоями"
        text = re.sub(r'(\d)([а-яА-ЯёЁa-zA-Z])', r'\1 \2', text)
        text = re.sub(r'([а-яА-ЯёЁa-zA-Z])(\d)', r'\1 \2', text)

        # Убираем множественные пробелы и переносы
        text = re.sub(r'\s+', ' ', text)

        # Убираем повторяющиеся знаки препинания
        text = re.sub(r'[.]{3,}', '...', text)
        text = re.sub(r'[-]{3,}', '---', text)

        # Убираем лишние символы в начале и конце
        text = text.strip(' .,;:-_=+*#@!?()[]{}|\\/')

        return text

    def _find_best_match_position(self, keyword: str, text: str) -> Tuple[int, str]:
        """Находит лучшую позицию совпадения в тексте"""
        keyword_lower = keyword.lower()
        text_lower = text.lower()

        # 1. Точное совпадение
        exact_pos = text_lower.find(keyword_lower)
        if exact_pos != -1:
            return exact_pos, "exact_match"

        # 2. Совпадение по словам (все слова keyword есть в тексте)
        keyword_words = keyword_lower.split()
        if len(keyword_words) > 1:
            # Ищем первое слово, затем проверяем наличие остальных рядом
            for word in keyword_words:
                word_pos = text_lower.find(word)
                if word_pos != -1:
                    # Проверяем область вокруг этого слова
                    start = max(0, word_pos - 50)
                    end = min(len(text), word_pos + len(word) + 50)
                    context = text_lower[start:end]

                    # Считаем сколько слов keyword есть в контексте
                    words_found = sum(1 for w in keyword_words if w in context)
                    if words_found >= len(keyword_words) * 0.7:  # 70% слов найдено
                        return word_pos, "word_match"

        # 3. Fuzzy поиск лучшего фрагмента
        best_pos = 0
        best_score = 0

        # Разбиваем текст на перекрывающиеся фрагменты
        fragment_size = max(len(keyword) * 2, 50)
        step = fragment_size // 2

        for i in range(0, len(text) - fragment_size + 1, step):
            fragment = text[i:i + fragment_size]
            score = fuzz.partial_ratio(keyword_lower, fragment.lower())

            if score > best_score:
                best_score = score
                best_pos = i

        return best_pos, f"fuzzy_match_{best_score}"

    def _extract_fragment_with_context(self, keyword: str, text: str, match_pos: int, method: str) -> Dict[str, str]:
        """Извлекает фрагмент с контекстом"""

        # Определяем размер фрагмента
        if "exact_match" in method:
            # Для точного совпадения берем keyword + контекст
            fragment_start = max(0, match_pos - 30)
            fragment_end = min(len(text), match_pos + len(keyword) + 30)
        else:
            # Для fuzzy совпадения берем более широкий контекст
            fragment_start = max(0, match_pos - 50)
            fragment_end = min(len(text), match_pos + 100)

        # Корректируем границы по словам
        fragment_start = self._adjust_to_word_boundary(text, fragment_start, direction="left")
        fragment_end = self._adjust_to_word_boundary(text, fragment_end, direction="right")

        # Извлекаем фрагмент
        fragment = text[fragment_start:fragment_end].strip()

        # Ограничиваем длину
        if len(fragment) > self.max_fragment_length:
            # Обрезаем по предложениям
            fragment = self._truncate_by_sentences(fragment, self.max_fragment_length)

        # Создаем подсвеченную версию
        highlighted = self._highlight_keyword_in_fragment(keyword, fragment)

        # Извлекаем контекст до и после
        context_before = text[max(0, fragment_start - 50):fragment_start].strip()
        context_after = text[fragment_end:min(len(text), fragment_end + 50)].strip()

        # Обрезаем контекст до разумной длины
        if len(context_before) > 50:
            context_before = "..." + context_before[-47:]
        if len(context_after) > 50:
            context_after = context_after[:47] + "..."

        return {
            'clean_fragment': fragment,
            'highlighted_fragment': highlighted,
            'context_before': context_before,
            'context_after': context_after
        }

    def _adjust_to_word_boundary(self, text: str, pos: int, direction: str) -> int:
        """Корректирует позицию до границы слова"""
        if direction == "left":
            # Ищем начало слова влево
            while pos > 0 and not text[pos - 1].isspace():
                pos -= 1
        else:  # direction == "right"
            # Ищем конец слова вправо
            while pos < len(text) and not text[pos].isspace():
                pos += 1

        return pos

    def _truncate_by_sentences(self, text: str, max_length: int) -> str:
        """Обрезает текст по предложениям"""
        if len(text) <= max_length:
            return text

        # Ищем конец предложения в пределах лимита
        sentence_endings = ['.', '!', '?', ';']

        for i in range(max_length - 1, max_length // 2, -1):
            if i < len(text) and text[i] in sentence_endings:
                return text[:i + 1].strip()

        # Если не нашли предложение, обрезаем по словам
        words = text[:max_length].split()
        if len(words) > 1:
            words.pop()  # Убираем последнее неполное слово
            return ' '.join(words) + "..."

        return text[:max_length - 3] + "..."

    def _highlight_keyword_in_fragment(self, keyword: str, fragment: str) -> str:
        """Подсвечивает ключевое слово в фрагменте"""
        keyword_lower = keyword.lower()
        fragment_lower = fragment.lower()

        # Точное совпадение
        if keyword_lower in fragment_lower:
            # Находим все вхождения с сохранением регистра
            result = fragment
            start = 0
            while True:
                pos = fragment_lower.find(keyword_lower, start)
                if pos == -1:
                    break

                # Заменяем с сохранением оригинального регистра
                original_word = fragment[pos:pos + len(keyword)]
                highlighted = f"**{original_word}**"
                result = result[:pos] + highlighted + result[pos + len(keyword):]

                # Корректируем позиции из-за добавленных символов
                fragment_lower = result.lower()
                start = pos + len(highlighted)

            return result

        # Fuzzy подсветка по словам
        keyword_words = keyword_lower.split()
        result = fragment

        for word in keyword_words:
            if len(word) >= 3:  # Подсвечиваем только значимые слова
                # Ищем слово с границами
                pattern = r'\b' + re.escape(word) + r'\b'
                result = re.sub(pattern, f"**{word}**", result, flags=re.IGNORECASE)

        return result

    def _determine_confidence(self, score: float, fragment_length: int) -> str:
        """Определяет уровень уверенности в совпадении"""
        if score >= 95:
            return "высокая"
        elif score >= 85:
            return "хорошая"
        elif score >= 75:
            return "средняя"
        elif score >= 65:
            return "низкая"
        else:
            return "очень низкая"

    def format_for_database(self, extraction_result: Dict[str, Any]) -> Dict[str, str]:
        """Форматирует результат для сохранения в БД"""
        fragment = extraction_result['clean_fragment']

        # Создаем краткое описание
        if len(fragment) > 100:
            short_fragment = fragment[:97] + "..."
        else:
            short_fragment = fragment

        # Создаем полное описание с контекстом
        full_description = ""
        if extraction_result['context_before']:
            full_description += f"...{extraction_result['context_before']} "

        full_description += f"[{extraction_result['highlighted_fragment']}]"

        if extraction_result['context_after']:
            full_description += f" {extraction_result['context_after']}..."

        return {
            'matched_text': short_fragment,                    # Для основного поля
            'matched_display_text': full_description,          # Для отображения
            'extraction_method': extraction_result['extraction_method'],
            'confidence': extraction_result['confidence']
        }


def improve_existing_matches(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Улучшает существующие совпадения с помощью SmartTextExtractor

    Args:
        matches: Список совпадений из KeywordMatcher.process_text()

    Returns:
        Улучшенный список совпадений
    """
    extractor = SmartTextExtractor()
    improved_matches = []

    for match in matches:
        keyword = match.get('keyword', '')
        matched_line = match.get('matched_line', '')
        score = match.get('score', 0)

        if not keyword or not matched_line:
            improved_matches.append(match)
            continue

        # Извлекаем улучшенный фрагмент
        extraction_result = extractor.extract_best_fragment(keyword, matched_line, score)
        formatted_result = extractor.format_for_database(extraction_result)

        # Обновляем совпадение
        improved_match = match.copy()
        improved_match.update({
            'matched_line': formatted_result['matched_text'],
            'matched_display_text': formatted_result['matched_display_text'],
            'extraction_method': formatted_result['extraction_method'],
            'confidence_level': formatted_result['confidence'],
            'original_line': extraction_result['original_line']  # Сохраняем оригинал для отладки
        })

        improved_matches.append(improved_match)

    return improved_matches


if __name__ == "__main__":
    # Тестирование на реальных примерах
    extractor = SmartTextExtractor()

    test_cases = [
        {
            'keyword': 'усиление конструкций',
            'text': 'ЭМв т.ч. ОТмЗТЗТмИтого по расценкеСП Работы по реконструкции зданий и сооружений: разборка отдельных конструктивных элементов здания (сооружения), а также зданий (сооружений) в целомВсего по позицииУтепление покрытий: керамзитом (демонтаж)Демонтаж (разборка) сборных бетонных и железобетонных строительных конструкций ОЗП=0,8; ЭМ=0,8 к расх.; ЗПМ=0,8; МАТ=0 к расх.; ТЗ=0,8; ТЗМ=0,8 ОТЭМЗТИтого по расценкеФОТНР Работы по реконструкции зданий и сооружений: разборка отдельных конструктивных элементов здания (сооружения), а также зданий (сооружений) в целомСП Работы по реконструкции зданий и сооружений: усиление и замена существующих конструкций, возведение отдельных конструктивных элементовВсего по позицииРазборка покрытий кровель: из волнистых и полуволнистых хризотилцементных листовОбъем=1692 / 100ОТ ФОТНР Кровли СП Кровли Всего по позиции',
            'score': 100
        },
        {
            'keyword': 'промышленных полов',
            'text': '                     <td style="border-top: none;">Для покрытия полов в помещениях жилых, общественных и промышленных зданий</td>',
            'score': 100
        },
        {
            'keyword': 'манопур с',
            'text': 'Неманову Н.В.',
            'score': 75
        }
    ]

    print("=== Тестирование SmartTextExtractor ===\n")

    for i, test_case in enumerate(test_cases, 1):
        print(f"Тест {i}: {test_case['keyword']}")
        print(f"Оригинальный текст: {test_case['text'][:100]}...")

        result = extractor.extract_best_fragment(
            test_case['keyword'],
            test_case['text'],
            test_case['score']
        )

        formatted = extractor.format_for_database(result)

        print(f"Улучшенный фрагмент: {formatted['matched_text']}")
        print(f"Для отображения: {formatted['matched_display_text']}")
        print(f"Метод: {formatted['extraction_method']}")
        print(f"Уверенность: {formatted['confidence']}")
        print("-" * 80)