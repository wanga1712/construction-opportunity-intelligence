"""Export contract for a future DOCUMENT_VALUE_MODEL. No training here."""
from __future__ import annotations

import json
from collections.abc import Iterable

from src.services.document_learning.contract import DocumentObservation
from src.services.document_learning.policy import training_eligibility

EXPORT_CONTRACT_VERSION = "DOCUMENT_VALUE_MODEL_EXPORT_V0"


def export_records(observations: Iterable[DocumentObservation]) -> dict[str, object]:
    rows = [row.to_record() for row in observations]
    eligibility = training_eligibility(
        [row["acquisition_policy"] for row in rows]
    )
    return {
        "contract_version": EXPORT_CONTRACT_VERSION,
        "eligibility": eligibility,
        "rows": rows,
    }


def export_jsonl(observations: Iterable[DocumentObservation]) -> str:
    payload = export_records(observations)
    header = json.dumps(
        {
            "contract_version": payload["contract_version"],
            "eligibility": payload["eligibility"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    lines = [header]
    for row in payload["rows"]:
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"
