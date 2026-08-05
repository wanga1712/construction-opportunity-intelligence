"""
Regression test for within-batch semantic deduplication in MatchRepository.save_matches.

Verifies that rows with the same (keyword, display_text) produced by a large smeta
are collapsed to a single evidence record per unique (keyword, text) pair.
No production DB required -- DatabaseManager is mocked.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/opt/construction-opportunity-intelligence/tender_documents_research")

import unittest
from unittest.mock import MagicMock


def _schema_rows():
    return [
        ("match_id",), ("product_name",), ("matched_display_text",),
        ("matched_text",), ("score",), ("matched_keywords",),
        ("line_number",), ("source_file",), ("row_index",),
    ]


class TestSaveMatchesBatchDedup(unittest.TestCase):

    def _make_repo_and_db(self):
        from document_processor.match_repository import MatchRepository
        db = MagicMock()
        return MatchRepository(db), db

    @staticmethod
    def _count_inserts(call_args_list):
        return sum(
            1
            for c in call_args_list
            if c.args and isinstance(c.args[1], str)
            and "INSERT INTO tender_document_match_details" in c.args[1]
        )

    def test_duplicate_keyword_text_collapsed_to_one_insert(self):
        """Same keyword + same display_text at 2253 different line_numbers -> 1 INSERT."""
        repo, db = self._make_repo_and_db()

        db.execute_query.side_effect = iter([
            _schema_rows(),   # _detect_detail_schema
            [(42,)],          # header UPSERT RETURNING id
            None,             # DELETE details
            [],               # dedup SELECT for 1st row -> not found
            None,             # INSERT for 1st row
            # rows 2..2253 are blocked by seen_in_batch before reaching DB
        ])

        repeated_text = "pokraska poverhnostej metallicheskih konstrukcij"
        matches = [
            {
                "keyword": "arhitekturn",
                "score": 85,
                "line_number": 7000 + i,
                "matched_line": repeated_text,
                "matched_cell_text": repeated_text,
            }
            for i in range(2253)
        ]

        repo.save_matches(
            tender_id=121025,
            registry_type="44fz",
            file_name="smeta.pdf",
            matches=matches,
        )

        n_inserts = self._count_inserts(db.execute_query.call_args_list)
        self.assertEqual(
            n_inserts,
            1,
            f"Expected 1 INSERT for 2253 semantically identical rows, got {n_inserts}",
        )

    def test_distinct_texts_each_produce_one_insert(self):
        """Different display_texts for same keyword -> one INSERT each."""
        repo, db = self._make_repo_and_db()

        n_distinct = 5
        side_effects = (
            [_schema_rows(), [(42,)], None]
            + [[], None] * n_distinct
        )
        db.execute_query.side_effect = iter(side_effects)

        matches = [
            {
                "keyword": "truboprovod",
                "score": 90,
                "line_number": 100 + i,
                "matched_line": f"tekst stroki {i}",
                "matched_cell_text": f"tekst stroki {i}",
            }
            for i in range(n_distinct)
        ]

        repo.save_matches(
            tender_id=999,
            registry_type="44fz",
            file_name="spec.xlsx",
            matches=matches,
        )

        n_inserts = self._count_inserts(db.execute_query.call_args_list)
        self.assertEqual(n_inserts, n_distinct)

    def test_distinct_keywords_same_text_produce_distinct_inserts(self):
        """Different keywords, same display_text -> one INSERT per keyword."""
        repo, db = self._make_repo_and_db()

        keywords = ["truboprovod", "kanalizac", "drenazh"]
        side_effects = (
            [_schema_rows(), [(42,)], None]
            + [[], None] * len(keywords)
        )
        db.execute_query.side_effect = iter(side_effects)

        shared_text = "montazh truboprovoda kanalizacii"
        matches = [
            {
                "keyword": kw,
                "score": 88,
                "line_number": 200 + i,
                "matched_line": shared_text,
                "matched_cell_text": shared_text,
            }
            for i, kw in enumerate(keywords)
        ]

        repo.save_matches(
            tender_id=555,
            registry_type="44fz",
            file_name="doc.pdf",
            matches=matches,
        )

        n_inserts = self._count_inserts(db.execute_query.call_args_list)
        self.assertEqual(n_inserts, len(keywords))

    def test_empty_matches_returns_early_no_inserts(self):
        """Empty matches list -> save_matches returns before any DB inserts."""
        repo, db = self._make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(),
            [(42,)],
            None,  # DELETE
        ])

        repo.save_matches(
            tender_id=1,
            registry_type="44fz",
            file_name="empty.pdf",
            matches=[],
        )

        n_inserts = self._count_inserts(db.execute_query.call_args_list)
        self.assertEqual(n_inserts, 0)


if __name__ == "__main__":
    unittest.main()
