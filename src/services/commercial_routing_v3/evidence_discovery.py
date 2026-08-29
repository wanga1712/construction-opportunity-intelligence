import hashlib, json, re
from typing import Any, Dict, List, Optional, Set, Tuple
from src.services.commercial_routing_v3.parsed_content_iterator import ParsedUnit, iter_parsed_units

PIPELINE_GENERATION = "S13_V3_EXHAUSTIVE_CONTEXT"

def compute_evidence_hash(matched_term: str, raw_text: str, source_locator_json: str) -> str:
    payload = f"{matched_term}||{raw_text}||{source_locator_json}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()

def compute_vocabulary_hash(vocab: List[Dict[str, Any]]) -> Tuple[str, str]:
    ser = json.dumps(vocab, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(ser.encode("utf-8")).hexdigest()
    version = f"v3_vocab_{h[:12]}"
    return version, h

def load_discovery_vocabulary(crm_db) -> List[Dict[str, Any]]:
    vocab: List[Dict[str, Any]] = []
    try:
        cats = crm_db.execute_query("SELECT category_code, category_name, is_active FROM crm_product_categories WHERE is_active = TRUE") or []
        for c in cats:
            code = c["category_code"]
            name = c.get("category_name") or ""
            if name and "?" not in name:
                vocab.append({"term": name.lower().strip(), "category_code": code, "method": "CATEGORY_NAME_MATCH"})
            code_clean = code.replace("_", " ").lower().strip()
            if len(code_clean) > 3 and "?" not in code_clean:
                vocab.append({"term": code_clean, "category_code": code, "method": "CATEGORY_CODE_MATCH"})
    except Exception:
        pass

    try:
        subs = crm_db.execute_query("""
            SELECT s.subcategory_code, s.subcategory_name, c.category_code
            FROM crm_product_subcategories s
            JOIN crm_product_categories c ON c.id = s.category_id
            WHERE c.is_active = TRUE AND s.is_active = TRUE
        """) or []
        for s in subs:
            sname = s.get("subcategory_name") or ""
            if sname and "?" not in sname:
                vocab.append({"term": sname.lower().strip(), "category_code": s["category_code"], "method": "SUBCATEGORY_NAME_MATCH"})
    except Exception:
        pass

    return vocab

def discover_and_persist_raw_evidence(
    procurement_id: int,
    crm_db,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    contract_number: Optional[str] = None,
    pipeline_generation: str = PIPELINE_GENERATION,
    research_generation_hash: Optional[str] = None,
) -> List[Dict[str, Any]]:
    vocab = load_discovery_vocabulary(crm_db)
    vocab_version, vocab_hash = compute_vocabulary_hash(vocab)
    raw_hits: List[Dict[str, Any]] = []
    seen_hashes: Set[str] = set()

    for unit in iter_parsed_units(procurement_id, source_table, source_id, contract_number):
        text_lower = unit.raw_text.lower()
        if not text_lower:
            continue

        # Exhaustive search across ALL vocabulary terms (FIRST_MATCH_BREAK = NO)
        for v in vocab:
            if v["term"] in text_lower:
                matched_term = v["term"]
                source_loc_json = json.dumps(unit.source_locator, default=str, sort_keys=True)
                ev_hash = compute_evidence_hash(matched_term, unit.raw_text, source_loc_json)

                if ev_hash in seen_hashes:
                    continue
                seen_hashes.add(ev_hash)

                ctx_before = unit.context_before or ["Content unit preceding locator."]
                ctx_after = unit.context_after or ["Content unit following locator."]

                raw_hits.append({
                    "procurement_id": procurement_id,
                    "source_document_id": unit.source_document_id,
                    "document_name": unit.document_name,
                    "matched_term": matched_term,
                    "raw_text": unit.raw_text,
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                    "source_locator_json": source_loc_json,
                    "discovery_method": v["method"],
                    "suggested_category_code": v["category_code"],
                    "evidence_hash": ev_hash,
                    "pipeline_generation": pipeline_generation,
                    "research_generation_hash": research_generation_hash,
                })

    persisted_rows: List[Dict[str, Any]] = []
    for hit in raw_hits:
        res = crm_db.execute_query(
            """
            INSERT INTO crm_v3_raw_source_evidence (
                procurement_id, source_document_id, document_name,
                matched_term, raw_text, context_before, context_after,
                source_locator_json, discovery_method, suggested_category_code,
                evidence_hash, pipeline_generation, research_generation_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id, procurement_id, source_document_id, document_name, matched_term, raw_text, source_locator_json, evidence_hash, pipeline_generation, research_generation_hash, created_at
            """,
            (
                hit["procurement_id"],
                hit["source_document_id"],
                hit["document_name"],
                hit["matched_term"],
                hit["raw_text"],
                json.dumps(hit["context_before"], ensure_ascii=False),
                json.dumps(hit["context_after"], ensure_ascii=False),
                hit["source_locator_json"],
                hit["discovery_method"],
                hit["suggested_category_code"],
                hit["evidence_hash"],
                hit["pipeline_generation"],
                hit["research_generation_hash"],
            ),
        )
        if res:
            persisted_rows.extend(res)

    return persisted_rows
