import inspect
import os
import unittest
from unittest.mock import patch


class CaptureRepository:
    def __init__(self, dsn, pipeline_generation):
        self.pipeline_generation_value = pipeline_generation


class GenerationAlignmentTests(unittest.TestCase):
    def test_s13_v2_backend_uses_v4_generation_by_default(self):
        from tender_documents_research.document_processor.backends import factory

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(factory, "_load_s13_dsn", return_value={}), \
             patch.object(factory, "_verify_s13_connection"), \
             patch.object(factory, "S13V2QueueRepository", CaptureRepository), \
             patch.object(factory, "S13V2StateRepository", CaptureRepository), \
             patch("tender_documents_research.document_processor.backends.s13_results.S13V2ResultStore", CaptureRepository):
            backend = factory.create_processing_backend("S13_V2")

        self.assertEqual(backend.queue.pipeline_generation_value, "S13_V4_EXHAUSTIVE_CONTEXT")
        self.assertEqual(backend.state.pipeline_generation_value, "S13_V4_EXHAUSTIVE_CONTEXT")
        self.assertEqual(backend.results.pipeline_generation_value, "S13_V4_EXHAUSTIVE_CONTEXT")

    def test_explicit_generation_is_shared_without_renaming_backend(self):
        from tender_documents_research.document_processor.backends import factory

        with patch.dict(os.environ, {"DOCUMENT_PIPELINE_GENERATION": "S13_V4_EXHAUSTIVE_CONTEXT"}), \
             patch.object(factory, "_load_s13_dsn", return_value={}), \
             patch.object(factory, "_verify_s13_connection"), \
             patch.object(factory, "S13V2QueueRepository", CaptureRepository), \
             patch.object(factory, "S13V2StateRepository", CaptureRepository), \
             patch("tender_documents_research.document_processor.backends.s13_results.S13V2ResultStore", CaptureRepository):
            backend = factory.create_processing_backend("S13_V2")

        self.assertEqual(backend.queue.pipeline_generation_value, "S13_V4_EXHAUSTIVE_CONTEXT")

    def test_daemon_persistence_reads_same_runtime_setting(self):
        from tender_documents_research.document_processor import daemon

        source = inspect.getsource(daemon.DocumentProcessorDaemon.__init__)
        self.assertIn("DOCUMENT_PIPELINE_GENERATION", source)
        self.assertIn("S13_V4_EXHAUSTIVE_CONTEXT", source)


if __name__ == "__main__":
    unittest.main()
