import re

# Таблица замены латинских омоглифов на кириллицу (lowercase)
_LATIN_TO_CYRILLIC = str.maketrans({
    'a': 'а', 'b': 'в', 'c': 'с', 'e': 'е',
    'h': 'н', 'k': 'к', 'm': 'м', 'n': 'п',
    'o': 'о', 'p': 'р', 't': 'т', 'x': 'х', 'y': 'у',
})

_LETTER_DIGIT_BOUNDARY = re.compile(r'([а-яёa-z])([0-9])', re.IGNORECASE)
_DIGIT_LETTER_BOUNDARY = re.compile(r'([0-9])([а-яёa-z])', re.IGNORECASE)

def normalize_ocr_line(line: str) -> str:
    words = line.split()
    normalized_words = []
    for w in words:
        has_cyr = any('а' <= ch <= 'я' or ch == 'ё' for ch in w)
        has_lat = any('a' <= ch <= 'z' for ch in w)
        if has_cyr and has_lat:
            w = w.translate(_LATIN_TO_CYRILLIC)
        normalized_words.append(w)
    result = ' '.join(normalized_words)
    result = re.sub(r'[\-\u2013\u2014]+', ' ', result)
    result = _LETTER_DIGIT_BOUNDARY.sub(r'\1 \2', result)
    result = _DIGIT_LETTER_BOUNDARY.sub(r'\1 \2', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result
