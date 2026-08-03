import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from utils.logger_config import get_logger

class OdtParser:
    def __init__(self):
        self.logger = get_logger()
        # Namespaces used in ODT content.xml
        self.ns = {
            'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
            'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0'
        }

    def parse(self, path: Path) -> str:
        self.logger.info(f"OdtParser: parsing {path.name}...")
        try:
            if not zipfile.is_zipfile(path):
                self.logger.warning(f"OdtParser: {path.name} is not a valid zip file")
                return ""

            with zipfile.ZipFile(path) as z:
                if "content.xml" not in z.namelist():
                    self.logger.warning(f"OdtParser: content.xml not found in {path.name}")
                    return ""
                
                with z.open("content.xml") as f:
                    content = f.read()
                    
                root = ET.fromstring(content)
                parts = []
                
                # Extract text from paragraphs (text:p) and headings (text:h)
                # We iterate over all elements to preserve order if possible, 
                # but finding all .//text:p and .//text:h is easier and usually sufficient.
                
                # Find all text paragraphs and headings
                for elem in root.findall('.//*'):
                    tag = elem.tag
                    # Check if tag ends with 'p' or 'h' in text namespace
                    # ElementTree tags are usually '{uri}tag'
                    if tag == f"{{{self.ns['text']}}}p" or tag == f"{{{self.ns['text']}}}h":
                        text = "".join(elem.itertext())
                        if text and text.strip():
                            parts.append(text.strip())
                            
                self.logger.info(f"OdtParser: finished {path.name}, extracted {len(parts)} paragraphs")
                return "\n".join(parts)
                
        except Exception as e:
            self.logger.error(f"OdtParser error processing {path.name}: {e}")
            return ""
