"""
Модуль фильтрации бесполезных файлов тендерной документации.

Файлы фильтруются ДО скачивания, чтобы сэкономить время и трафик.
Фильтр работает по:
  1. Точному совпадению имени файла (без расширения) — SKIP_EXACT_NAMES
  2. Совпадению начала имени — SKIP_PREFIXES
  3. Расширению файла — SKIP_EXTENSIONS
  4. Файлам без расширения — skip_no_extension

DOCUMENT_SELECTION_V3: legacy-поведение ``should_skip_file()`` сохранено
(тот же union множеств), но каждый skip получает policy-класс:
  HARD_SKIP   — pipeline не должен исследовать никогда: технические
                контейнеры/подписи (.xml .sig .p7s .gge .sign .gsfx),
                сертификаты/ключи, control/result-control артефакты,
                изображения и чертёжные форматы, имена без расширения,
                невалидные имена;
  SOFT_SKIP   — семантический класс имени, обычно бесполезный, но с
                measured historical evidence: проект контракта/договора,
                извещение, ElectronicAuction*, печатные формы контракта,
                информация о контракте;
  EXECUTABLE  — legacy-фильтр пропускает файл.

HARD_SKIP не может быть повышен ни при каких условиях. SOFT_SKIP может
пройти только как единственный explicit last-resort документ конкретной
(procurement, category) — см. ``document_selection_v3``.
"""

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from utils.logger_config import get_logger

logger = get_logger()


class SkipPolicy(str, Enum):
    """V3-классификация исполнимости файла (см. docstring модуля)."""

    HARD_SKIP = "HARD_SKIP"
    SOFT_SKIP = "SOFT_SKIP"
    EXECUTABLE = "EXECUTABLE"


# ----- Встроенный список бесполезных файлов -----

# HARD_SKIP: точные имена (без расширения) — control/result-control артефакты.
HARD_SKIP_EXACT_NAMES: Set[str] = {
    "автоматический контроль",
    "подписи заключивших контракт",
    "!! в_помощь_участникам_закупок",
}

# SOFT_SKIP: точные имена — семантические классы с measured evidence.
SOFT_SKIP_EXACT_NAMES: Set[str] = {
    "информация о контракте",
    "извещение о проведении электронного аукциона",
}

# Legacy-множество — union, смысл should_skip_file() не меняется.
SKIP_EXACT_NAMES: Set[str] = HARD_SKIP_EXACT_NAMES | SOFT_SKIP_EXACT_NAMES

# HARD_SKIP префиксы: control/result-control артефакты.
HARD_SKIP_PREFIXES: List[str] = [
    "результат контроля",
    "положительный результат контроля",
    "control99",
]

# SOFT_SKIP префиксы: семантические классы (Phase 2 evidence audit их
# приоритезирует; см. document_selection_v3). Совпадение по началу имени (lower).
SOFT_SKIP_PREFIXES: List[str] = [
    "печатная форма контракта",
    "печатная форма доп. соглашения",
    "печатная форма электронного контракта",
    "контракт с учетом доп. соглашений",
    "доп. соглашение",
    "электронный контракт",
    # Данные подтверждены частотным разбором имён файлов (10.10):
    # «проект контракта/договора» ~3 000 файлов, «извещение» ~400,
    # платформенные артефакты «electronicauction…» ~300. Юридическая форма,
    # товарных данных в них нет — но есть единичные measured positives (V3).
    "проект контракта",
    "проект_контракта",
    "проект договора",
    "проект_договора",
    "извещение",
    "electronicauction",
]

# Legacy-множество — union, смысл should_skip_file() не меняется.
SKIP_PREFIXES: List[str] = HARD_SKIP_PREFIXES + SOFT_SKIP_PREFIXES

# Расширения файлов, которые точно не содержат полезных данных (HARD_SKIP).
# (контракты xml ЕИС, подписи, изображения печатей)
SKIP_EXTENSIONS: Set[str] = {
    ".xml",
    ".sig",
    ".p7s",
    # Растровые изображения: служебные подложки/иконки из архивов, полезного
    # текста нет (проверено на выборке — на выходе 1–3 символа каши). Сканы PDF
    # обрабатываются отдельной OCR-веткой (ENABLE_OCR).
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    # Криптоконтейнеры/подписи — не документы.
    ".gge",
    ".sign",
    ".gsfx",
    # Сертификаты/ключи.
    ".cer",
    ".crt",
    ".key",
    ".pem",
    # Чертёжные форматы: текстового слоя для извлечения нет.
    ".dwg",
    ".dxf",
    ".dwf",
}

#: Semantic labels for SOFT_SKIP files (Phase 4 priority is derived from these).
SOFT_CLASS_PROJECT_CONTRACT = "PROJECT_CONTRACT"
SOFT_CLASS_NOTICE = "NOTICE"
SOFT_CLASS_ELECTRONIC_AUCTION = "ELECTRONIC_AUCTION"
SOFT_CLASS_PRINTED_CONTRACT_FORM = "PRINTED_CONTRACT_FORM"
SOFT_CLASS_CONTRACT_FORM_OTHER = "CONTRACT_FORM_OTHER"
SOFT_CLASS_CONTRACT_INFO = "CONTRACT_INFO"
SOFT_CLASS_NUMERIC_NAME = "NUMERIC_NAME"
SOFT_CLASS_OTHER = "SOFT_OTHER"

