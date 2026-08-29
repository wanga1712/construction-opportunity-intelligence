"""Read-only composition model for the expert annotation workbench card."""
from __future__ import annotations

from typing import Any, Callable

from src.services.annotation_card_provenance import load_annotation_history, source_law
from src.services.commercial_routing_v3.document_links import resolve_document_links
from src.services.commercial_routing_v3.research_ui_projection import format_friendly_locator

PIPELINE_GENERATION = "S13_V2"


def _lifecycle(header: dict) -> str:
    if (
        "awarded" in str(header.get("source_table") or "").lower()
        or str(header.get("award_status") or "").lower() == "awarded"
        or str(header.get("crm_stage") or "").lower() == "razygranye"
    ):
        return "AWARDED"
    if str(header.get("award_status") or "").lower() in {
        "submission_closed_waiting_award", "award_not_found"
    }:
        return "COMMISSION"
    return "OPEN"


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
    if any(value and value not in {"SUCCESS", "DOWNLOADED", "OK", "COMPLETED"} for value in downloads):
        return "DOWNLOAD_FAILED"
    if any(value and value not in {"SUCCESS", "PARSED", "OK", "COMPLETED"} for value in parses):
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


def load_current_generation_raw_evidence(
    procurement_id: int,
    crm_db: Any,
    research_generation_hash: str | None = None,
) -> list[dict]:
    """Load strict current-generation raw evidence for a procurement."""
    if research_generation_hash:
        rows = crm_db.execute_query(
            """
            SELECT id, procurement_id, source_document_id, document_name, matched_term,
                   raw_text, context_before, context_after, source_locator_json,
                   suggested_category_code, created_at, research_generation_hash
            FROM crm_v3_raw_source_evidence
            WHERE procurement_id = %s AND pipeline_generation = %s AND research_generation_hash = %s
            ORDER BY source_document_id, id
            """,
            (procurement_id, PIPELINE_GENERATION, research_generation_hash),
        )
    else:
        from src.services.commercial_routing_v3.card_research_state import _get_doc_db_conn
        try:
            doc_conn = _get_doc_db_conn()
            with doc_conn.cursor() as cur:
                cur.execute(
                    "SELECT research_generation_hash FROM document_processing_queue WHERE procurement_id = %s AND pipeline_generation = %s ORDER BY id DESC LIMIT 1",
                    (procurement_id, PIPELINE_GENERATION),
                )
                row = cur.fetchone()
                gh = row[0] if row else None
            doc_conn.close()
        except Exception:
            gh = None
        if not gh:
            return []
        rows = crm_db.execute_query(
            """
            SELECT id, procurement_id, source_document_id, document_name, matched_term,
                   raw_text, context_before, context_after, source_locator_json,
                   suggested_category_code, created_at, research_generation_hash
            FROM crm_v3_raw_source_evidence
            WHERE procurement_id = %s AND pipeline_generation = %s AND research_generation_hash = %s
            ORDER BY source_document_id, id
            """,
            (procurement_id, PIPELINE_GENERATION, gh),
        )

    # Fetch active categories map
    cat_map: dict[str, str] = {}
    try:
        c_rows = crm_db.execute_query(
            "SELECT category_code, category_name FROM crm_product_categories WHERE is_active = True"
        )
        for r in (c_rows or []):
            code = r.get("category_code") or r.get("code")
            name = r.get("category_name") or r.get("name")
            if code and name:
                cat_map[code] = name
    except Exception:
        pass

    results = []
    for r in (rows or []):
        d = dict(r)
        cc = d.get("suggested_category_code")
        d["category_name"] = cat_map.get(cc, cc or "")
        d["friendly_locator"] = format_friendly_locator(d.get("source_locator_json"))
        results.append(d)
    return results


def compose_annotation_card_view(
    *,
    header: dict,
    resolved: dict,
    observations: list[dict],
    history: list[dict],
    raw_evidence: list[dict] | None = None,
) -> dict:
    """Pure composition step used by tests and the runtime loader."""
    lifecycle = _lifecycle(header)
    awarded = lifecycle == "AWARDED"
    initial = header.get("initial_price")
    final = header.get("final_contract_price")
    if final is None:
        final = header.get("final_price")
    display_amount = final if awarded and final is not None else initial
    display_amount_label = "Цена контракта" if awarded and final is not None else "НМЦК"

    if awarded:
        deadline = header.get("execution_end_at") or header.get("delivery_end_date")
        deadline_label = "Исполнение до" if deadline else "Срок исполнения"
    elif lifecycle == "COMMISSION":
        deadline = header.get("end_date")
        deadline_label = "Приём заявок завершён"
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
        if source_id is None and url:
            by_url.setdefault(url, []).append(observation)

    # Group raw evidence strictly by source_document_id
    evidence_by_doc_id: dict[int, list[dict]] = {}
    for ev in (raw_evidence or []):
        s_id = ev.get("source_document_id")
        if s_id is not None:
            evidence_by_doc_id.setdefault(int(s_id), []).append(ev)

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

        doc_ev = evidence_by_doc_id.get(int(source_id), []) if source_id is not None else []
        obs_state = _observation_state(matches)
        if doc_ev:
            obs_state = "OBSERVED_WITH_EVIDENCE"

        documents.append(
            {
                **source_document,
                "observations": matches,
                "observation_state": obs_state,
                "observation_join_method": join_method,
                "observation_join_deterministic": bool(matches),
                "research_evidence": doc_ev,
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

    # Sort documents: (1) with evidence, (2) researched no evidence, (3) processing/unobserved, (4) failed/unknown
    def _doc_sort_key(doc: dict) -> tuple[int, str]:
        ev_cnt = len(doc.get("research_evidence") or [])
        st = doc.get("observation_state") or "UNOBSERVED"
        name = str(doc.get("document_name") or "").casefold()
        if ev_cnt > 0 or st == "OBSERVED_WITH_EVIDENCE":
            group = 1
        elif st in ("OBSERVED_NO_EVIDENCE", "COMPLETED", "PARSED", "OK"):
            group = 2
        elif st == "UNOBSERVED":
            group = 3
        else:
            group = 4
        return (group, name)

    documents.sort(key=_doc_sort_key)

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
            "lifecycle": lifecycle,
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
    raw_evidence = load_current_generation_raw_evidence(procurement_id, crm_db)
    history = load_annotation_history(crm_db, procurement_id, header)
    return compose_annotation_card_view(
        header=header,
        resolved=resolved,
        observations=observations,
        history=history,
        raw_evidence=raw_evidence,
    )
