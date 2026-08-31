"""
Модуль фильтрации бесполезных файлов тендерной документации.

Файлы фильтруются ДО скачивания, чтобы сэкономить время и трафик.
Фильтр работает по:
  1. Точному совпадению имени файла (без расширения) — SKIP_EXACT_NAMES
  2. Совпадению начала имени — SKIP_PREFIXES
  3. Расширению файла — SKIP_EXTENSIONS
  4. Файлам без расширения — skip_no_extension
"""

import json
import os
import re
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from utils.logger_config import get_logger

logger = get_logger()

# ----- Встроенный список бесполезных файлов -----

# Точные имена (без расширения), которые нужно пропускать
SKIP_EXACT_NAMES: Set[str] = {
    "информация о контракте",
    "извещение о проведении электронного аукциона",
    "автоматический контроль",
    "!! в_помощь_участникам_закупок",
    "подписи заключивших контракт",
}

# Префиксы имён файлов (без расширения), которые нужно пропускать.
# Совпадение проверяется по началу имени (lower).
SKIP_PREFIXES: List[str] = [
    "печатная форма контракта",
    "печатная форма доп. соглашения",
    "печатная форма электронного контракта",
    "контракт с учетом доп. соглашений",
    "доп. соглашение",
    "электронный контракт",
    "результат контроля",
    "положительный результат контроля",
    "control99",
]

# Расширения файлов, которые точно не содержат полезных данных
# (контракты xml ЕИС, подписи, изображения печатей)
SKIP_EXTENSIONS: Set[str] = {
    ".xml",
    ".sig",
    ".p7s",
}


def _load_custom_skip_list() -> Optional[dict]:
    """Загружает дополнительные правила из skip_files.json, если он есть."""
    path_env = os.getenv("SKIP_FILES_JSON")
    candidates = []
    if path_env:
        candidates.append(Path(path_env))
    candidates.append(Path("skip_files.json"))

    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"Ошибка загрузки skip-list из {path}: {e}")
    return None


def _build_skip_sets():
    """Собирает финальные множества из встроенных + пользовательских правил."""
    exact = set(SKIP_EXACT_NAMES)
    prefixes = list(SKIP_PREFIXES)
    extensions = set(SKIP_EXTENSIONS)

    custom = _load_custom_skip_list()
    if custom:
        for name in custom.get("exact_names", []):
            if isinstance(name, str):
                exact.add(name.lower().strip())
        for prefix in custom.get("prefixes", []):
            if isinstance(prefix, str):
                prefixes.append(prefix.lower().strip())
        for ext in custom.get("extensions", []):
            if isinstance(ext, str):
                ext = ext.strip().lower()
                if not ext.startswith("."):
                    ext = "." + ext
                extensions.add(ext)

    return exact, prefixes, extensions


# Инициализация при импорте
_EXACT, _PREFIXES, _EXTENSIONS = _build_skip_sets()


def should_skip_file(file_name: Optional[str]) -> bool:
    """
    Возвращает True, если файл нужно пропустить (не скачивать и не обрабатывать).

    :param file_name: Имя файла из БД (может быть None)
    :return: True если файл бесполезен
    """
    if not file_name or not file_name.strip():
        # Файл без имени — пропускаем
        return True

    name = file_name.strip()
    path = Path(name)
    ext = path.suffix.lower()
    stem = path.stem.lower().strip()

    # 1. Файл без расширения (например "Информация о контракте")
    if not ext:
        return True

    # 2. Расширение в чёрном списке
    if ext in _EXTENSIONS:
        return True

    # 3. Точное совпадение имени (без расширения)
    if stem in _EXACT:
        return True

    # 4. Совпадение по префиксу
    for prefix in _PREFIXES:
        if stem.startswith(prefix):
            return True

    return False


def filter_links(
    links: List[Any],
) -> Tuple[List[Any], int]:
    """
    Фильтрует список ссылок, убирая бесполезные файлы.

    :param links: Список кортежей, содержащих file_name на 2-й позиции
    :return: (отфильтрованный список, количество пропущенных)
    """
    filtered = []
    skipped = 0
    for link in links:
        url = link[0]
        file_name = link[1]
        if should_skip_file(file_name):
            skipped += 1
        else:
            filtered.append(link)
    return filtered, skipped