_PROJECT_CONTRACT_PREFIXES = (
    "проект контракта",
    "проект_контракта",
    "проект договора",
    "проект_договора",
)
_CONTRACT_FORM_OTHER_PREFIXES = (
    "контракт с учетом доп. соглашений",
    "доп. соглашение",
    "электронный контракт",
)


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
    """Собирает финальные множества из встроенных + пользовательских правил.

    Custom-правила (skip_files.json) семантически неизвестны, поэтому
    классифицируются как HARD_SKIP (fail-closed: их нельзя повышать).
    """
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
_SOFT_EXACT = frozenset(SOFT_SKIP_EXACT_NAMES)
_SOFT_PREFIXES = frozenset(SOFT_SKIP_PREFIXES)


def _split(file_name: Optional[str]) -> Tuple[str, str]:
    name = (file_name or "").strip()
    if not name:
        return "", ""
    path = Path(name)
    return path.suffix.lower(), path.stem.lower().strip()


def classify_skip_policy(file_name: Optional[str]) -> SkipPolicy:
    """V3-классификация исполнимости: HARD_SKIP / SOFT_SKIP / EXECUTABLE.

    Инвариант: ``classify_skip_policy(name) != EXECUTABLE`` тогда и только
    тогда, когда legacy ``should_skip_file(name) is True``.
    """
    if not file_name or not file_name.strip():
        return SkipPolicy.HARD_SKIP
    ext, stem = _split(file_name)

    # 1. Файл без расширения (например "Информация о контракте").
    if not ext:
        return SkipPolicy.HARD_SKIP

    # 2. Расширение в чёрном списке — технический контейнер/подпись/растр.
    if ext in _EXTENSIONS:
        return SkipPolicy.HARD_SKIP

    # 3. Точное совпадение имени (без расширения).
    if stem in _EXACT:
        return SkipPolicy.SOFT_SKIP if stem in _SOFT_EXACT else SkipPolicy.HARD_SKIP

    # 4. Совпадение по префиксу.
    for prefix in _PREFIXES:
        if stem.startswith(prefix):
            return SkipPolicy.SOFT_SKIP if prefix in _SOFT_PREFIXES else SkipPolicy.HARD_SKIP

    # 5. Имя без букв (только цифры/разделители) — служебный артефакт.
    #    V3 evidence (2026-10-11): all 39 GLOBAL hard-only units were alpha-less
    #    EIS names (e.g. "1578.docx", "17238739.pdf") and every one carried
    #    real product/material terms in stored matches - a non-semantic name is
    #    not a technical container. Such files stay skippable everywhere except
    #    an explicit last-resort promotion (class NUMERIC_NAME, lowest priority).
    if not any(ch.isalpha() for ch in stem):
        return SkipPolicy.SOFT_SKIP

    return SkipPolicy.EXECUTABLE


def soft_skip_class(file_name: Optional[str]) -> Optional[str]:
    """Semantic-класс SOFT_SKIP файла; ``None`` если файл не SOFT_SKIP."""
    if classify_skip_policy(file_name) != SkipPolicy.SOFT_SKIP:
        return None
    _ext, stem = _split(file_name)
    if not any(ch.isalpha() for ch in stem):
        return SOFT_CLASS_NUMERIC_NAME
    if stem.startswith("electronicauction"):
        return SOFT_CLASS_ELECTRONIC_AUCTION
    if stem.startswith("извещение"):
        return SOFT_CLASS_NOTICE
    if stem.startswith(_PROJECT_CONTRACT_PREFIXES):
        return SOFT_CLASS_PROJECT_CONTRACT
    if stem.startswith("печатная форма"):
        return SOFT_CLASS_PRINTED_CONTRACT_FORM
    if stem.startswith(_CONTRACT_FORM_OTHER_PREFIXES):
        return SOFT_CLASS_CONTRACT_FORM_OTHER
    if stem == "информация о контракте":
        return SOFT_CLASS_CONTRACT_INFO
    return SOFT_CLASS_OTHER


def should_skip_file(file_name: Optional[str]) -> bool:
    """
    Возвращает True, если файл нужно пропустить (не скачивать и не обрабатывать).

    Legacy-семантика сохранена (тот же union HARD_SKIP + SOFT_SKIP):
    ``classify_skip_policy(file_name) != EXECUTABLE``.

    :param file_name: Имя файла из БД (может быть None)
    :return: True если файл бесполезен
    """
    return classify_skip_policy(file_name) != SkipPolicy.EXECUTABLE


def filter_links(
    links: List[Any],
) -> Tuple[List[Any], int]:
    """Фильтрует список ссылок, убирая бесполезные файлы.

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
