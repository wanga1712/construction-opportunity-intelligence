import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).parents[1] / "deploy" / "s13_dashboard3.py"
spec = importlib.util.spec_from_file_location("s13_dashboard3", PATH)
kiosk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kiosk)

class RuntimeObservabilityTests(unittest.TestCase):
    def test_gpu_process_attribution(self):
        rows = kiosk.parse_gpu_compute_apps("42, llama-server, 1200 MiB", {42: {"ppid": 7, "cmd": "llama-server"}, 7: {"cmd": "ollama serve"}}, lambda pid: "ollama.service")
        self.assertEqual(rows[0]["unit"], "ollama.service")
        self.assertEqual(rows[0]["parent"], "ollama serve")

    def test_stopped_document_workers(self):
        state = kiosk.document_runtime_counts(4, 3, 0)
        self.assertEqual(state["state"], "STALE_PROCESSING")
        self.assertEqual(state["stale"], 3)

    def test_stale_processing_rows(self):
        self.assertEqual(kiosk.document_runtime_counts(0, 2, 0)["stale"], 2)

    def test_idle_service(self):
        self.assertEqual(kiosk.classify_service_runtime("active", 123, False), "IDLE")

    def test_active_assessment_procurement(self):
        log = ["Processing CRM ID 485092", "persisted 0 category opportunities for procurement_id=485092", "Processing CRM ID 485141"]
        self.assertEqual(kiosk.parse_current_assessment(log), 485141)

    def test_normalization_off(self):
        self.assertEqual(kiosk.normalization_runtime_state(True, False), "OFF")

    def test_event_feed(self):
        events = kiosk.parse_runtime_events([f"2026-11-16 event {i}" for i in range(25)])
        self.assertEqual(len(events), 20)
        self.assertTrue(events[0]["event"].endswith("event 5"))

if __name__ == "__main__":
    unittest.main()
