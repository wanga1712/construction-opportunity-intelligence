import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from document_processor.archive_extractor import ArchiveExtractor


class _Logger:
    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class ArchiveExtractorTests(unittest.TestCase):
    def setUp(self):
        self.extractor = ArchiveExtractor(_Logger())

    def test_rar_nested_directory_collection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "sample.rar"
            destination = root / "out"
            destination.mkdir()

            def extract(_cmd, **_kwargs):
                nested = destination / "folder"
                nested.mkdir()
                (nested / "document.docx").write_bytes(b"data")
                return type("Result", (), {"returncode": 0, "stderr": b""})()

            with patch("document_processor.archive_extractor.subprocess.run", side_effect=extract):
                files = self.extractor._extract_rar_and_collect(archive, destination)

            self.assertEqual([destination / "folder" / "document.docx"], files)

    def test_rar_nested_archive_discovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "outer.rar"
            destination = root / "out"
            destination.mkdir()
            nested = destination / "inner.7z"
            final = destination / "document.txt"

            def rar_extract(_archive, _destination):
                nested.write_bytes(b"archive")
                return [nested]

            def seven_zip_extract(_archive, _destination):
                final.write_bytes(b"data")
                return [final]

            with patch.object(
                self.extractor,
                "_extract_rar_and_collect",
                side_effect=rar_extract,
            ), patch.object(
                self.extractor,
                "_extract_7z_and_collect",
                side_effect=seven_zip_extract,
            ):
                files = self.extractor.extract_recursive(archive, destination)

            self.assertEqual([final], files)

    def test_zip_existing_behavior(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "sample.zip"
            destination = root / "out"
            destination.mkdir()
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("document.txt", "data")

            files = self.extractor.extract_recursive(archive, destination)

            self.assertEqual([destination / "document.txt"], files)

    def test_7z_recognition_and_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "sample.7z"
            destination = root / "out"
            destination.mkdir()
            archive.write_bytes(b"archive")
            output = destination / "document.txt"

            def extract(_cmd, **_kwargs):
                output.write_bytes(b"data")
                return type("Result", (), {"returncode": 0, "stderr": b""})()

            with patch("document_processor.archive_extractor.subprocess.run", side_effect=extract):
                self.assertTrue(self.extractor.is_archive(archive))
                files = self.extractor.extract_recursive(archive, destination)

            self.assertEqual([output], files)

    def test_recursion_depth_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "sample.7z"
            destination = root / "out"
            destination.mkdir()
            archive.write_bytes(b"archive")

            self.assertEqual([], self.extractor.extract_recursive(archive, destination, depth=4))


if __name__ == "__main__":
    unittest.main()
