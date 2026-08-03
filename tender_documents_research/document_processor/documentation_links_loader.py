"""
Загрузка и дедупликация ссылок на документацию по contract_id.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .registry_tables import qualified


LinkRow = Tuple[str, Optional[str]]


class DocumentationLinksLoader:
    """Читает links_documentation_* и объединяет результаты по нескольким id."""

    def __init__(self, db, db_alias: str):
        self.db = db
        self.db_alias = db_alias
    def load_for_contract(
        self,
        links_table: str,
        contract_number: Optional[str],
        contract_ids: Sequence[int],
    ) -> List[LinkRow]:
        table_q = qualified(links_table)
        parsed: List[LinkRow] = []
        collected_rows = []

        if contract_number:
            try:
                sql_by_number = (
                    f"SELECT document_links, file_name FROM {table_q} "
                    f"WHERE contract_number = %s"
                )
                rows = self.db.execute_query(
                    self.db_alias, sql_by_number, (contract_number,), fetch=True
                ) or []
                collected_rows.extend(rows)
            except Exception:
                pass

        if contract_ids:
            unique_ids = sorted(set(contract_ids))
            placeholders = ", ".join(["%s"] * len(unique_ids))
            sql_by_ids = (
                f"SELECT document_links, file_name FROM {table_q} "
                f"WHERE contract_id IN ({placeholders})"
            )
            rows = self.db.execute_query(
                self.db_alias, sql_by_ids, tuple(unique_ids), fetch=True
            ) or []
            collected_rows.extend(rows)

        for row in collected_rows:
            value = row[0]
            file_name = row[1] if len(row) > 1 else None
            parsed.extend(self._expand_link_value(value, file_name))
        return self.dedupe_links(parsed)

    @staticmethod
    def _expand_link_value(
        value,
        file_name: Optional[str],
    ) -> List[LinkRow]:
        result: List[LinkRow] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    result.append((item.strip(), file_name))
        elif isinstance(value, str):
            for part in value.split():
                if part.strip():
                    result.append((part.strip(), file_name))
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
        for url, file_name in links:
            key = (
                cls.normalize_url(url),
                cls.normalize_file_name(file_name),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            result.append((url, file_name))
        return result
