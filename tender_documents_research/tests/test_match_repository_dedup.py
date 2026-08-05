"""
Regression tests for within-batch semantic deduplication in MatchRepository.save_matches.

Scope contract:
  One save_matches() call = one file (one tender_id + registry_type + file_name triple
  resolves to exactly one match_id via ON CONFLICT).
  seen_in_batch is local to one call, so cross-file collapsing cannot happen.

Dedup key (after fix):
  (keyword, COALESCE(matched_display_text, matched_cell_text, matched_line_text))

  matched_display_text is preferred because it is what the CRM shows to the user.
  Two evidence rows that display identically to the user are the same evidence,
  regardless of which physical page/row they come from in the source document.

  source_file is NOT in the key -- all rows in one call share the same source file.
  sheet_name/page is NOT in the key -- same keyword+display_text on different pages
  of the same smeta section is one piece of evidence, not N.

No production DB required -- DatabaseManager is mocked.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/opt/construction-opportunity-intelligence/tender_documents_research")

import unittest
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _schema_rows():
    """Simulate _detect_detail_schema() returning current column set."""
    return [
        ("match_id",), ("product_name",), ("matched_display_text",),
        ("matched_text",), ("score",), ("matched_keywords",),
        ("line_number",), ("source_file",), ("row_index",), ("sheet_name",),
    ]


def _side_effects_for_n_inserts(n: int, match_id: int = 42):
    """
    Build a side_effect list for n rows that all pass batch-dedup
    (each with a unique key) and produce one INSERT each.
    Schema + header + DELETE + n*(dedup_select_empty + INSERT).
    """
    return [_schema_rows(), [(match_id,)], None] + [[], None] * n


def _count_inserts(call_args_list) -> int:
    return sum(
        1
        for c in call_args_list
        if c.args and isinstance(c.args[1], str)
        and "INSERT INTO tender_document_match_details" in c.args[1]
    )


def _make_repo_and_db():
    from document_processor.match_repository import MatchRepository
    db = MagicMock()
    return MatchRepository(db), db


def _match(keyword: str, display_text: str = "", cell_text: str = "",
           line_text: str = "", line_number: int = 100,
           score: int = 85, sheet_name: str = "page_1_table_1") -> dict:
    """Build a minimal match dict."""
    return {
        "keyword": keyword,
        "score": score,
        "line_number": line_number,
        "matched_display_text": display_text,
        "matched_cell_text": cell_text or display_text,
        "matched_line": line_text or display_text,
        "sheet_name": sheet_name,
    }


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestBatchDedupCollapses(unittest.TestCase):
    """Scenarios where within-batch dedup should collapse rows -> fewer INSERTs."""

    def test_same_keyword_same_display_text_different_line_numbers_collapses(self):
        """
        Core regression: same (keyword, display_text) at 2253 different line_numbers
        -> 1 INSERT (the outlier smeta case from tender 121025, match 23859).
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(), [(42,)], None,  # schema, header, DELETE
            [], None,                         # dedup SELECT + INSERT for row 0
            # rows 1..2252 hit seen_in_batch before reaching DB
        ])

        display = "pokraska poverhnostej maslyanyh krasok"
        matches = [
            _match("arxitektu", display_text=display, line_number=7000 + i)
            for i in range(2253)
        ]
        repo.save_matches(tender_id=121025, registry_type="44fz",
                          file_name="smeta.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 1)

    def test_same_keyword_same_display_text_different_pages_collapses(self):
        """
        Same display_text from 560 different PDF pages/sheets -> 1 INSERT.
        Same keyword+context on different pages is ONE evidence for CRM.
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(), [(42,)], None,
            [], None,  # only the first row reaches DB
        ])

        display = "montazh truboprovodov"
        matches = [
            _match("truboprovod", display_text=display,
                   line_number=100 + i, sheet_name=f"page_{i}_table_1")
            for i in range(560)
        ]
        repo.save_matches(tender_id=999, registry_type="44fz",
                          file_name="big_smeta.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 1)

    def test_same_keyword_same_display_text_different_raw_text_collapses(self):
        """
        Same display_text but 109 slightly different raw matched_text values
        (OCR/formatting variants) -> 1 INSERT.
        dedup_text prefers matched_display_text over matched_cell_text.
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(), [(42,)], None,
            [], None,  # first row
        ])

        display = "ochistka poverhnostej ot zagryaznenij"
        matches = [
            _match("arxitektu", display_text=display,
                   cell_text=f"ochistka poverhnostej (variant {i})",  # 109 raw variants
                   line_number=1000 + i)
            for i in range(109)
        ]
        repo.save_matches(tender_id=121025, registry_type="44fz",
                          file_name="smeta.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 1)

    def test_same_physical_position_repeated_collapses(self):
        """
        Exact same (keyword, line_number, display_text) repeated in batch -> 1 INSERT.
        Guards against generator bugs that emit duplicate match dicts.
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(), [(42,)], None,
            [], None,  # first row only
        ])

        m = _match("kanal", display_text="kanalizacionnye truby", line_number=500)
        repo.save_matches(tender_id=1, registry_type="44fz",
                          file_name="doc.pdf", matches=[m, m, m])

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 1)


class TestBatchDedupPreserves(unittest.TestCase):
    """Scenarios where dedup must NOT collapse -> distinct INSERTs."""

    def test_different_keywords_same_display_text_each_preserved(self):
        """
        Different keywords, same display_text -> one INSERT per keyword.
        (keyword, text) key includes the keyword, so they are distinct.
        """
        repo, db = _make_repo_and_db()
        keywords = ["truboprovod", "kanalizac", "drenazh"]
        db.execute_query.side_effect = iter(
            _side_effects_for_n_inserts(len(keywords))
        )

        display = "montazh sistem vnutrennih kommunikacij"
        matches = [
            _match(kw, display_text=display, line_number=200 + i)
            for i, kw in enumerate(keywords)
        ]
        repo.save_matches(tender_id=2, registry_type="44fz",
                          file_name="spec.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), len(keywords))

    def test_same_keyword_different_display_texts_each_preserved(self):
        """
        Same keyword, different содержательные строки (display_text) -> each preserved.
        Different display_text = different evidence context for CRM.
        """
        repo, db = _make_repo_and_db()
        display_texts = [
            "ukladka truby v transhee",
            "montazh truboprovoda na oporax",
            "ispytanie truboprovoda gidravlicheskoe",
        ]
        db.execute_query.side_effect = iter(
            _side_effects_for_n_inserts(len(display_texts))
        )

        matches = [
            _match("truboprovod", display_text=dt, line_number=300 + i)
            for i, dt in enumerate(display_texts)
        ]
        repo.save_matches(tender_id=3, registry_type="44fz",
                          file_name="tender.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), len(display_texts))

    def test_different_pages_different_display_text_each_preserved(self):
        """
        Keyword on page 1 has display_text A, on page 50 has display_text B
        -> two separate evidence items preserved (different section context).
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter(
            _side_effects_for_n_inserts(2)
        )

        matches = [
            _match("drenazh", display_text="poverhnostnyj drenazh",
                   line_number=100, sheet_name="page_1_table_1"),
            _match("drenazh", display_text="glubokie drenazhnye sistemы",
                   line_number=5000, sheet_name="page_50_table_1"),
        ]
        repo.save_matches(tender_id=4, registry_type="44fz",
                          file_name="project.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 2)

    def test_two_files_same_keyword_text_each_gets_own_insert(self):
        """
        Two calls to save_matches with different file_name, same keyword+text
        -> each call produces 1 INSERT (seen_in_batch is fresh per call).
        source_file is NOT in the batch dedup key, but each call is independent.
        """
        repo1, db1 = _make_repo_and_db()
        repo2, db2 = _make_repo_and_db()

        display = "armatura stroitelnaya"
        m = _match("armat", display_text=display, line_number=100)

        db1.execute_query.side_effect = iter([
            _schema_rows(), [(11,)], None, [], None,
        ])
        db2.execute_query.side_effect = iter([
            _schema_rows(), [(12,)], None, [], None,
        ])

        repo1.save_matches(tender_id=5, registry_type="44fz",
                           file_name="file_A.pdf", matches=[m])
        repo2.save_matches(tender_id=5, registry_type="44fz",
                           file_name="file_B.pdf", matches=[m])

        inserts_a = _count_inserts(db1.execute_query.call_args_list)
        inserts_b = _count_inserts(db2.execute_query.call_args_list)
        self.assertEqual(inserts_a, 1, "file A should produce 1 INSERT")
        self.assertEqual(inserts_b, 1, "file B should produce its own INSERT")


class TestBatchDedupEdgeCases(unittest.TestCase):

    def test_empty_matches_no_inserts(self):
        """Empty batch -> save_matches returns early, 0 INSERTs."""
        repo, db = _make_repo_and_db()
        # save_matches has an early return `if not matches: return`
        db.execute_query.side_effect = iter([_schema_rows()])

        repo.save_matches(tender_id=1, registry_type="44fz",
                          file_name="empty.pdf", matches=[])

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 0)

    def test_display_text_takes_priority_over_cell_text_in_dedup_key(self):
        """
        When matched_display_text is set, it governs dedup, not matched_cell_text.
        Two rows: same display_text, different cell_text -> collapse to 1 INSERT.
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(), [(42,)], None,
            [], None,  # first row only
        ])

        matches = [
            _match("krovlya", display_text="montazh krovel",
                   cell_text="montazh krovel (variant 1)", line_number=10),
            _match("krovlya", display_text="montazh krovel",
                   cell_text="montazh krovel (variant 2)", line_number=11),
        ]
        repo.save_matches(tender_id=7, registry_type="44fz",
                          file_name="roof.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 1)

    def test_no_display_text_falls_back_to_cell_text(self):
        """
        When matched_display_text is absent, dedup falls back to matched_cell_text.
        Two rows with same cell_text -> collapse to 1 INSERT.
        """
        repo, db = _make_repo_and_db()
        db.execute_query.side_effect = iter([
            _schema_rows(), [(42,)], None,
            [], None,
        ])

        matches = [
            {
                "keyword": "beton",
                "score": 90,
                "line_number": 20,
                "matched_display_text": "",   # absent
                "matched_cell_text": "beton klassa B25",
                "matched_line": "beton klassa B25",
                "sheet_name": "page_1_table_1",
            },
            {
                "keyword": "beton",
                "score": 90,
                "line_number": 30,
                "matched_display_text": "",   # absent
                "matched_cell_text": "beton klassa B25",
                "matched_line": "beton klassa B25",
                "sheet_name": "page_2_table_1",
            },
        ]
        repo.save_matches(tender_id=8, registry_type="44fz",
                          file_name="concrete.pdf", matches=matches)

        self.assertEqual(_count_inserts(db.execute_query.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
