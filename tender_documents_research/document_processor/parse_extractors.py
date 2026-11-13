"""Parse-time extraction: estimates (tables) and project metadata (R4-PD).

Retention deletes raw files after 3 days, so everything we may ever need must be
extracted while the file is still on disk. This hook runs right after a document
is parsed and persists:
  * universal estimate rows -> structured_estimate_rows
  * DIRECT compatibility facts -> structured_entities (legacy read fallback)
  * project organizations / people -> project_metadata_* (raw + source_quote)
Fail-safe by design: any error is logged and never breaks parsing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("parse_extractors")

_TAXONOMY_INDEX_CACHE: Dict[str, Any] | None = None
_CATEGORY_SIGNAL_INDEX_CACHE: Dict[str, set] | None = None
_TAXONOMY_PATTERN_CACHE: tuple[Dict[str, Any], re.Pattern[str]] | None = None
_CATEGORY_PATTERN_CACHE: tuple[Dict[str, set], re.Pattern[str]] | None = None
_ESTIMATE_TAXONOMY_CACHE: Any = None
_ESTIMATE_TAXONOMY_SNAPSHOT: Any = None


def _call_estimate_row_ai(prompt: str) -> str:
    """Run one bounded row batch through the shared local Ollama GPU arbiter."""
    import urllib.request
    from document_processor.estimate_row_ai_normalizer import (
        response_schema_for_prompt,
    )

    model = os.getenv("ESTIMATE_ROW_NORMALIZER_MODEL", "qwen2.5:7b")
    url = os.getenv("OLLAMA_GENERATE_URL", "http://localhost:11434/api/generate")
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": response_schema_for_prompt(prompt),
            "options": {"temperature": 0, "num_predict": 1800},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    from document_processor.docs_gpu_arbiter_lock import acquire_document_gpu

    with acquire_document_gpu(
        defer_when_routing=True,
        max_wait_sec=float(os.getenv("ESTIMATE_ROW_AI_GPU_MAX_WAIT_SEC", "120")),
    ):
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read())
    return str(payload.get("response") or "")


def _project_estimate_row_categories(rows: list[Any]) -> None:
    """Resolve universal rows with the active CRM taxonomy; ambiguous stays NULL."""
    global _ESTIMATE_TAXONOMY_CACHE, _ESTIMATE_TAXONOMY_SNAPSHOT
    if not rows:
        return
    if _ESTIMATE_TAXONOMY_CACHE is None:
        from document_processor.crm_taxonomy_loader import CrmTaxonomyLoader
        from document_processor.estimate_row_taxonomy import EstimateTaxonomy

        snapshot = CrmTaxonomyLoader(contour_code="procurement").load_snapshot()
        _ESTIMATE_TAXONOMY_SNAPSHOT = snapshot
        terms = [
            (
                term.category_code,
                term.subcategory_code,
                term.term_type,
                term.phrase,
                term.weight,
            )
            for term in snapshot.terms
            if term.term_type in {"search", "negative"}
        ]
        _ESTIMATE_TAXONOMY_CACHE = EstimateTaxonomy.from_rows(terms)

    try:
        from document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

        procurement_contexts = CrmTaxonomyLoader(
            contour_code="procurement"
        ).load_procurement_contexts(
            [int(row.procurement_id) for row in rows if getattr(row, "procurement_id", None) is not None]
        )
    except Exception as exc:  # noqa: BLE001 - category extraction must remain available
        logger.warning("procurement context unavailable for estimate rows: %s", exc)
        procurement_contexts = {}

    projected = []
    for row in rows:
        if row.row_kind not in {"GOODS", "SPECIAL_WORK_REVIEW"}:
            projected.append((None, None))
            continue
        attribute_terms = []
        for attribute in row.technical_attributes or []:
            if not isinstance(attribute, dict):
                continue
            attribute_terms.extend(
                str(attribute.get(key) or "").strip()
                for key in ("raw_value", "normalized_value", "attribute_name")
            )
        resolution = _ESTIMATE_TAXONOMY_CACHE.resolve(
            " ".join([row.name_raw, *attribute_terms])
        )
        projected.append((resolution.category_code, resolution.subcategory_code))
    for row, (category_code, subcategory_code) in zip(rows, projected):
        row.category_code = category_code
        row.subcategory_code = subcategory_code
        row.category_resolution_attempted = True
        row.category_decision = {
            "decision_code": (
                "NOT_A_GOOD" if row.row_kind not in {"GOODS", "SPECIAL_WORK_REVIEW"}
                else ("RULE_FALLBACK" if category_code else "RULE_UNRESOLVED")
            ),
            "category_code": category_code,
            "subcategory_code": subcategory_code,
            "confidence": None,
            "reason": "active_taxonomy_rule_fallback",
            "evidence_quote": row.source_quote or row.name_raw,
            "model_name": None,
            "prompt_version": "estimate_row_rule_v1",
        }

    if os.getenv("ESTIMATE_ROW_AI_NORMALIZATION", "1").strip().lower() in {
        "0", "false", "no", "off"
    }:
        return
    eligible = [
        (index, row) for index, row in enumerate(rows)
        if row.row_kind == "GOODS"
        or (
            row.row_kind == "SPECIAL_WORK_REVIEW"
            and row.special_work_family == "structural_reinforcement"
        )
    ]
    if not eligible:
        return
    try:
        from document_processor.estimate_row_ai_normalizer import (
            PROMPT_VERSION,
            adjudicate_rows,
        )

        model = os.getenv("ESTIMATE_ROW_NORMALIZER_MODEL", "qwen2.5:7b")
        candidates = [row for _, row in eligible]
        decisions = adjudicate_rows(
            candidates,
            _ESTIMATE_TAXONOMY_SNAPSHOT,
            ai_caller=_call_estimate_row_ai,
            model_name=model,
            # Small local models showed cross-row evidence leakage in 4-row
            # canaries. Keep row identity reliable unless explicitly overridden.
            batch_size=int(os.getenv("ESTIMATE_ROW_AI_BATCH_SIZE", "1")),
            procurement_contexts=procurement_contexts,
        )
        terms_payload = [
            (term.category_code, term.subcategory_code, term.term_type, term.phrase)
            for term in _ESTIMATE_TAXONOMY_SNAPSHOT.terms
        ]
        taxonomy_hash = hashlib.sha256(
            json.dumps(terms_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        for candidate_index, (_row_index, row) in enumerate(eligible):
            decision = decisions[candidate_index]
            # Malformed/unavailable model output preserves the auditable rule
            # fallback; a valid unresolved answer explicitly clears the guess.
            if decision.reason == "invalid_model_item":
                continue
            row.category_code = decision.category_code
            row.subcategory_code = decision.subcategory_code
            row.category_decision = {
                "decision_code": {
                    "EXISTING_CATEGORY": "AI_EXISTING_CATEGORY",
                    "OTHER_OR_UNRESOLVED": "AI_OTHER_OR_UNRESOLVED",
                    "NEW_CATEGORY_CANDIDATE": "AI_NEW_CATEGORY_CANDIDATE",
                }[decision.decision],
                "category_code": decision.category_code,
                "subcategory_code": decision.subcategory_code,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "evidence_quote": decision.evidence_quote,
                "proposed_category_name": decision.new_category_name,
                "model_name": model,
                "prompt_version": PROMPT_VERSION,
                "taxonomy_snapshot_hash": taxonomy_hash,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("estimate-row AI normalization unavailable: %s", exc)


def _normalize_phrase(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _compile_phrase_pattern(phrases) -> re.Pattern[str]:
    ordered = sorted(
        {_normalize_phrase(phrase) for phrase in phrases if _normalize_phrase(phrase)},
        key=lambda phrase: (-len(phrase), phrase),
    )
    if not ordered:
        return re.compile(r"(?!x)x")
    strict = []
    adjective = []
    inflected = []
    for phrase in ordered:
        escaped = re.escape(phrase)
        if re.search(r"[a-z0-9]", phrase):
            strict.append(escaped)
        elif phrase.endswith(("ый", "ий", "ой")):
            adjective.append(escaped)
        else:
            inflected.append(escaped)
    branches = []
    if strict:
        branches.append(r"(?P<strict_phrase>" + "|".join(strict) + r")(?!\w)")
    if adjective:
        branches.append(
            r"(?P<adjective_phrase>" + "|".join(adjective) + r")"
            r"(?:ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ым|им|ом|ем|"
            r"ую|юю|ых|их|ыми|ими|ой|ей)?(?!\w)"
        )
    if inflected:
        branches.append(
            r"(?P<inflected_phrase>" + "|".join(inflected) + r")"
            r"(?:а|я|у|ю|ом|ем|е|ы|и|ов|ев|ей|ам|ям|ами|ями|ах|ях)?(?!\w)"
        )
    return re.compile(r"(?<!\w)(?:" + "|".join(branches) + r")")


def _matched_phrases(pattern: re.Pattern[str], text: str) -> set[str]:
    matched = set()
    for match in pattern.finditer(text):
        for name in ("strict_phrase", "adjective_phrase", "inflected_phrase"):
            if name in pattern.groupindex and match.group(name):
                matched.add(match.group(name))
                break
    return matched


def _taxonomy_index() -> Dict[str, Any]:
    global _TAXONOMY_INDEX_CACHE
    if _TAXONOMY_INDEX_CACHE is None:
        from document_processor.crm_taxonomy_loader import load_keyword_index

        normalized: Dict[str, Any] = {}
        for phrase, bucket in load_keyword_index().items():
            normalized_phrase = _normalize_phrase(phrase)
            if not normalized_phrase:
                continue
            target = normalized.setdefault(
                normalized_phrase,
                {
                    **bucket,
                    "keyword": normalized_phrase,
                    "category_codes": [],
                },
            )
            for category in bucket.get("category_codes") or []:
                if category not in target["category_codes"]:
                    target["category_codes"].append(category)
            target["weight"] = max(
                int(target.get("weight") or 100),
                int(bucket.get("weight") or 100),
            )
        _TAXONOMY_INDEX_CACHE = normalized
    return _TAXONOMY_INDEX_CACHE


def _category_signal_index() -> Dict[str, set]:
    global _CATEGORY_SIGNAL_INDEX_CACHE
    if _CATEGORY_SIGNAL_INDEX_CACHE is None:
        from document_processor.crm_taxonomy_loader import CrmTaxonomyLoader

        snapshot = CrmTaxonomyLoader().load_snapshot()
        index: Dict[str, set] = {}
        for code, category in snapshot.categories.items():
            phrases = list(category.get("positive_signals") or [])
            phrases += list(category.get("aliases") or [])
            for phrase in phrases:
                phrase = _normalize_phrase(phrase)
                if phrase:
                    index.setdefault(phrase, set()).add(code)
        _CATEGORY_SIGNAL_INDEX_CACHE = index
    return _CATEGORY_SIGNAL_INDEX_CACHE


def _resolve_embedded_category(name: str, fallback: str) -> Optional[str]:
    """Return the best registry category for a row, or None."""
    global _TAXONOMY_PATTERN_CACHE, _CATEGORY_PATTERN_CACHE

    from document_processor.estimate_row_taxonomy import (
        category_semantic_guard,
    )

    low = _normalize_phrase(name)
    if not low:
        return None
    scores: Dict[str, int] = {}
    taxonomy = _taxonomy_index()
    if _TAXONOMY_PATTERN_CACHE is None or _TAXONOMY_PATTERN_CACHE[0] is not taxonomy:
        _TAXONOMY_PATTERN_CACHE = (taxonomy, _compile_phrase_pattern(taxonomy))
    for phrase in _matched_phrases(_TAXONOMY_PATTERN_CACHE[1], low):
        bucket = taxonomy[phrase]
        weight = int(bucket.get("weight") or 100)
        for category in bucket.get("category_codes") or []:
            scores[category] = scores.get(category, 0) + weight
    if not scores:
        category_index = _category_signal_index()
        if (
            _CATEGORY_PATTERN_CACHE is None
            or _CATEGORY_PATTERN_CACHE[0] is not category_index
        ):
            _CATEGORY_PATTERN_CACHE = (
                category_index,
                _compile_phrase_pattern(category_index),
            )
        for phrase in _matched_phrases(_CATEGORY_PATTERN_CACHE[1], low):
            for category in category_index[phrase]:
                scores[category] = scores.get(category, 0) + 100
    if not scores:
        return None
    scores = {
        category: score
        for category, score in scores.items()
        if category_semantic_guard(category, low)
    }
    if not scores:
        return None
    return max(scores, key=lambda k: (scores[k], k))


def _section_cells(quote: str) -> list:
    """Split a stored cell dump ("A=… | B=…") into bare cell texts.

    SECTION_LEVEL_NORMALIZATION_V1: the section detector must see the cell text
    without its column prefix so "Итого по главе N" / "Итого:" match.
    """
    out = []
    for part in str(quote or "").split("|"):
        part = part.strip()
        if not part:
            continue
        if len(part) > 2 and part[1] == "=" and part[0].isupper():
            part = part[2:].strip()
        out.append(part)
    return out


def _estimate_layout(fact) -> str:
    """Value-provenance for an estimate row (mirrors the embedded contract)."""
    explicit = str(getattr(fact, "layout_status", "") or "").upper()
    if explicit == "UNIT_RATE_ONLY":
        return explicit
    qty = getattr(fact, "quantity_value", None)
    price = getattr(fact, "unit_price_value", None)
    total = getattr(fact, "total_price_value", None)
    if qty is None or price is None or total is None:
        return "UNSUPPORTED_LAYOUT"
    computed = float(qty) * float(price)
    denom = max(abs(float(total)), abs(computed), 1.0)
    if abs(float(total) - computed) / denom > 0.05:
        return "INCONSISTENT_LAYOUT"
    return "CONSISTENT"


_DDL = (
    """CREATE TABLE IF NOT EXISTS project_metadata_organizations (
         id bigserial PRIMARY KEY,
         procurement_id bigint NOT NULL,
         organization_name_raw text NOT NULL,
         organization_role_raw text,
         document_name text,
         page_or_sheet text,
         source_quote text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT NOW()
       )""",
    """CREATE TABLE IF NOT EXISTS project_metadata_people (
         id bigserial PRIMARY KEY,
         procurement_id bigint NOT NULL,
         person_name_raw text NOT NULL,
         role_raw text,
         organization_name_raw text,
         document_name text,
         page_or_sheet text,
         source_quote text NOT NULL,
         created_at timestamptz NOT NULL DEFAULT NOW()
       )""",
)


def _connect():
    from dotenv import load_dotenv

    load_dotenv("/opt/CRM_Streamlit/.env", override=True)
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ.get("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("S13_DOCUMENT_DB_PORT", "5432")),
        dbname=os.environ.get("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        user=os.environ.get("S13_DOCUMENT_DB_USER", "doc_worker"),
        password=os.environ["S13_DOCUMENT_DB_PASSWORD"],
    )
    return conn


def _persist_estimate(conn, path: Path, procurement_id: int, document_name: str) -> int:
    from document_processor.smeta_forma_4b import detect_forma_4b, read_estimate, xlsx_sheet_names
    from document_processor.xlsx_table_reader import read_tables
    from document_processor.section_detector import (
        SECTION_RESIDUE,
        SectionTracker,
        is_aggregate_row,
        is_summarizable,
    )

    if detect_forma_4b(xlsx_sheet_names(path)):
        facts = read_estimate(path)
    else:
        facts = read_tables(path)
    if not facts:
        return 0
    # SECTION_LEVEL_NORMALIZATION_V1 (Phase 2): the xlsx estimate path is not
    # covered by embedded_extraction, so derive the deterministic section state
    # here over the reader rows (quote cells carry column A markers).
    _tracker = SectionTracker()
    _fact_section: Dict[int, Any] = {}
    for _fact in facts:
        _quote = str(getattr(_fact, "source_quote", "") or "")
        _sheet = getattr(_fact, "sheet", None) or getattr(_fact, "sheet_name", None)
        _code = _tracker.observe(
            str(_sheet) if _sheet else None, _section_cells(_quote), _quote
        )
        _name = getattr(_fact, "product_name_raw", None)
        _unit = getattr(_fact, "quantity_unit", None)
        _qty = getattr(_fact, "quantity_value", None)
        _tracker.add_child(
            _code,
            getattr(_fact, "total_price_value", None),
            summarizable=is_summarizable(
                layout_status=_estimate_layout(_fact),
                quantity_value=_qty,
                unit_normalized=_unit,
                name=_name,
            ),
            aggregate=is_aggregate_row(
                name=_name, unit_normalized=_unit, quantity_value=_qty
            ),
        )
        _fact_section[id(_fact)] = _code
    _tracker.finalize()
    cur = conn.cursor()
    cur.execute(
        "SELECT MIN(id) FROM document_match_details WHERE procurement_id=%s",
        (procurement_id,),
    )
    detail_id = cur.fetchone()[0]  # nullable; may be None when no match detail exists
    payload = json.dumps([getattr(f, "__dict__", {}) for f in facts], ensure_ascii=False, default=str)
    cur.execute(
        """INSERT INTO structured_extraction_runs
             (detail_id, procurement_id, category_code, document_name, page_or_sheet,
              source_text_snapshot, source_text_sha256, source_validator_name,
              source_validator_version, source_validation_method, extractor_name,
              extractor_version, extraction_method, prompt_version, model_name, status,
              created_at, completed_at, structured_fact_trust_state)
           VALUES (%s,%s,%s,%s,'sheet1',%s,%s,'PROVENANCE_CONTRACT','v1','PARSE_TIME',
                   'PARSE_TIME_READER','v1','DETERMINISTIC_TABLE_MAP','none','none','COMPLETED',
                   NOW(),NOW(),'MANUAL_PROOF_QUARANTINE')
           ON CONFLICT (detail_id, extractor_version) DO UPDATE
             SET source_text_snapshot = EXCLUDED.source_text_snapshot,
                 source_text_sha256 = EXCLUDED.source_text_sha256,
                 completed_at = NOW()
           RETURNING id""",
        (detail_id, procurement_id,
         getattr(facts[0], "category_code", "unknown"), document_name,
         payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()),
    )
    run_id = cur.fetchone()[0]
    saved = 0
    for fact in facts:
        name = getattr(fact, "product_name_raw", None)
        if not name:
            continue
        fingerprint = hashlib.sha256(
            f"{procurement_id}|{name}|{getattr(fact, 'row', '')}".encode("utf-8")
        ).hexdigest()
        _code = _fact_section.get(id(fact)) or SECTION_RESIDUE
        _info = _tracker.section(_code)
        cur.execute(
            """INSERT INTO structured_entities
                 (run_id, detail_id, procurement_id, category_code, entity_fingerprint,
                  entity_type, product_name_raw, product_name_normalized, quantity_value,
                  quantity_raw, quantity_unit_raw, quantity_unit_normalized,
                  unit_price_value, unit_price_raw, total_price_value, total_price_raw,
                  currency_code, source_quote, confidence, product_relation, created_at,
                  structured_fact_trust_state,
                  section_code, section_name, section_total_price_value,
                  section_total_price_raw, section_total_source)
               VALUES (%s,%s,%s,%s,%s,'PRODUCT',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RUB',%s,0.9,
                       'EMBEDDED',NOW(),'MANUAL_PROOF_QUARANTINE',
                       %s,%s,%s,%s,%s)
               ON CONFLICT ON CONSTRAINT uq_entity_run_fingerprint DO UPDATE SET
                   quantity_value = EXCLUDED.quantity_value,
                   unit_price_value = EXCLUDED.unit_price_value,
                   total_price_value = EXCLUDED.total_price_value,
                   total_price_raw = EXCLUDED.total_price_raw,
                   source_quote = EXCLUDED.source_quote,
                   section_code = EXCLUDED.section_code,
                   section_name = EXCLUDED.section_name,
                   section_total_price_value = EXCLUDED.section_total_price_value,
                   section_total_price_raw = EXCLUDED.section_total_price_raw,
                   section_total_source = EXCLUDED.section_total_source""",
            (run_id, detail_id, procurement_id, getattr(fact, "category_code", "unknown"),
             fingerprint, name, name, getattr(fact, "quantity_value", None),
             str(getattr(fact, "quantity_value", "")), getattr(fact, "quantity_unit", ""),
             getattr(fact, "quantity_unit", ""), getattr(fact, "unit_price_value", None),
             str(getattr(fact, "unit_price_value", "")), getattr(fact, "total_price_value", None),
             str(getattr(fact, "total_price_value", "")), getattr(fact, "source_quote", ""),
             _code, (_info.name if _info else None),
             (_info.total_value if _info else None), (_info.total_raw if _info else None),
             (_info.total_source if _info else None)),
        )
        saved += 1
    return saved


def _persist_metadata(conn, text: str, procurement_id: int, document_name: str) -> int:
    from document_processor.project_metadata_reader import scan_lines

    hits = scan_lines((text or "").splitlines())
    if not hits:
        return 0
    cur = conn.cursor()
    saved = 0
    for hit in hits:
        if hit.kind == "PERSON":
            cur.execute(
                """INSERT INTO project_metadata_people
                     (procurement_id, person_name_raw, role_raw, document_name, source_quote)
                   VALUES (%s,%s,%s,%s,%s)""",
                (procurement_id, hit.raw_value, hit.role_bucket, document_name, hit.source_quote),
            )
        else:
            cur.execute(
                """INSERT INTO project_metadata_organizations
                     (procurement_id, organization_name_raw, organization_role_raw,
                      document_name, source_quote)
                   VALUES (%s,%s,%s,%s,%s)""",
                (procurement_id, hit.raw_value, hit.role_bucket, document_name, hit.source_quote),
            )
        saved += 1
    return saved


def extract_and_persist(
    path: Any,
    text: Optional[str],
    procurement_id: Optional[int],
    document_name: Optional[str] = None,
    *,
    category_code: Optional[str] = None,
    source_document_id: Optional[int] = None,
    physical_key: Optional[str] = None,
    line_meta: Optional[Dict[int, Any]] = None,
    track: Optional[str] = None,
    document_class: Optional[str] = None,
    allowed_categories: Optional[set] = None,
) -> Dict[str, int]:
    """Best-effort parse-time extraction; never raises.

    Estimate-like rows use one universal extractor and the active CRM taxonomy.
    DIRECT compatibility extraction remains enabled until its read-model canary
    is accepted. Ambiguous taxonomy matches are kept unresolved.
    """
    result = {
        "facts": 0,
        "metadata": 0,
        "embedded": 0,
        "estimate_rows": 0,
    }
    universal_attempted = False
    universal_extracted = 0
    universal_goods = 0
    universal_categorized = 0
    universal_normalized = False
    universal_error = None
    if procurement_id is None:
        return result
    try:
        path = Path(path)
        name = document_name or path.name
        conn = _connect()
        try:
            conn.cursor().execute("SELECT 1")
            for statement in _DDL:
                conn.cursor().execute(statement)
            from document_processor.estimate_row_persistence import (
                ensure_estimate_row_schema,
            )

            ensure_estimate_row_schema(conn)
            conn.commit()
            # Each extractor is isolated: one failing must not block the others.
            track_upper = str(track or "").upper()
            direct_track = track_upper in {"DIRECT", "DIRECT_SUPPLY"}
            # Extract estimate rows into the shared contract on all tracks.
            # DIRECT's category-bound writer remains a compatibility source
            # until the card/read-model canary is accepted.
            estimate_classes = {"ESTIMATE", "BOQ", "NMCK_JUSTIFICATION"}
            universal_estimate = (
                not direct_track
                or str(document_class or "").upper() in estimate_classes
            )
            if universal_estimate:
                universal_attempted = True
                if source_document_id is None:
                    logger.warning(
                        "estimate-row source identity unavailable; retaining name fallback only: procurement=%s document=%s",
                        procurement_id,
                        name,
                    )
                try:
                    from document_processor.estimate_row_persistence import (
                        persist_estimate_rows,
                    )
                    from document_processor.universal_estimate_rows import (
                        extract_universal_estimate_rows,
                    )

                    estimate_rows = extract_universal_estimate_rows(
                        path,
                        procurement_id=int(procurement_id),
                        document_name=name,
                        source_document_id=source_document_id,
                        text=text,
                        line_meta=line_meta,
                    )
                    universal_extracted = len(estimate_rows)
                    universal_goods = sum(
                        str(getattr(row, "row_kind", "")).upper() == "GOODS"
                        for row in estimate_rows
                    )
                    try:
                        _project_estimate_row_categories(estimate_rows)
                        universal_normalized = True
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "estimate-row taxonomy projection failed for %s: %s",
                            name,
                            exc,
                        )
                    result["estimate_rows"] = persist_estimate_rows(
                        conn, estimate_rows
                    )
                    universal_categorized = sum(
                        bool(getattr(row, "category_code", None))
                        for row in estimate_rows
                    )
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    universal_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "universal estimate extraction failed for %s: %s",
                        name,
                        exc,
                    )
            if text:
                try:
                    result["metadata"] = _persist_metadata(conn, text, int(procurement_id), name)
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    logger.warning("metadata extraction failed for %s: %s", name, exc)
            if category_code and direct_track:
                persistence = _persist_embedded(
                    conn, path, text, line_meta, int(procurement_id), name,
                    category_code, source_document_id, physical_key, "DIRECT",
                    document_class, allowed_categories,
                )
                result["embedded"] = persistence.persisted_facts
                if persistence.error:
                    conn.rollback()
                try:
                    from document_processor.embedded_persistence import record_outcome

                    record_outcome(
                        conn,
                        source_document_id=source_document_id,
                        procurement_id=int(procurement_id),
                        category_code=category_code,
                        track=track,
                        document_name=name,
                        outcome=persistence.outcome,
                        facts_found=persistence.extracted_facts,
                        reason=persistence.reason("parse_time_hook"),
                        files_parsed=1,
                    )
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    logger.exception(
                        "extraction outcome persistence failed for %s: %s",
                        name,
                        exc,
                    )
            elif universal_attempted and category_code:
                from document_processor.embedded_persistence import (
                    CATEGORY_FACTS_NOT_RESOLVED,
                    FACTS_FOUND,
                    NO_RAW_FACTS,
                    PERSISTENCE_FAILED,
                    UNIVERSAL_ROWS_PERSISTED_NOT_NORMALIZED,
                    record_outcome,
                )

                persisted = int(result.get("estimate_rows") or 0)
                if universal_error:
                    outcome = PERSISTENCE_FAILED
                elif universal_extracted == 0:
                    outcome = NO_RAW_FACTS
                elif persisted == 0:
                    outcome = PERSISTENCE_FAILED
                elif universal_normalized and universal_categorized == 0:
                    outcome = CATEGORY_FACTS_NOT_RESOLVED
                elif universal_normalized:
                    outcome = FACTS_FOUND
                else:
                    outcome = UNIVERSAL_ROWS_PERSISTED_NOT_NORMALIZED
                reason = (
                    "parse_time_universal; "
                    f"extracted={universal_extracted}; "
                    f"goods={universal_goods}; "
                    f"category_resolved={universal_categorized}; "
                    f"persisted={persisted}; "
                    f"full_normalization={'YES' if universal_normalized else 'NO'}"
                )
                if universal_error:
                    reason += f"; error={universal_error}"
                try:
                    record_outcome(
                        conn,
                        source_document_id=source_document_id,
                        procurement_id=int(procurement_id),
                        category_code=category_code,
                        track=track,
                        document_name=name,
                        outcome=outcome,
                        facts_found=universal_extracted,
                        reason=reason,
                        files_parsed=1,
                    )
                except Exception:  # noqa: BLE001
                    conn.rollback()
                    raise
            conn.commit()
        finally:
            conn.close()
        if (
            result["facts"]
            or result["metadata"]
            or result.get("embedded")
            or result.get("estimate_rows")
        ):
            logger.info(
                "parse-time extraction: estimate_rows=%d facts=%d metadata=%d "
                "embedded=%d doc=%s",
                result.get("estimate_rows", 0), result["facts"],
                result["metadata"], result.get("embedded", 0), name,
            )
    except Exception as exc:
        logger.warning("parse-time extraction failed for %s: %s", document_name, exc)
    return result


def _persist_embedded(
    conn,
    path: Path,
    text: Optional[str],
    line_meta: Optional[Dict[int, Any]],
    procurement_id: int,
    document_name: str,
    category_code: str,
    source_document_id: Optional[int],
    physical_key: Optional[str],
    track: Optional[str] = None,
    document_class: Optional[str] = None,
    allowed_categories: Optional[set] = None,
    persist: bool = True,
) -> Any:
    """Run the category-bound extractor during parsing (file still on disk)."""
    extracted_facts = 0
    goods_accepted_facts = 0
    category_resolved_facts = 0
    allowed_rejected_facts = 0
    accepted_facts = 0
    total_created = 0
    total_reused = 0
    try:
        from document_processor.embedded_extraction import extract_facts, facts_from_table_rows
        from document_processor.embedded_persistence import (
            PersistenceResult,
            persist_facts,
        )

        # DIRECT (прямые поставки) uses the previously built template extractor;
        # EMBEDDED (проекты/объекты) uses the table-row extractor.
        if track == "DIRECT":
            from document_processor.direct_runtime import direct_facts

            facts = direct_facts(
                path, procurement_id=procurement_id, category_code=category_code,
                document_name=document_name, source_document_id=source_document_id,
                physical_key=physical_key,
                text=text, line_meta=line_meta,
                document_class=document_class,
            )
            extracted_facts = len(facts)
            goods_accepted_facts = extracted_facts
            category_resolved_facts = extracted_facts
            accepted_facts = len(facts)
            if not facts:
                return PersistenceResult()
            if not persist:
                return PersistenceResult(
                    extracted_facts=extracted_facts,
                    goods_accepted_facts=goods_accepted_facts,
                    category_resolved_facts=category_resolved_facts,
                    accepted_facts=accepted_facts,
                    persistence_attempted=False,
                )
            # DIRECT facts are built from template/table row cells. Their exact
            # row texts are the provenance snapshot used by strict quote checks;
            # the generic parser text can use a different cell layout.
            direct_snapshot = "\n".join(
                str(getattr(f, "source_quote", "") or "") for f in facts
            )
            created, _reused, _stats = persist_facts(
                conn, procurement_id=procurement_id, document_name=document_name,
                category_code=category_code, facts=facts,
                source_text=direct_snapshot,
                source_document_id=source_document_id,
            )
            return PersistenceResult(
                extracted_facts=extracted_facts,
                accepted_facts=accepted_facts,
                created=int(created or 0),
                reused=int(_reused or 0),
            )

        # Bounded work: one pathological workbook must not stall the batch.
        max_xlsx_bytes = int(os.getenv("EMBEDDED_MAX_XLSX_BYTES", str(8 * 1024 * 1024)))
        if path.suffix.lower() in (".xlsx", ".xlsm") and path.stat().st_size > max_xlsx_bytes:
            logger.warning(
                "embedded extraction skipped (xlsx over %d bytes): %s", max_xlsx_bytes, document_name
            )
            return PersistenceResult(error=f"xlsx_over_limit:{path.stat().st_size}")
        snapshot_text = text or ""
        if path.suffix.lower() in (".xlsx", ".xlsm"):
            try:
                from document_processor.smeta_forma_4b import (
                    detect_forma_4b,
                    read_estimate,
                    xlsx_sheet_names,
                )
                from document_processor.xlsx_table_reader import read_tables

                rows = read_estimate(path) if detect_forma_4b(xlsx_sheet_names(path)) else read_tables(path)
            except Exception:
                rows = []
            facts = facts_from_table_rows(
                procurement_id=procurement_id, category_code=category_code,
                document_name=document_name, rows=rows,
                source_document_id=source_document_id, physical_key=physical_key,
            )
            # source_quote для xlsx строится из table rows ("A=… | B=…"),
            # а ExcelParser.parse даёт плоский текст без имён колонок.
            # Snapshot должен содержать ровно ту форму, что и source_quote.
            snapshot_text = "\n".join(
                str(getattr(r, "source_quote", "") or "") for r in rows
            )
        else:
            facts = extract_facts(
                procurement_id=procurement_id, category_code=category_code,
                document_name=document_name, text=text, line_meta=line_meta,
                source_document_id=source_document_id, physical_key=physical_key,
            )
        extracted_facts = len(facts)
        if not facts:
            return PersistenceResult()
        from collections import defaultdict

        from document_processor.goods_fact_gate import is_confident_count_goods

        grouped = defaultdict(list)
        for fact in facts:
            fact_name = (
                getattr(fact, "product_name_raw", "")
                or getattr(fact, "product_name_normalized", "")
                or ""
            )
            resolved = _resolve_embedded_category(fact_name, category_code)
            if not is_confident_count_goods(
                fact, category_code=resolved or category_code
            ):
                continue
            goods_accepted_facts += 1
            if resolved is None:
                continue
            category_resolved_facts += 1
            if allowed_categories is not None and resolved not in allowed_categories:
                allowed_rejected_facts += 1
                continue
            fact.category_code = resolved
            grouped[resolved].append(fact)
        accepted_facts = sum(len(group) for group in grouped.values())
        if not grouped:
            return PersistenceResult(
                extracted_facts=extracted_facts,
                goods_accepted_facts=goods_accepted_facts,
                category_resolved_facts=category_resolved_facts,
                accepted_facts=accepted_facts,
                allowed_rejected_facts=allowed_rejected_facts,
                persistence_attempted=persist,
            )
        if not persist:
            return PersistenceResult(
                extracted_facts=extracted_facts,
                goods_accepted_facts=goods_accepted_facts,
                category_resolved_facts=category_resolved_facts,
                accepted_facts=accepted_facts,
                allowed_rejected_facts=allowed_rejected_facts,
                persistence_attempted=False,
            )
        for resolved_category, group in grouped.items():
            group_snapshot = "\n".join(
                str(getattr(f, "source_quote", "") or "") for f in group
            )
            created, _reused, _stats = persist_facts(
                conn,
                procurement_id=procurement_id,
                document_name=document_name,
                category_code=resolved_category,
                facts=group,
                source_text=group_snapshot,
                source_document_id=source_document_id,
            )
            total_created += int(created or 0)
            total_reused += int(_reused or 0)
        return PersistenceResult(
            extracted_facts=extracted_facts,
            goods_accepted_facts=goods_accepted_facts,
            category_resolved_facts=category_resolved_facts,
            accepted_facts=accepted_facts,
            allowed_rejected_facts=allowed_rejected_facts,
            created=total_created,
            reused=total_reused,
        )
    except Exception as exc:  # keep parsing alive, but expose a failed outcome
        logger.warning("embedded extraction failed for %s: %s", document_name, exc)
        from document_processor.embedded_persistence import PersistenceResult

        return PersistenceResult(
            extracted_facts=extracted_facts,
            goods_accepted_facts=goods_accepted_facts,
            category_resolved_facts=category_resolved_facts,
            accepted_facts=accepted_facts,
            allowed_rejected_facts=allowed_rejected_facts,
            created=total_created,
            reused=total_reused,
            error=f"{type(exc).__name__}: {exc}",
        )
