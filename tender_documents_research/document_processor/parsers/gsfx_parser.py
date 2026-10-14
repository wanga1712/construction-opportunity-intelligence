import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger_config import get_logger


class GsfxParser:
    """Parser for .gsfx files (SmetaWIZARD / GrandSmeta cost estimation archives).

    .gsfx is a ZIP archive containing ``Data.xml`` (+ ``Properties.xml``).
    GrandSmeta keeps every value in XML **attributes** (``Caption``, ``Units``,
    ``Quantity``, ``PriceCurr/@Value``), so reading only element text yields
    nothing — verified on production files (0 fragments before this rewrite).

    Output is a pipe-delimited table with a header that the embedded extractor
    recognises (:data:`_COL_MARKERS` in ``embedded_extraction``): materials
    (``Mat``) become supply lines, works (``Position``/``Work``) are emitted as
    plain context lines so they do not turn into category facts.
    """

    TABLE_HEADER = "№ | Наименование | Единица измерения | Кол-во | Цена | Сумма | Код"
    _MATERIAL_TAGS = ("Mat",)
    _SKIP_CONTEXT_TAGS = ("Work", "Mch", "Tzr", "Tzm2022")

    def __init__(self):
        self.logger = get_logger()

    def parse(self, path: Path) -> str:
        self.logger.info(f"GsfxParser: parsing {path.name}...")
        try:
            if not zipfile.is_zipfile(path):
                self.logger.warning(f"GsfxParser: {path.name} is not a valid zip file")
                return ""
            parts: List[str] = []
            with zipfile.ZipFile(path) as z:
                roots = []
                for name in z.namelist():
                    if not name.lower().endswith(".xml"):
                        continue
                    try:
                        roots.append(ET.fromstring(z.read(name)))
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning(
                            f"GsfxParser: failed to parse {name} in {path.name}: {exc}"
                        )
                for root in roots:
                    parts.extend(self._render(root))
            text = "\n".join(p for p in parts if p)
            self.logger.info(
                f"GsfxParser: finished {path.name}, {len(parts)} fragments"
            )
            return text
        except Exception as exc:  # noqa: BLE001
            self.logger.error(f"GsfxParser error processing {path.name}: {exc}")
            return ""

    def _render(self, root: ET.Element) -> List[str]:
        out: List[str] = []
        props = root.find("Properties")
        parent_map = {child: parent for parent in root.iter() for child in parent}

        if props is not None:
            for label, key in (("Объект", "Object"), ("Смета", "Constr"),
                               ("ЛС", "LocNum"), ("Описание", "Description")):
                value = str(props.attrib.get(key) or "").strip()
                if value:
                    out.append(f"{label}: {value}")

        rows: List[str] = []
        context: List[str] = []
        seq = 0
        for elem in root.iter():
            if elem.tag == "Position":
                caption = str(elem.attrib.get("Caption") or "").strip()
                if caption:
                    context.append(f"позиция: {caption}")
                continue
            if elem.tag in self._SKIP_CONTEXT_TAGS:
                caption = str(elem.attrib.get("Caption") or "").strip()
                if caption:
                    context.append(f"{elem.tag.lower()}: {caption}")
                continue
            if elem.tag not in self._MATERIAL_TAGS:
                continue
            caption = str(elem.attrib.get("Caption") or "").strip()
            if not caption:
                continue
            unit = str(elem.attrib.get("Units") or "").strip()
            qty = self._num(elem.attrib.get("Quantity")) or self._child_result(elem)
            price = self._price(elem)
            if qty is None and price is None:
                continue
            total = qty * price if (qty is not None and price is not None) else None
            code = str(elem.attrib.get("Code") or "").strip()
            position = parent_map.get(elem)
            number = ""
            while position is not None:
                if position.tag == "Position":
                    number = str(position.attrib.get("Number") or "").strip()
                    break
                position = parent_map.get(position)
            seq += 1
            label = number or str(seq)
            rows.append(" | ".join([
                label, caption, unit,
                self._fmt(qty), self._fmt(price), self._fmt(total), code,
            ]))

        if rows:
            out.append(self.TABLE_HEADER)
            out.extend(rows)
        out.extend(context)
        return out

    @staticmethod
    def _child_result(elem: ET.Element) -> Optional[float]:
        child = elem.find("Quantity")
        if child is not None:
            return GsfxParser._num(child.attrib.get("Result"))
        return None

    @staticmethod
    def _price(elem: ET.Element) -> Optional[float]:
        for tag in ("PriceCurr", "PriceBase"):
            child = elem.find(tag)
            if child is not None:
                value = GsfxParser._num(child.attrib.get("Value"))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _num(raw: object) -> Optional[float]:
        if raw is None:
            return None
        text = str(raw).strip().replace("\xa0", "").replace(" ", "")
        if not text:
            return None
        if "," in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _fmt(value: Optional[float]) -> str:
        if value is None:
            return ""
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text or "0"
