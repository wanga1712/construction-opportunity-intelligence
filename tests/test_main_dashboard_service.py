"""Tests for the main dashboard (control room) pure logic and category assembly.

No DB access: only deterministic helpers and the in-memory row assembly.
"""
from __future__ import annotations

import unittest

from src.services.main_dashboard_service import (
    ERROR_LABELS,
    ControlRoom,
    _best_category,
    _build_categories,
    classify_doc_error,
    deadline_bucket,
    format_age,
    freshness_status,
)
from src.services.main_dashboard_types import MEDALS


class FreshnessStatusTests(unittest.TestCase):
    def test_unknown_when_no_stamp(self):
        self.assertEqual(freshness_status(None), "UNKNOWN")

    def test_green_boundary(self):
        self.assertEqual(freshness_status(0), "GREEN")
        self.assertEqual(freshness_status(300), "GREEN")

    def test_yellow_boundary(self):
        self.assertEqual(freshness_status(300.5), "YELLOW")
        self.assertEqual(freshness_status(1800), "YELLOW")

    def test_red_beyond_30_minutes(self):
        self.assertEqual(freshness_status(1800.5), "RED")
        self.assertEqual(freshness_status(86400), "RED")

    def test_negative_clock_skew_is_fresh(self):
        self.assertEqual(freshness_status(-120), "GREEN")


class FormatAgeTests(unittest.TestCase):
    def test_none_renders_dash_not_zero(self):
        self.assertEqual(format_age(None), "\u2014")

    def test_seconds_minutes_hours_days(self):
        self.assertEqual(format_age(5), "5 \u0441\u0435\u043a \u043d\u0430\u0437\u0430\u0434")
        self.assertEqual(format_age(59), "59 \u0441\u0435\u043a \u043d\u0430\u0437\u0430\u0434")
        self.assertEqual(format_age(60), "1 \u043c\u0438\u043d \u043d\u0430\u0437\u0430\u0434")
        self.assertEqual(format_age(3599), "59 \u043c\u0438\u043d \u043d\u0430\u0437\u0430\u0434")
        self.assertEqual(format_age(3600), "1 \u0447 \u043d\u0430\u0437\u0430\u0434")
        self.assertEqual(format_age(86399), "23 \u0447 \u043d\u0430\u0437\u0430\u0434")
        self.assertEqual(format_age(86400), "1 \u0434\u043d \u043d\u0430\u0437\u0430\u0434")


class DeadlineBucketTests(unittest.TestCase):
    def test_buckets_match_decay_schedule(self):
        self.assertEqual(deadline_bucket(None), "unknown")
        self.assertEqual(deadline_bucket(30), "gt14")
        self.assertEqual(deadline_bucket(15), "gt14")
        self.assertEqual(deadline_bucket(14), "8-14")
        self.assertEqual(deadline_bucket(8), "8-14")
        self.assertEqual(deadline_bucket(7), "4-7")
        self.assertEqual(deadline_bucket(4), "4-7")
        self.assertEqual(deadline_bucket(3), "2-3")
        self.assertEqual(deadline_bucket(2), "2-3")


class ClassifyDocErrorTests(unittest.TestCase):
    def test_no_links_is_never_produced(self):
        self.assertNotIn("NO_LINKS", ERROR_LABELS)
        samples = [
            (None, None),
            ("some unknown failure", "FAILED"),
            ("uq_canonical_source_file_gen", "FAILED"),
            ("HTTP 403 Forbidden", None),
            ("filename too long: 300 chars", None),
            ("Unsupported format .sign", None),
            ("broken pdf: cannot open", None),
            ("archive extraction failed: zip", None),
            ("skip-list: template", None),
            ("download error: timeout", None),
        ]
        for message, status in samples:
            self.assertNotEqual(classify_doc_error(message, status), "NO_LINKS")

    def test_duplicate_collision(self):
        self.assertEqual(
            classify_doc_error("duplicate key value violates unique constraint", "FAILED"),
            "DUPLICATE_COLLISION",
        )
        self.assertEqual(classify_doc_error("uq_canonical_source_file_gen", None),
                         "DUPLICATE_COLLISION")

    def test_forbidden_and_filename(self):
        self.assertEqual(classify_doc_error("403 Forbidden", None), "FORBIDDEN_403")
        self.assertEqual(classify_doc_error("filename too long", None), "FILENAME_TOO_LONG")

    def test_unsupported_and_archive(self):
        self.assertEqual(classify_doc_error("Unsupported format .xls", None), "UNSUPPORTED")
        self.assertEqual(classify_doc_error("archive extraction failed", None), "BROKEN_ARCHIVE")

    def test_pdf_needs_both_markers(self):
        self.assertEqual(classify_doc_error("broken pdf, cannot open", None), "MALFORMED_PDF")
        self.assertEqual(classify_doc_error("file.pdf ok", None), "OTHER")

    def test_download_error_and_generic_failed(self):
        self.assertEqual(classify_doc_error("download error", None), "DOWNLOAD_ERROR")
        self.assertEqual(classify_doc_error(None, "FAILED"), "DOWNLOAD_ERROR")
        self.assertEqual(classify_doc_error("plain message", "COMPLETED"), "OTHER")

    def test_every_class_has_a_label(self):
        for message, status in [
            (None, None), ("403", None), ("filename too long", None),
            ("Unsupported format", None), ("archive extraction failed", None),
            ("broken pdf cannot open", None), ("skip", None),
            ("download error", None), ("duplicate key", None),
        ]:
            self.assertIn(classify_doc_error(message, status), ERROR_LABELS)


