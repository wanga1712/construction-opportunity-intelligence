from __future__ import annotations

import inspect
from pathlib import Path

from src.services.commercial_routing_v3.projection import resolve_lifecycle_identity
from src.services.commercial_routing_v3.projection_writer import _find_existing_indexed
from src.services.commercial_routing_v3.queue_producer import CommercialRoutingV3QueueProducer


def test_awarded_provenance_wins_over_open_stable_identity() -> None:
    ident = resolve_lifecycle_identity(
        source_table="reestr_contract_44_fz_awarded",
        source_id=547747,
        contract_number="0373200275826000001",
    )
    open_row = {"id": 163706, "source_table": "reestr_contract_44_fz", "source_id": 618608}
    awarded_row = {
        "id": 22103,
        "source_table": "reestr_contract_44_fz_awarded",
        "source_id": 547747,
    }
    index = {
        "by_stable": {ident.key(): open_row},
        "by_prov": {("reestr_contract_44_fz_awarded", 547747): awarded_row},
        "by_awarded": {},
    }

    assert _find_existing_indexed(index, ident) is awarded_row


def test_queue_producer_carries_crm_end_date_to_submission_deadline() -> None:
    source = inspect.getsource(CommercialRoutingV3QueueProducer._upsert_queue_task)
    assert "submission_end_at" in source
    assert "task[\"submission_end_at\"]" in source


def test_queue_deadline_migration_is_idempotent() -> None:
    migration = Path("src/migrations/document_processing_queue_submission_end_at.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS submission_end_at" in migration
    assert "CREATE INDEX IF NOT EXISTS" in migration
