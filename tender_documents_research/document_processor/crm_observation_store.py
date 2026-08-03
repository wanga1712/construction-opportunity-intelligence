"""?????????? ??????????? ?????????? ?? ?????????? ? CRM ??.

???? ???? ?? ?????? ?????????? ?????????????. ?? ?????? ??????????? ??????????????
? ????????????? ??????? ??? ??????????? ????????? effective_priority.
"""
from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)
load_dotenv("/opt/CRM_Streamlit/.env", override=False)


class CrmObservationStore:
    """????? ?????????????? ?????????? ?? ????????? ?????????? ? CRM ??."""

    def __init__(self) -> None:
        self._dsn = {
            "host": os.getenv("CRM_DB_HOST"),
            "dbname": os.getenv("CRM_DB_DATABASE"),
            "user": os.getenv("CRM_DB_USER"),
            "password": os.getenv("CRM_DB_PASSWORD"),
            "port": os.getenv("CRM_DB_PORT"),
        }

    def record_matches(
        self,
        *,
        tender_id: int,
        registry_type: str,
        match_id: int,
        file_name: str,
        matches: list[dict[str, Any]],
    ) -> None:
        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {
                "category_name": None,
                "subcategory_name": None,
                "scores": [],
                "keywords": [],
                "lines": [],
                "technical_attributes": [],
            }
        )
        for match in matches:
            taxonomy = match.get("taxonomy") or {}
            category_code = str(taxonomy.get("category_code") or "").strip()
            subcategory_code = str(taxonomy.get("subcategory_code") or "").strip()
            if not category_code:
                continue
            bucket = grouped[(category_code, subcategory_code)]
            bucket["category_name"] = taxonomy.get("category_name")
            bucket["subcategory_name"] = taxonomy.get("subcategory_name")
            bucket["scores"].append(int(match.get("score") or 0))
            keyword = str(match.get("keyword") or "").strip()
            if keyword and keyword not in bucket["keywords"]:
                bucket["keywords"].append(keyword)
            matched_line = str(match.get("matched_line") or "").strip()
            if matched_line and matched_line not in bucket["lines"]:
                bucket["lines"].append(matched_line[:500])
            taxonomy_params = taxonomy.get("technical_parameters") or []
            for item in taxonomy_params:
                value = str(item or "").strip()
                if value and value not in bucket["technical_attributes"]:
                    bucket["technical_attributes"].append(value)

        if not grouped:
            return

        conn = psycopg2.connect(**self._dsn)
        try:
            with conn.cursor() as cur:
                for (category_code, subcategory_code), payload in grouped.items():
                    cur.execute(
                        """
                        INSERT INTO category_object_observations (
                            category_code,
                            subcategory_code,
                            tender_id,
                            registry_type,
                            document_id,
                            match_strength,
                            evidence_count,
                            technical_attributes_found,
                            ai_confidence,
                            manager_status,
                            observation_payload,
                            created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, NOW())
                        """,
                        (
                            category_code,
                            subcategory_code or None,
                            tender_id,
                            registry_type,
                            match_id,
                            max(payload["scores"]) if payload["scores"] else 0,
                            len(payload["keywords"]),
                            Json(payload["technical_attributes"]),
                            None,
                            "unreviewed",
                            Json(
                                {
                                    "file_name": file_name,
                                    "category_name": payload["category_name"],
                                    "subcategory_name": payload["subcategory_name"],
                                    "keywords": payload["keywords"],
                                    "lines": payload["lines"][:10],
                                }
                            ),
                        ),
                    )
            conn.commit()
        finally:
            conn.close()
