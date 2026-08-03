import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from utils.logger_config import get_logger


class GsfxParser:
    """Parser for .gsfx files (SmetaWIZARD cost estimation archives).

    .gsfx is a ZIP archive containing:
    - Data.xml     — project cost estimation data
    - Properties.xml — document properties
    """

    def __init__(self):
        self.logger = get_logger()

    def parse(self, path: Path) -> str:
        self.logger.info(f"GsfxParser: parsing {path.name}...")
        try:
            if not zipfile.is_zipfile(path):
                self.logger.warning(f"GsfxParser: {path.name} is not a valid zip file")
                return ""

            parts = []
            with zipfile.ZipFile(path) as z:
                for xml_name in ("Data.xml", "Properties.xml"):
                    if xml_name not in z.namelist():
                        continue
                    try:
                        with z.open(xml_name) as f:
                            content = f.read()
                        root = ET.fromstring(content)
                        # Extract all text content from XML elements
                        for elem in root.iter():
                            if elem.text and elem.text.strip():
                                parts.append(elem.text.strip())
                            if elem.tail and elem.tail.strip():
                                parts.append(elem.tail.strip())
                    except Exception as e:
                        self.logger.warning(
                            f"GsfxParser: failed to parse {xml_name} in {path.name}: {e}"
                        )

                # Also try any other XML files inside the archive
                for name in z.namelist():
                    if name.lower().endswith(".xml") and name not in ("Data.xml", "Properties.xml"):
                        try:
                            with z.open(name) as f:
                                content = f.read()
                            root = ET.fromstring(content)
                            for elem in root.iter():
                                if elem.text and elem.text.strip():
                                    parts.append(elem.text.strip())
                        except Exception:
                            pass

            self.logger.info(
                f"GsfxParser: finished {path.name}, extracted {len(parts)} text fragments"
            )
            return "\n".join(parts)

        except Exception as e:
            self.logger.error(f"GsfxParser error processing {path.name}: {e}")
            return ""
