"""???????? ?????????? ????????? ? ????????? ???? ?? CRM ??.

?????? ?????? ????? ??????? 7-?? ??????? ????? CRM_DB_* ?? /opt/CRM_Streamlit/.env.
??????? ??????? JSON-???????? ??? ???????? ????????? ????? ???.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)
load_dotenv("/opt/CRM_Streamlit/.env", override=False)


@dataclass(frozen=True)
class TaxonomyTerm:
    phrase: str
    term_type: str
    weight: int
    category_code: str
    category_name: str
    subcategory_code: str
    subcategory_name: str


@dataclass
class TaxonomySubcategory:
    category_code: str
    category_name: str
    subcategory_code: str
    subcategory_name: str
    search_phrases: list[str] = field(default_factory=list)
    negative_phrases: list[str] = field(default_factory=list)
    brand_phrases: list[str] = field(default_factory=list)
    technical_parameters: list[str] = field(default_factory=list)


@dataclass
class TaxonomySnapshot:
    contour_code: str
    categories: dict[str, dict[str, Any]]
    terms: list[TaxonomyTerm]

    def phrases_by_term_type(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for term in self.terms:
            result.setdefault(term.term_type, []).append(term.phrase)
        return result


class CrmTaxonomyLoader:
    """?????? ????????? ? ??????? ???????? ?? CRM ??."""

    def __init__(self, *, contour_code: str = "procurement") -> None:
        self.contour_code = contour_code

    def load_snapshot(self) -> TaxonomySnapshot:
        rows = self._query(
            """
            SELECT
                c.category_code,
                c.category_name,
                s.subcategory_code,
                s.subcategory_name,
                s.technical_parameters,
                s.brand_phrases,
                t.term_type,
                t.phrase,
                COALESCE(t.weight, 100) AS weight
            FROM crm_product_categories c
            JOIN crm_product_subcategories s
              ON s.category_id = c.id
             AND s.is_active = TRUE
            LEFT JOIN crm_product_subcategory_terms t
              ON t.subcategory_id = s.id
             AND t.is_active = TRUE
            WHERE c.is_active = TRUE
              AND c.contour_code = %s
            ORDER BY c.sort_order, s.sort_order, c.category_name, s.subcategory_name, t.term_type, t.weight DESC, t.phrase
            """,
            (self.contour_code,),
        )
        categories: dict[str, dict[str, Any]] = {}
        terms: list[TaxonomyTerm] = []
        for row in rows:
            category_code = str(row["category_code"])
            category_name = str(row["category_name"])
            subcategory_code = str(row["subcategory_code"])
            subcategory_name = str(row["subcategory_name"])
            category = categories.setdefault(
                category_code,
                {
                    "category_code": category_code,
                    "category_name": category_name,
                    "subcategories": {},
                },
            )
            subcategory = category["subcategories"].setdefault(
                subcategory_code,
                TaxonomySubcategory(
                    category_code=category_code,
                    category_name=category_name,
                    subcategory_code=subcategory_code,
                    subcategory_name=subcategory_name,
                    technical_parameters=self._normalize_json_list(row.get("technical_parameters")),
                    brand_phrases=self._normalize_json_list(row.get("brand_phrases")),
                ),
            )
            phrase = (row.get("phrase") or "").strip()
            term_type = (row.get("term_type") or "").strip().lower()
            if not phrase or not term_type:
                continue
            normalized_phrase = phrase.lower()
            if term_type == "search" and normalized_phrase not in subcategory.search_phrases:
                subcategory.search_phrases.append(normalized_phrase)
            elif term_type == "negative" and normalized_phrase not in subcategory.negative_phrases:
                subcategory.negative_phrases.append(normalized_phrase)
            elif term_type == "brand" and normalized_phrase not in subcategory.brand_phrases:
                subcategory.brand_phrases.append(normalized_phrase)
            terms.append(
                TaxonomyTerm(
                    phrase=normalized_phrase,
                    term_type=term_type,
                    weight=int(row.get("weight") or 100),
                    category_code=category_code,
                    category_name=category_name,
                    subcategory_code=subcategory_code,
                    subcategory_name=subcategory_name,
                )
            )
        return TaxonomySnapshot(contour_code=self.contour_code, categories=categories, terms=terms)

    def load_keyword_index(self) -> dict[str, dict[str, Any]]:
        snapshot = self.load_snapshot()
        keyword_index: dict[str, dict[str, Any]] = {}
        for term in snapshot.terms:
            if term.term_type not in {"search", "brand"}:
                continue
            bucket = keyword_index.setdefault(
                term.phrase,
                {
                    "keyword": term.phrase,
                    "term_type": term.term_type,
                    "weight": term.weight,
                    "category_codes": [],
                    "category_names": [],
                    "subcategory_codes": [],
                    "subcategory_names": [],
                    "negative_phrases": [],
                },
            )
            if term.category_code not in bucket["category_codes"]:
                bucket["category_codes"].append(term.category_code)
            if term.category_name not in bucket["category_names"]:
                bucket["category_names"].append(term.category_name)
            if term.subcategory_code not in bucket["subcategory_codes"]:
                bucket["subcategory_codes"].append(term.subcategory_code)
            if term.subcategory_name not in bucket["subcategory_names"]:
                bucket["subcategory_names"].append(term.subcategory_name)
            bucket["term_type"] = "brand" if term.term_type == "brand" else bucket["term_type"]
            bucket["weight"] = max(int(bucket["weight"]), int(term.weight))

        for category in snapshot.categories.values():
            for subcategory in category["subcategories"].values():
                negatives = list(subcategory.negative_phrases)
                for phrase in subcategory.search_phrases + subcategory.brand_phrases:
                    bucket = keyword_index.get(phrase)
                    if not bucket:
                        continue
                    for negative in negatives:
                        if negative not in bucket["negative_phrases"]:
                            bucket["negative_phrases"].append(negative)
        return keyword_index

    def build_profiles(self) -> list[dict[str, Any]]:
        snapshot = self.load_snapshot()
        profiles: list[dict[str, Any]] = []
        for category_code, category in snapshot.categories.items():
            phrases: list[str] = []
            for subcategory in category["subcategories"].values():
                phrases.extend(subcategory.search_phrases[:8])
            dedup_phrases = list(dict.fromkeys([p for p in phrases if p]))[:40]
            profiles.append(
                {
                    "code": category_code,
                    "name": category["category_name"],
                    "product_groups": [category_code],
                    "object_segments": [],
                    "sources": ["44fz", "223fz"],
                    "title_include_any": dedup_phrases,
                    "title_exclude_any": [],
                    "object_keywords": dedup_phrases,
                    "ai_routing_hint": f"????????? {category['category_name']} ????????? ?? CRM ??.",
                    "document_search": True,
                    "comment": "db_taxonomy",
                }
            )
        return profiles

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        conn = psycopg2.connect(
            host=os.getenv("CRM_DB_HOST"),
            dbname=os.getenv("CRM_DB_DATABASE"),
            user=os.getenv("CRM_DB_USER"),
            password=os.getenv("CRM_DB_PASSWORD"),
            port=os.getenv("CRM_DB_PORT"),
            cursor_factory=RealDictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        finally:
            conn.close()

    @staticmethod
    def _normalize_json_list(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]
        result: list[str] = []
        for item in raw_items:
            text = str(item or "").strip().lower()
            if text and text not in result:
                result.append(text)
        return result


def load_keyword_index(*, contour_code: str = "procurement") -> dict[str, dict[str, Any]]:
    return CrmTaxonomyLoader(contour_code=contour_code).load_keyword_index()


def load_profiles(*, contour_code: str = "procurement") -> list[dict[str, Any]]:
    return CrmTaxonomyLoader(contour_code=contour_code).build_profiles()
