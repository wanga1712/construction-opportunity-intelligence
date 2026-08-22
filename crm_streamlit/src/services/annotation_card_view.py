"""Read-only composition model for the expert annotation workbench card."""
from __future__ import annotations

from typing import Any, Callable

from src.services.annotation_card_provenance import load_annotation_history, source_law
from src.services.commercial_routing_v3.document_links import resolve_document_links


def _is_awarded(header: dict) -> bool:
    return (
        "awarded" in str(header.get("source_table") or "").lower()
        or str(header.get("award_status") or "").lower() == "awarded"
        or str(header.get("crm_stage") or "").lower() == "razygranye"
    )


def _exact_url(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _observation_state(rows: list[dict]) -> str:
    if not rows:
        return "UNOBSERVED"
    outcomes = {str(row.get("usefulness_label") or "").upper() for row in rows}
    downloads = {str(row.get("download_status") or "").upper() for row in rows}
    parses = {str(row.get("parse_status") or "").upper() for row in rows}
    for state in ("DOWNLOAD_FAILED", "PARSE_FAILED", "UNSUPPORTED_FORMAT", "EMPTY_DOCUMENT", "DUPLICATE_DOCUMENT"):
        if state in outcomes or state in downloads or state in parses:
            return state
    if any(value and value not in {"SUCCESS", "DOWNLOADED", "OK"} for value in downloads):
        return "DOWNLOAD_FAILED"
    if any(value and value not in {"SUCCESS", "PARSED", "OK"} for value in parses):
        return "PARSE_FAILED"
    if any(row.get("commercial_evidence_found") for row in rows):
        return "OBSERVED_WITH_EVIDENCE"
    return "OBSERVED_NO_EVIDENCE"


def load_document_observations(procurement_id: int, crm_db: Any) -> list[dict]:
    """Load the complete optional observation layer; never starts research."""
    rows = crm_db.execute_query(
        """
        SELECT id, source_document_id, document_title, source_document_type,
               source_document_url, download_status, parse_status,
               commercial_evidence_found, matched_categories, product_mentions,
               usefulness_label, observed_at
        FROM crm_v3_document_observations
        WHERE procurement_id = %s
        ORDER BY observed_at, id
        """,
        (procurement_id,),
    )
    return [dict(row) for row in (rows or [])]


def compose_annotation_card_view(
    *,
    header: dict,
    resolved: dict,
    observations: list[dict],
    history: list[dict],
) -> dict:
    """Pure composition step used by tests and the runtime loader."""
    awarded = _is_awarded(header)
    initial = header.get("initial_price")
    final = header.get("final_contract_price")
    if final is None:
        final = header.get("final_price")
    display_amount = final if awarded and final is not None else initial
    display_amount_label = "Цена контракта" if awarded and final is not None else "НМЦК"

    if awarded:
        deadline = header.get("execution_end_at") or header.get("delivery_end_date")
        deadline_label = "Исполнение до" if deadline else "Срок исполнения"
    else:
        deadline = header.get("end_date")
        deadline_label = "Приём заявок до"

    by_id: dict[str, list[dict]] = {}
    by_url: dict[str, list[dict]] = {}
    for observation in observations:
        source_id = observation.get("source_document_id")
        if source_id is not None:
            by_id.setdefault(str(source_id), []).append(observation)
        url = _exact_url(observation.get("source_document_url"))
        # URL is a legacy fallback, never a second identity when a source id exists.
        if source_id is None and url:
            by_url.setdefault(url, []).append(observation)

    used: set[Any] = set()
    documents = []
    contract_url = None
    contract_url_provenance = None
    for source_document in resolved.get("links") or []:
        source_id = source_document.get("source_document_id")
        id_hits = by_id.get(str(source_id), []) if source_id is not None else []
        url_hits = by_url.get(_exact_url(source_document.get("document_url")), [])
        matches = id_hits or url_hits
        join_method = "source_document_id" if id_hits else ("exact_url" if url_hits else None)
        used.update(row.get("id") for row in matches if row.get("id") is not None)
        documents.append(
            {
                **source_document,
                "observations": matches,
                "observation_state": _observation_state(matches),
                "observation_join_method": join_method,
                "observation_join_deterministic": bool(matches),
            }
        )
        name = str(source_document.get("document_name") or "").strip().casefold()
        url = _exact_url(source_document.get("document_url"))
        if awarded and name == "информация о контракте" and url and "/epz/contract/" in url:
            contract_url = url
            contract_url_provenance = (
                f"{source_document.get('link_source')}:source_document_id="
                f"{source_document.get('source_document_id')}"
            )

    orphan_observations = [
        row for row in observations if row.get("id") is None or row.get("id") not in used
    ]
    return {
        "facts": {
            "procurement_id": header.get("id"),
            "title": header.get("auction_name"),
            "procurement_number": header.get("contract_number"),
            "contract_number": header.get("contract_number"),
            "source_table": header.get("source_table"),
            "law": source_law(header.get("source_table")),
            "lifecycle": "AWARDED" if awarded else "OPEN",
            "award_status": header.get("award_status"),
            "customer": header.get("customer"),
            "region": header.get("delivery_region"),
            "initial_price": initial,
            "final_contract_price": final if awarded else None,
            "display_amount": display_amount,
            "display_amount_label": display_amount_label,
            "deadline": deadline,
            "deadline_label": deadline_label,
            "procurement_url": header.get("tender_link"),
            "contract_url": contract_url,
            "contract_url_provenance": contract_url_provenance,
            "crm_created_at": header.get("crm_created_at"),
            "crm_updated_at": header.get("crm_updated_at"),
            "source_updated_at": header.get("source_updated_at"),
        },
        "documents": documents,
        "document_count": len(documents),
        "document_resolution": {k: v for k, v in resolved.items() if k != "links"},
        "orphan_observations": orphan_observations,
        "history": history,
    }


def load_annotation_card_view(
    procurement_id: int,
    header: dict,
    crm_db: Any,
    *,
    resolver: Callable[..., dict] = resolve_document_links,
) -> dict:
    """Compose all read-only factual layers for one annotation card."""
    resolved = resolver(
        source_table=header.get("source_table") or "",
        source_id=header.get("source_id"),
        contract_number=header.get("contract_number"),
        limit=10000,
    )
    observations = load_document_observations(procurement_id, crm_db)
    history = load_annotation_history(crm_db, procurement_id, header)
    return compose_annotation_card_view(
        header=header,
        resolved=resolved,
        observations=observations,
        history=history,
    )
