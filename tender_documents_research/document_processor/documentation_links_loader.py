"""Explicit source-native procurement identity and document-link resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .registry_tables import qualified

LinkRow = Tuple[str, Optional[str], Optional[int], Optional[str]]


class SourceLinkIdentityError(RuntimeError):
    """The source family or identity is not supported."""


class SourceLinkMappingError(RuntimeError):
    """The configured source schema cannot execute its declared lookup."""


@dataclass(frozen=True)
class SourceProcurementIdentity:
    source_table: str
    source_id: Optional[int]
    registry_number: str
    source_type: str


class SourceLinksRepository:
    """Resolve links using the native registry number declared by each source."""

    LINK_TABLES = {
        "44": "links_documentation_44_fz",
        "223": "links_documentation_223_fz",
    }
    SOURCE_TYPES_BY_LINK_TABLE = {
        table: source_type for source_type, table in LINK_TABLES.items()
    }

    def __init__(self, db, db_alias: str):
        self.db = db
        self.db_alias = db_alias

    def resolve_links(self, identity: SourceProcurementIdentity) -> List[LinkRow]:
        source_type = str(identity.source_type or "").strip()
        table = self.LINK_TABLES.get(source_type)
        number = str(identity.registry_number or "").strip()
        expected_marker = f"_{source_type}_fz"
        if table is None or not number or expected_marker not in identity.source_table:
            raise SourceLinkIdentityError(
                "SOURCE_LINK_IDENTITY_UNSUPPORTED: "
                f"type={source_type!r} table={identity.source_table!r}"
            )

        sql = (
            f"SELECT id, document_links, file_name FROM {qualified(table)} "
            "WHERE contract_number = %s ORDER BY id"
        )
        try:
            rows = self.db.execute_query(
                self.db_alias, sql, (number,), fetch=True
            ) or []
        except Exception as exc:
            raise SourceLinkMappingError(
                f"SOURCE_LINK_MAPPING_ERROR: {table}.contract_number lookup failed"
            ) from exc

        import hashlib
        parsed: List[LinkRow] = []
        for row_id, value, file_name in rows:
            expanded = self._expand_link_value(value, file_name)
            for url, fname in expanded:
                norm_url = self.normalize_url(url)
                phys_key = hashlib.sha256(norm_url.encode('utf-8')).hexdigest()
                parsed.append((url, fname, row_id, phys_key))
        return self.dedupe_links(parsed)

    def load_for_contract(
        self,
        links_table: str,
        contract_number: str,
        _legacy_reestr_ids,
    ) -> List[LinkRow]:
        """Compatibility API; reestr row IDs are deliberately not link keys."""
        source_type = self.SOURCE_TYPES_BY_LINK_TABLE.get(links_table)
        if source_type is None:
            raise SourceLinkIdentityError(
                "SOURCE_LINK_IDENTITY_UNSUPPORTED: "
                f"links_table={links_table!r}"
            )
        return self.resolve_links(
            SourceProcurementIdentity(
                source_table=f"reestr_contract_{source_type}_fz",
                source_id=None,
                registry_number=contract_number,
                source_type=source_type,
            )
        )

    @staticmethod
    def _expand_link_value(value, file_name: Optional[str]) -> List[Tuple[str, Optional[str]]]:
        result: List[Tuple[str, Optional[str]]] = []
        values = value if isinstance(value, list) else str(value or "").split()
        for item in values:
            if isinstance(item, str) and item.strip():
                result.append((item.strip(), file_name))
        return result

    @staticmethod
    def normalize_url(url: str) -> str:
        text = (url or "").strip()
        if not text:
            return ""
        try:
            parsed = urlparse(text)
            if not parsed.scheme and not parsed.netloc:
                return text.lower()
            query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
            path = parsed.path.rstrip("/") or "/"
            return urlunparse(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    path,
                    parsed.params,
                    query,
                    "",
                )
            )
        except Exception:
            return text.lower()

    @staticmethod
    def normalize_file_name(file_name: Optional[str]) -> str:
        return (file_name or "").strip().lower()

    @classmethod
    def dedupe_links(cls, links: Iterable[LinkRow]) -> List[LinkRow]:
        seen: set[Tuple[str, str]] = set()
        result: List[LinkRow] = []
        for url, file_name, row_id, phys_key in links:
            key = (cls.normalize_url(url), cls.normalize_file_name(file_name))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            result.append((url, file_name, row_id, phys_key))
        return result


# Compatibility name for callers; behavior is the explicit repository above.
DocumentationLinksLoader = SourceLinksRepository
