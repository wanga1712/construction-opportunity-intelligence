"""Один цикл наблюдателя обучения: где рвётся цепочка (пишет те же таблицы, что и демон)."""
import os
import sys
import traceback

sys.path.insert(0, "/opt/CRM_Streamlit")

from src.services.commercial_routing_v3.learning_observer import LearningObserver

APPLY = os.getenv("OBSERVER_APPLY", "0") == "1"
observer = LearningObserver()
stages = [
    ("snapshots", "_build_missing_snapshots"),
    ("truths", "_build_missing_truths"),
    ("evaluations", "_evaluate_predictions"),
    ("examples", "_materialize_examples"),
]
for name, method in stages:
    if not APPLY:
        print("%-12s (dry-run, не вызываю)" % name)
        continue
    try:
        result = getattr(observer, method)()
        print("%-12s -> %s" % (name, result))
    except Exception as exc:  # noqa: BLE001
        print("%-12s -> ОШИБКА %s: %s" % (name, type(exc).__name__, exc))
        traceback.print_exc()
        break
