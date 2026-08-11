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
        return self._is_zip(path) or self._is_rar_entry_point(path)

    def _is_zip(self, path: Path) -> bool:
        # Recognize by extension so corrupt ZIPs reach extraction diagnostics
        # instead of being silently treated as unsupported ordinary files.
        try:
            return path.suffix.lower() == ".zip"
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
            for p in dest_dir.iterdir():
                if p.is_file():
                    extracted_before.add(p.resolve())
        except Exception:
            pass
        try:
            cmd = ["unrar", "--extract", "--force", str(rar_path), str(dest_dir) + "/"]
            result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode != 0 and result.stderr:
                self.logger.warning(f"unrar вернул ошибку для {rar_path.name}: {result.stderr[:200]}")
        except Exception as e:
            self.logger.warning(f"unrar недоступен: {e}")
            return []
        extracted: List[Path] = []
        try:
            for p in dest_dir.iterdir():
                try:
                    if p.is_file() and p.resolve() not in extracted_before and p.suffix.lower() not in (".rar", ".r00", ".r01", ".r02", ".r03", ".r04", ".r05", ".r06", ".r07", ".r08", ".r09"):
                        extracted.append(p)
                except Exception:
                    continue
        except Exception:
            pass
        # Do not delete the canonical durable source archive here.
        return extracted

    def extract_recursive(self, archive_path: Path, dest_dir: Path, depth: int = 0) -> List[Path]:
        """Рекурсивное извлечение архивов (ZIP, RAR). Архивы внутри архивов тоже распаковываются."""
        MAX_DEPTH = 3
        if depth > MAX_DEPTH:
            self.logger.warning(f"Достигнут лимит глубины вложенности архивов ({MAX_DEPTH}): {archive_path.name}")
            return []

        if archive_path.suffix.lower() == ".zip":
            raw = self._extract_zip_and_collect(archive_path, dest_dir)
        elif self._is_rar_entry_point(archive_path):
            raw = self._extract_rar_and_collect(archive_path, dest_dir)
        else:
            return [archive_path]

        result: List[Path] = []
        for p in raw:
            if p.suffix.lower() == ".zip" and zipfile.is_zipfile(p):
                result.extend(self.extract_recursive(p, dest_dir, depth + 1))
            elif self._is_rar_entry_point(p):
                result.extend(self.extract_recursive(p, dest_dir, depth + 1))
            else:
                result.append(p)
        return result
