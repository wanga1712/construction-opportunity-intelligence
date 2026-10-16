import subprocess
import zipfile
from pathlib import Path
from typing import List


class ArchiveExtractor:
    """
    Отвечает за распаковку ZIP и RAR архивов.
    Поддерживает многотомные RAR-архивы и рекурсивную распаковку "архив в архиве".
    """
    def __init__(self, logger):
        self.logger = logger

    #: Extensions whose payload is itself a ZIP container that our parsers read
    #: natively (OOXML/ODF/GSFX). They must never be treated as archives even
    #: though `zipfile.is_zipfile` returns True for them.
    _NATIVE_ZIP_CONTAINERS = frozenset(
        {".xlsx", ".xlsm", ".xltx", ".docx", ".pptx", ".odt", ".ods", ".gsfx"}
    )

    def _sanitize_name(self, name: str) -> str:
        """
        Очистка имени файла (копия логики из http_client).
        """
        import os
        if not name:
            return "unknown_file"

        forbidden_chars = [
            "/", "\\", ":", "*", "?", "<", ">", "|", '"',
            "+", "%", "#", "&", "{", "}", "[", "]", "=", ";", ",", "'", "@", "!", "$", "`", "^"
        ]

        cleaned = name
        for char in forbidden_chars:
            cleaned = cleaned.replace(char, "_")

        cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32)
        cleaned = cleaned.replace("(", "_").replace(")", "_").replace("~", "_")

        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")

        cleaned = cleaned.strip(" ._")

        if not cleaned:
            return "unknown_file"

        if len(cleaned) > 200:
            base, ext = os.path.splitext(cleaned)
            if len(ext) > 10:
                ext = ""
            limit = 200 - len(ext)
            cleaned = base[:limit] + ext

        return cleaned

    def is_archive(self, path: Path) -> bool:
        return self._is_zip(path) or self._is_rar_entry_point(path) or self._is_7z(path)

    def _is_zip(self, path: Path) -> bool:
        # Recognize by extension so corrupt ZIPs reach extraction diagnostics
        # instead of being silently treated as unsupported ordinary files.
        #
        # UNSUPPORTED_DOC_RECOVERY_V1: EIS sometimes serves a ZIP archive under a
        # non-archive name (e.g. a "contract.rtf" that is really a ZIP holding
        # the contractor's estimate). Detect those by content, but never shred
        # OOXML/ODF/GSFX containers that our parsers read directly.
        try:
            suffix = path.suffix.lower()
        except Exception:
            return False
        if suffix == ".zip":
            return True
        if suffix in self._NATIVE_ZIP_CONTAINERS:
            return False
        try:
            if not zipfile.is_zipfile(str(path)):
                return False
            # An OOXML package ([Content_Types].xml) is a document, not a plain
            # archive: never shred it into raw XML members.
            with zipfile.ZipFile(str(path)) as zf:
                if "[Content_Types].xml" in set(zf.namelist()):
                    return False
            return True
        except Exception:
            return False

    def _is_7z(self, path: Path) -> bool:
        try:
            return path.suffix.lower() == ".7z"
        except Exception:
            return False

    def _is_rar(self, path: Path) -> bool:
        try:
            return path.suffix.lower() in (".rar", ".r00")
        except Exception:
            return False

    def _is_rar_entry_point(self, path: Path) -> bool:
        """Возвращает True только для первой части многочастного RAR (.rar или .r00).
        Части .r01, .r02 и т.д., а также .part2.rar, .part3.rar — не точки входа."""
        suffix = path.suffix.lower()
        name = path.name.lower()

        # Проверка для нового формата именования WinRAR (.partN.rar)
        if ".part" in name and name.endswith(".rar"):
            # Точкой входа считается только part1.rar (или part01.rar и т.д.)
            import re
            return bool(re.search(r'\.part0*1\.rar$', name))

        return suffix == ".rar" or suffix == ".r00"

    def _extract_zip_and_collect(self, zip_path: Path, dest_dir: Path) -> List[Path]:
        extracted: List[Path] = []
        try:
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                for member in zf.infolist():
                    try:
                        # Нормализуем имя для кириллицы (cp437 → utf-8)
                        try:
                            name = member.filename.encode("cp437").decode("utf-8")
                        except Exception:
                            name = member.filename
                        extracted_path = Path(zf.extract(member, path=str(dest_dir)))
                        if extracted_path.is_file():
                            extracted.append(extracted_path)
                    except Exception as exc:
                        self.logger.warning(
                            f"ZIP member extraction failed in {zip_path.name}: "
                            f"{member.filename}: {exc}",
                            exc_info=True,
                        )
        except Exception as exc:
            self.logger.error(
                f"ZIP extraction failed for {zip_path.name}: {exc}",
                exc_info=True,
            )
            return []
        # Do not delete the canonical durable source archive here.  S13_V2
        # records document_files.local_path for the downloaded source file and
        # that path must survive parser/matcher failures.  Future retention
        # cleanup may remove it explicitly, but extraction is not that owner.
        return extracted

    def _extract_rar_and_collect(self, rar_path: Path, dest_dir: Path) -> List[Path]:
        """Запускает unrar на первой части архива. Остальные части (.r01, .r02...)
        unrar найдёт автоматически если они лежат в той же папке."""
        extracted_before: set = set()
        try:
            extracted_before = {
                p.resolve()
                for p in dest_dir.rglob("*")
                if p.is_file()
            }
        except Exception:
            pass
        try:
            cmd = ["unrar", "x", "-o+", str(rar_path), str(dest_dir) + "/"]
            result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode != 0 and result.stderr:
                self.logger.warning(f"unrar вернул ошибку для {rar_path.name}: {result.stderr[:200]}")
        except Exception as e:
            self.logger.warning(f"unrar недоступен: {e}")
            return []
        extracted: List[Path] = []
        try:
            for p in dest_dir.rglob("*"):
                try:
                    if p.is_file() and p.resolve() not in extracted_before:
                        extracted.append(p)
                except Exception:
                    continue
        except Exception:
            pass
        # Do not delete the canonical durable source archive here.
        return extracted

    def _extract_7z_and_collect(self, seven_zip_path: Path, dest_dir: Path) -> List[Path]:
        extracted_before = set()
        try:
            extracted_before = {
                p.resolve()
                for p in dest_dir.rglob("*")
                if p.is_file()
            }
        except Exception:
            pass

        try:
            cmd = [
                "/usr/bin/7z",
                "x",
                "-y",
                f"-o{dest_dir}",
                str(seven_zip_path),
            ]
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0 and result.stderr:
                self.logger.warning(
                    f"7z extraction failed for {seven_zip_path.name}: "
                    f"{result.stderr[:200]}"
                )
        except Exception as exc:
            self.logger.warning(f"7z unavailable: {exc}")
            return []

        extracted: List[Path] = []
        try:
            for p in dest_dir.rglob("*"):
                if p.is_file() and p.resolve() not in extracted_before:
                    extracted.append(p)
        except Exception:
            pass
        return extracted

    def extract_recursive(self, archive_path: Path, dest_dir: Path, depth: int = 0) -> List[Path]:
        """Рекурсивное извлечение ZIP, RAR и 7z архивов."""
        MAX_DEPTH = 3
        if depth > MAX_DEPTH:
            self.logger.warning(f"Достигнут лимит глубины вложенности архивов ({MAX_DEPTH}): {archive_path.name}")
            return []

        if self._is_zip(archive_path):
            raw = self._extract_zip_and_collect(archive_path, dest_dir)
        elif self._is_rar_entry_point(archive_path):
            raw = self._extract_rar_and_collect(archive_path, dest_dir)
        elif self._is_7z(archive_path):
            raw = self._extract_7z_and_collect(archive_path, dest_dir)
        else:
            return [archive_path]

        result: List[Path] = []
        for p in raw:
            if self._is_zip(p):
                result.extend(self.extract_recursive(p, dest_dir, depth + 1))
            elif self._is_rar_entry_point(p):
                result.extend(self.extract_recursive(p, dest_dir, depth + 1))
            elif self._is_7z(p):
                result.extend(self.extract_recursive(p, dest_dir, depth + 1))
            else:
                result.append(p)
        return result
