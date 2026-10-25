#!/usr/bin/env python3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/opt/tender_documents_research")
sys.path.insert(0, "/opt/CRM_Streamlit/scripts")

from direct_supply_phase2 import inventory  # noqa: E402
from document_processor.archive_extractor import ArchiveExtractor  # noqa: E402
from document_processor.parse_utils import (  # noqa: E402
    get_rich_parser, parse_file_with_meta, supports_rich_meta,
)
from document_processor.parser_factory import ParserFactory  # noqa: E402
from document_processor.direct_runtime import direct_facts  # noqa: E402

import logging


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    items = [r for r in inventory(include_all=True)
             if r.get("classification") == "DEFERRED_ARCHIVE"]
    factory = ParserFactory()
    extractor = ArchiveExtractor(logging.getLogger("archive_audit"))
    for row in items[:3]:
        path = Path(str(row.get("local_path") or ""))
        if not path.is_file():
            print("MISSING", row["procurement_id"], path)
            continue
        print("ARCHIVE", row["procurement_id"], row["document_file_id"], path.name)
        with tempfile.TemporaryDirectory(prefix="archive_audit_") as tmp:
            members = extractor.extract_recursive(path, Path(tmp))
            for member in members[:6]:
                print("  MEMBER", member.suffix, member.name[:70])
                parser = (
                    get_rich_parser(factory, member)
                    if supports_rich_meta(member)
                    else factory.get_parser(member)
                )
                if parser is None:
                    print("    NO_PARSER")
                    continue
                try:
                    text, meta = parse_file_with_meta(parser, member)
                except Exception as exc:
                    print("    PARSE_ERR", type(exc).__name__, exc)
                    continue
                facts = direct_facts(
                    member,
                    procurement_id=row["procurement_id"],
                    category_code=row["category"],
                    document_name=member.name,
                    source_document_id=row.get("document_file_id"),
                    physical_key=None,
                    document_class=row["document_class"],
                )
                print("    TEXT_LEN", len(text), "META", len(meta or {}), "FACTS", len(facts))
                for line in (text or "").splitlines()[:5]:
                    print("    TXT", line[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
