import os
import sys
import unittest
from unittest import mock
import psycopg2.extras

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../tender_documents_research")))

from tender_documents_research.document_processor.context_validator import (
    ContextValidator,
    CONTEXT_VALIDATOR_MODEL_TIMEOUT_SECONDS,
    is_retryable_technical_result,
)
from tender_documents_research.document_processor.context_validator_service import (
    update_candidate_validations,
    process_batch,
    BatchResult,
    INITIAL_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    BACKOFF_FACTOR,
)


class MockCursor:
    def __init__(self, fetch_data=None):
        self.fetch_data = fetch_data or []
        self.executed = []

    def execute(self, query, vars=None):
        self.executed.append((query, vars))

    def fetchall(self):
        return self.fetch_data

    def fetchone(self):
        return self.fetch_data[0] if self.fetch_data else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    def __init__(self, fetch_data=None):
        self.cursor_obj = MockCursor(fetch_data)
        self.committed = False

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def commit(self):
        self.committed = True


class TestTransientFailureRepair(unittest.TestCase):
    def test_semantic_confirmed_terminal(self):
        candidate = {
            "detail_id": 101,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума гост",
            "context_after": "",
        }
        raw_json = '{"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "линолеума", "reason": "match"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "CONFIRMED")
        self.assertFalse(res["is_retryable"])
        self.assertFalse(is_retryable_technical_result(res))
        self.assertIsNotNone(res.get("validated_at"))

    def test_semantic_rejected_terminal(self):
        candidate = {
            "detail_id": 102,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "адрес: ул. Линолеума 5",
            "context_after": "",
        }
        raw_json = '{"decision": "REJECTED", "confidence": 0.90, "supporting_quote": "Линолеума 5", "reason": "address"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "REJECTED")
        self.assertFalse(res["is_retryable"])
        self.assertFalse(is_retryable_technical_result(res))

    def test_semantic_unknown_insufficient_context_terminal(self):
        candidate = {
            "detail_id": 103,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "текст",
            "context_after": "",
        }
        raw_json = '{"decision": "UNKNOWN", "confidence": 0.0, "reason_code": "INSUFFICIENT_CONTEXT", "reason": "ambiguous"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "INSUFFICIENT_CONTEXT")
        self.assertFalse(res["is_retryable"])
        self.assertFalse(is_retryable_technical_result(res))

    def test_missing_supporting_quote_terminal(self):
        candidate = {
            "detail_id": 104,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума",
            "context_after": "",
        }
        raw_json = '{"decision": "CONFIRMED", "confidence": 0.90, "supporting_quote": "", "reason": "no quote"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "MISSING_SUPPORTING_QUOTE")
        self.assertFalse(res["is_retryable"])

    def test_hallucinated_quote_terminal(self):
        candidate = {
            "detail_id": 105,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума",
            "context_after": "",
        }
        raw_json = '{"decision": "CONFIRMED", "confidence": 0.90, "supporting_quote": "вымышленная цитата", "reason": "fake"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "HALLUCINATED_QUOTE")
        self.assertFalse(res["is_retryable"])

    def test_low_confidence_terminal(self):
        candidate = {
            "detail_id": 106,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума",
            "context_after": "",
        }
        raw_json = '{"decision": "CONFIRMED", "confidence": 0.50, "supporting_quote": "линолеума", "reason": "low conf"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "LOW_CONFIDENCE")
        self.assertFalse(res["is_retryable"])

    def test_model_exception_nonterminal(self):
        candidate = {
            "detail_id": 107,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума",
            "context_after": "",
        }

        def raise_timeout(prompt):
            raise TimeoutError("timed out")

        validator = ContextValidator(ai_caller=raise_timeout)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "MODEL_EXCEPTION")
        self.assertTrue(res["is_retryable"])
        self.assertTrue(is_retryable_technical_result(res))

        conn = MockConnection()
        affected = update_candidate_validations(conn, [res])
        self.assertEqual(len(conn.cursor_obj.executed), 0)
        self.assertEqual(len(affected), 0)

    def test_invalid_json_nonterminal(self):
        candidate = {
            "detail_id": 108,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума",
            "context_after": "",
        }
        validator = ContextValidator(ai_caller=lambda p: "Not a JSON document")
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "INVALID_JSON")
        self.assertTrue(res["is_retryable"])

        conn = MockConnection()
        affected = update_candidate_validations(conn, [res])
        self.assertEqual(len(conn.cursor_obj.executed), 0)

    def test_invalid_decision_enum_nonterminal(self):
        candidate = {
            "detail_id": 109,
            "procurement_id": 5001,
            "category_code": "flooring",
            "subcategory_code": "commercial_homogeneous",
            "matched_term": "линолеум",
            "context_before": "поставка линолеума",
            "context_after": "",
        }
        raw_json = '{"decision": "MAYBE", "confidence": 0.90, "reason": "invalid enum"}'
        validator = ContextValidator(ai_caller=lambda p: raw_json)
        res = validator.validate_single(candidate)

        self.assertEqual(res["decision"], "UNKNOWN")
        self.assertEqual(res["reason_code"], "INVALID_DECISION_ENUM")
        self.assertTrue(res["is_retryable"])

        conn = MockConnection()
        affected = update_candidate_validations(conn, [res])
        self.assertEqual(len(conn.cursor_obj.executed), 0)

    def test_first_row_timeout_cascade_prevention(self):
        candidates = [
            {
                "id": i,
                "detail_id": i,
                "procurement_id": 5000 + i,
                "category_code": "flooring",
                "subcategory_code": "commercial_homogeneous",
                "matched_term": "линолеум",
                "context_before": f"поставка линолеума {i}",
                "context_after": "",
                "procurement_okpd_code": "43.33.10.000",
            }
            for i in range(1, 21)
        ]

        ai_mock = mock.MagicMock(side_effect=TimeoutError("timed out"))
        validator = ContextValidator(ai_caller=ai_mock)

        doc_conn = MockConnection(candidates)
        proc_rows = [{"id": 5000 + i, "auction_name": f"Proc {i}", "okpd_code": "43.33.10.000", "okpd_name": "Flooring"} for i in range(1, 21)]
        crm_conn = MockConnection(proc_rows)
        priors = [{"okpd_pattern": "43.33.10.000", "match_type": "PREFIX", "active": True}]
        taxonomy = mock.MagicMock(categories={"flooring": {"category_name": "Напольные покрытия", "subcategories": {}}})

        res = process_batch(doc_conn, crm_conn, validator, priors, taxonomy, target_procurement_ids=None, use_target_cache=False)

        # Candidate 1 timed out -> STOP model calls immediately at 1
        self.assertEqual(ai_mock.call_count, 1)
        self.assertEqual(res.claimed_count, 20)
        self.assertEqual(res.target_validated_count, 0)
        self.assertTrue(res.has_technical_failure)
        # ZERO DML updates written
        self.assertEqual(len(doc_conn.cursor_obj.executed), 1)  # only SELECT query executed

    def test_third_row_timeout_cascade_prevention(self):
        candidates = [
            {
                "id": i,
                "detail_id": i,
                "procurement_id": 5000 + i,
                "category_code": "flooring",
                "subcategory_code": "commercial_homogeneous",
                "matched_term": "линолеум",
                "context_before": f"поставка линолеума {i}",
                "context_after": "",
                "procurement_okpd_code": "43.33.10.000",
            }
            for i in range(1, 21)
        ]

        def ai_side_effect(prompt):
            if "линолеума 1" in prompt:
                return '{"decision": "CONFIRMED", "confidence": 0.95, "supporting_quote": "линолеума 1"}'
            elif "линолеума 2" in prompt:
                return '{"decision": "REJECTED", "confidence": 0.90, "supporting_quote": "линолеума 2"}'
            else:
                raise TimeoutError("timed out on row 3")

        ai_mock = mock.MagicMock(side_effect=ai_side_effect)
        validator = ContextValidator(ai_caller=ai_mock)

        doc_conn = MockConnection(candidates)
        proc_rows = [{"id": 5000 + i, "auction_name": f"Proc {i}", "okpd_code": "43.33.10.000", "okpd_name": "Flooring"} for i in range(1, 21)]
        crm_conn = MockConnection(proc_rows)
        priors = [{"okpd_pattern": "43.33.10.000", "match_type": "PREFIX", "active": True}]
        taxonomy = mock.MagicMock(categories={"flooring": {"category_name": "Напольные покрытия", "subcategories": {}}})

        res = process_batch(doc_conn, crm_conn, validator, priors, taxonomy, target_procurement_ids=None, use_target_cache=False)

        # Row 1 SUCCESS, Row 2 SUCCESS, Row 3 Timeout -> 3 AI calls executed total
        self.assertEqual(ai_mock.call_count, 3)
        self.assertEqual(res.claimed_count, 20)
        self.assertEqual(res.target_validated_count, 2)
        self.assertTrue(res.has_technical_failure)

        # Check DB updates: Rows 1 and 2 updated, Row 3 NOT updated
        update_queries = [q for q in doc_conn.cursor_obj.executed if "UPDATE document_match_details" in q[0]]
        self.assertEqual(len(update_queries), 2)
        updated_detail_ids = [q[1][-1] for q in update_queries]
        self.assertIn(1, updated_detail_ids)
        self.assertIn(2, updated_detail_ids)
        self.assertNotIn(3, updated_detail_ids)

    def test_backoff_calculation(self):
        b1 = INITIAL_BACKOFF_SECONDS
        self.assertEqual(b1, 60.0)
        b2 = min(b1 * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
        self.assertEqual(b2, 120.0)
        b3 = min(b2 * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
        self.assertEqual(b3, 240.0)
        b4 = min(b3 * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
        self.assertEqual(b4, 480.0)
        b5 = min(b4 * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
        self.assertEqual(b5, 900.0)
        b6 = min(b5 * BACKOFF_FACTOR, MAX_BACKOFF_SECONDS)
        self.assertEqual(b6, 900.0)  # bounded max

    def test_explicit_timeout_configuration(self):
        v_default = ContextValidator()
        self.assertEqual(v_default.timeout, CONTEXT_VALIDATOR_MODEL_TIMEOUT_SECONDS)
        self.assertEqual(v_default.timeout, 180)

        mock_generate = mock.MagicMock(return_value='{"decision": "UNKNOWN"}')
        with mock.patch("tender_documents_research.document_processor.context_validator.generate", mock_generate):
            v_test = ContextValidator()
            v_test.validate_single({
                "detail_id": 1,
                "procurement_id": 101,
                "category_code": "flooring",
                "matched_term": "линолеум",
                "context_before": "линолеум",
            })
            self.assertTrue(mock_generate.called)
            kwargs = mock_generate.call_args.kwargs
            self.assertEqual(kwargs.get("timeout"), 180)


if __name__ == "__main__":
    unittest.main()