class CategoryAssemblyTests(unittest.TestCase):
    REGISTRY = [("lighting", "\u0421\u0432\u0435\u0442\u043e\u0442\u0435\u0445\u043d\u0438\u043a\u0430"),
                ("flooring", "\u041d\u0430\u043f\u043e\u043b\u044c\u043d\u044b\u0435 \u043f\u043e\u043a\u0440\u044b\u0442\u0438\u044f")]

    def test_rows_come_only_from_registry(self):
        rows = _build_categories(self.REGISTRY, [], {})
        self.assertEqual([r.code for r in rows], ["lighting", "flooring"])
        self.assertTrue(all(r.active == 0 for r in rows))

    def test_noncanonical_and_nonmedal_are_ignored(self):
        medal_rows = [
            (1, "lighting", "GOLD", "SECOND_PASS"),
            (2, "lighting", "SILVER", "FIRST_PASS"),
            (3, "other_unmapped", "GOLD", "SECOND_PASS"),
            (4, "3d printing", "SILVER", "FIRST_PASS"),
            (5, "lighting", "", "SECOND_PASS"),
            (6, "lighting", "UNASSESSED", "FIRST_PASS"),
        ]
        rows = {r.code: r for r in _build_categories(self.REGISTRY, medal_rows, {})}
        self.assertEqual(rows["lighting"].active, 2)
        self.assertEqual(rows["lighting"].gold, 1)
        self.assertEqual(rows["lighting"].silver, 1)
        self.assertNotIn("other_unmapped", rows)
        self.assertNotIn("3d printing", rows)
        self.assertEqual(rows["flooring"].active, 0)

    def test_docs_split_into_with_and_waiting(self):
        medal_rows = [
            (1, "lighting", "GOLD", "SECOND_PASS"),
            (2, "lighting", "SILVER", "FIRST_PASS"),
        ]
        doc_files = {1: (3, 3, 0), 2: (0, 0, 0)}
        rows = {r.code: r for r in _build_categories(self.REGISTRY, medal_rows, doc_files)}
        self.assertEqual(rows["lighting"].with_docs, 1)
        self.assertEqual(rows["lighting"].waiting_docs, 1)

    def test_second_pass_column_tracks_only_second_pass_source(self):
        medal_rows = [
            (1, "lighting", "GOLD", "SECOND_PASS"),
            (2, "lighting", "SILVER", "FIRST_PASS"),
            (3, "flooring", "BRONZE", "SECOND_PASS"),
        ]
        rows = {r.code: r for r in _build_categories(self.REGISTRY, medal_rows, {})}
        self.assertEqual(rows["lighting"].active, 2)
        self.assertEqual(rows["lighting"].second_pass, 1)
        self.assertEqual(rows["flooring"].second_pass, 1)

    def test_counts_are_distinct_per_procurement(self):
        medal_rows = [
            (1, "lighting", "GOLD", "SECOND_PASS"),
            (1, "lighting", "GOLD", "SECOND_PASS"),
        ]
        rows = {r.code: r for r in _build_categories(self.REGISTRY, medal_rows, {})}
        self.assertEqual(rows["lighting"].active, 1)
        self.assertEqual(rows["lighting"].gold, 1)

    def test_duplicate_pair_with_two_medals_counts_once(self):
        medal_rows = [
            (1, "lighting", "SILVER", "SECOND_PASS"),
            (1, "lighting", "GOLD", "FIRST_PASS"),
        ]
        rows = {r.code: r for r in _build_categories(self.REGISTRY, medal_rows, {})}
        self.assertEqual(rows["lighting"].active, 1)
        self.assertEqual(rows["lighting"].gold + rows["lighting"].silver, 1)

    def test_two_categories_for_one_procurement_count_in_each_row(self):
        medal_rows = [
            (1, "lighting", "GOLD", "SECOND_PASS"),
            (1, "flooring", "SILVER", "SECOND_PASS"),
        ]
        rows = {r.code: r for r in _build_categories(self.REGISTRY, medal_rows, {})}
        self.assertEqual(rows["lighting"].active, 1)
        self.assertEqual(rows["flooring"].active, 1)

    def test_best_category_prefers_strongest_medal(self):
        rows = [
            (1, "lighting", "WOOD", "FIRST_PASS"),
            (1, "flooring", "GOLD", "SECOND_PASS"),
            (2, "lighting", "BRONZE", "SECOND_PASS"),
        ]
        best = _best_category(rows)
        self.assertEqual(best[1], ("flooring", "GOLD"))
        self.assertEqual(best[2], ("lighting", "BRONZE"))

    def test_best_category_skips_unassessed(self):
        self.assertEqual(_best_category([(1, "lighting", "UNASSESSED", "SECOND_PASS")]), {})

    def test_medal_set_is_the_only_source_of_columns(self):
        self.assertEqual(MEDALS, ("GOLD", "SILVER", "BRONZE", "WOOD"))


class ControlRoomTests(unittest.TestCase):
    def test_authority_sum_matches_active_count(self):
        room = ControlRoom(active_total=311)
        room.authority = {"PRELIMINARY": 113, "SECOND_PASS_MODEL": 18, "UNASSESSED": 180}
        self.assertEqual(room.authority_sum, 311)
        self.assertEqual(room.authority_sum, room.active_total)

    def test_missing_values_stay_none_not_zero(self):
        room = ControlRoom()
        self.assertIsNone(room.active_total)
        self.assertIsNone(room.second_pass)
        self.assertIsNone(room.doc_errors_total)


if __name__ == "__main__":
    unittest.main()