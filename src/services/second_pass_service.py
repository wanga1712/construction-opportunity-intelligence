"""Second Pass AI service (MEDAL SEMANTICS V2).

Second Pass evaluates CANONICAL CATEGORY RELEVANCE from document evidence and
returns an evidence-bound per-category evaluation. It does NOT decide the
commercial medal: ``relevance_level`` is mapped to a medal deterministically by
application code (``src.services.medal_semantics_v2``), and the overall model
medal is the strongest supported canonical category medal.

Hard rules for ANALYTICS-V2-MEDAL-SEMANTICS-V2-REBUILD-1 (PHASE 6.4):
  * price / NMCK / contract volume never create category relevance;
  * Qwen returns ``relevance_level``, never a free-form commercial medal;
  * a positive category medal requires a canonical category AND evidence;
  * completed analysis without a canonical category => WOOD;
  * analysis not ready => UNASSESSED, never WOOD;
  * every result carries ``semantics_version = 2``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.services.ai_client import generate_with_meta  # noqa: F401  (import compatibility)
from src.services.medal_semantics_v2 import (
    CANONICAL_CATEGORY_CODES,
    MEDAL_SEMANTICS_TAG,
    MEDAL_SEMANTICS_VERSION,
    canonical_category,
    evaluate_category,
    medal_to_relevance,
    relevance_to_medal,
    strongest_category_medal,
)
from src.services.second_pass_prompt_v2 import (
    SECOND_PASS_MODEL,
    SECOND_PASS_PROMPT_VERSION,
    build_second_pass_prompt,
)
from src.services.second_pass_evidence import (  # noqa: F401  (re-export)
    MAX_EVIDENCE_CHARS_PER_SNIPPET,
    MAX_EVIDENCE_SNIPPETS,
    _format_row_data,
    extract_evidence_snippets,
)

logger = logging.getLogger(__name__)

_MEDALS = ("GOLD", "SILVER", "BRONZE", "WOOD")
_SUPPORT_TYPES = {"FACT", "CATEGORY_EVALUATION", "MIXED", "NEGATIVE/EXCLUSION"}
_RELEVANCE_LEVELS = ("STRONG", "MODERATE", "WEAK", "NONE")
#: Relevance levels that may carry a positive commercial medal.
_POSITIVE_LEVELS = ("STRONG", "MODERATE", "WEAK")

#: Diagnostic-only score scale, derived from the final medal. Price never enters.
_DIAGNOSTIC_SCORES = {"GOLD": 85, "SILVER": 65, "BRONZE": 40, "WOOD": 10, "UNASSESSED": 0}

CANONICAL_CATEGORIES = list(CANONICAL_CATEGORY_CODES)

_CATEGORY_ALIASES = {
    "lighting": "lighting", "27.40": "lighting", "b72021": "lighting", "освещение": "lighting", "светильники": "lighting",
    "waterproofing": "waterproofing", "waterproofing_materials": "waterproofing", "гидроизоляция": "waterproofing",
    "flooring": "flooring", "43.34": "flooring", "полы": "flooring", "паркет": "flooring",
    "computers": "computers", "26.20": "computers", "оргтехника": "computers", "компьютеры": "computers",
    "drainage_water_management": "drainage_water_management", "b73004": "drainage_water_management", "водоотведение": "drainage_water_management", "дренаж": "drainage_water_management",
    "bridge_road_infrastructure": "bridge_road_infrastructure", "42.11": "bridge_road_infrastructure", "43.11": "bridge_road_infrastructure", "дороги": "bridge_road_infrastructure", "мосты": "bridge_road_infrastructure",
    "external_utility_networks": "external_utility_networks", "042101": "external_utility_networks", "инженерные сети": "external_utility_networks", "трубопроводы": "external_utility_networks",
    "concrete_materials": "concrete_materials", "41.20": "concrete_materials", "бетон": "concrete_materials",
    "structural_reinforcement": "structural_reinforcement", "43.99": "structural_reinforcement", "усиление": "structural_reinforcement",
    "cable_support_systems": "cable_support_systems", "кабельные трассы": "cable_support_systems",
    "composite_structures": "composite_structures", "composites": "composites", "композиты": "composites",
    "curbstone": "curbstone", "бордюр": "curbstone", "waterproofing_concrete_repair": "waterproofing_concrete_repair",
}


def normalize_category_code(raw_code: Any) -> str:
    """Map a raw, legacy or OKPD-ish code onto a canonical category code."""
    if not raw_code:
        return "other_unmapped"
    c = str(raw_code).strip().lower()
    cat = canonical_category(c)
    if cat:
        return cat
    for alias, mapped in _CATEGORY_ALIASES.items():
        if c == alias or c.startswith(alias) or alias in c:
            return mapped
    return c


def verify_category_semantic_support(category_code: str, evidence_texts: List[str]) -> bool:
    """True when canonical-category vocabulary is genuinely present in evidence."""
    cat = canonical_category(normalize_category_code(category_code))
    if cat is None:
        return False
    text = " ".join(t for t in (evidence_texts or []) if t)
    ev = evaluate_category(cat, text)
    return bool(ev["positive_signals"]) and not ev["negative_signals"]


def compute_hash(text: str) -> str:
    """Return SHA-256 hex digest of text."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def parse_second_pass_json(
    raw_text: str,
    evidence_corpus: str = "",
    *,
    analysis_ready: bool = True,
) -> Dict[str, Any]:
    """Parse Qwen category-relevance JSON and assign medals deterministically.

    MEDAL SEMANTICS V2: Qwen supplies ``relevance_level`` per canonical category;
    this function maps it to a medal, gates it on real evidence, and derives the
    overall model medal as the strongest supported canonical category medal.
    """
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    m = re.search(r"(\{[\s\S]*\})", cleaned)
    candidate = m.group(1).strip() if m else cleaned

    data = None
    try:
        data = json.loads(candidate)
    except Exception:
        for attempt in range(len(candidate), 0, -1):
            sub = candidate[:attempt].rstrip()
            if sub.endswith(","):
                sub = sub[:-1]
            open_braces = sub.count("{") - sub.count("}")
            open_brackets = sub.count("[") - sub.count("]")
            repaired = sub + ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
            try:
                data = json.loads(repaired)
                break
            except Exception:
                continue

    if not isinstance(data, dict):
        data = {
            "object_classification": {"object_family": "OTHER", "object_type": "Не определен"},
            "category_evaluations": [],
            "commercial_exclusions": [],
            "found_facts": [],
            "model_reason": "Structured JSON not recovered from model output",
        }

    corpus = evidence_corpus or ""
    corpus_lower = corpus.lower()

    raw_medal = str(data.get("model_medal") or "").upper()
    raw_suggestion = {
        "medal": raw_medal if raw_medal in _MEDALS else None,
        "score": data.get("model_score"),
        "reason": str(data.get("model_reason") or ""),
        "authoritative": False,
    }

    # ── found_facts: strict evidence grounding (UNSUPPORTED_FINDINGS = 0) ──────
    valid_facts: List[Dict[str, Any]] = []
    for f in data.get("found_facts", []) or []:
        if not isinstance(f, dict):
            continue
        pname = str(f.get("product_name_normalized") or "").strip()
        doc_name = str(f.get("document_name") or "").strip()
        quote = str(f.get("source_quote") or "").strip()
        if not pname or pname.lower() in ("null", "none", "не определено"):
            continue
        if not doc_name or doc_name.lower() in ("null", "none"):
            doc_name = "Документация"
        if corpus_lower:
            is_supported = (
                (quote and quote.lower() in corpus_lower)
                or (pname and pname.lower() in corpus_lower)
                or any(w in corpus_lower for w in pname.lower().split() if len(w) > 3)
            )
            if not is_supported:
                continue
        f["product_name_normalized"] = pname
        f["document_name"] = doc_name
        f["category_code"] = normalize_category_code(f.get("category_code"))
        f["support_type"] = "NORMALIZED" if str(f.get("support_type", "")).upper() == "NORMALIZED" else "EXACT"
        valid_facts.append(f)
    data["found_facts"] = valid_facts

    # ── category evaluations: canonical category + evidence + semantics ───────
    raw_cat_evals = data.get("category_evaluations")
    if not isinstance(raw_cat_evals, list):
        raw_cat_evals = []

    validated: List[Dict[str, Any]] = []
    for c in raw_cat_evals:
        if not isinstance(c, dict):
            continue
        # A medal without a canonical category is forbidden (PRELIM/MODEL parity).
        cat = canonical_category(normalize_category_code(c.get("category_code")))
        if cat is None:
            continue

        rel = str(c.get("relevance_level") or "").strip().upper()
        if rel not in _RELEVANCE_LEVELS:
            rel = medal_to_relevance(str(c.get("category_model_medal") or "").upper())
        if rel not in _RELEVANCE_LEVELS:
            rel = "NONE"

        refs: List[Dict[str, str]] = []
        for r in (c.get("evidence_refs") or c.get("category_evidence_refs") or []):
            if not isinstance(r, dict):
                continue
            refs.append({
                "document_name": str(r.get("document_name") or "").strip(),
                "matched_term": str(r.get("matched_term") or "").strip(),
                "location": str(r.get("location") or "").strip(),
                "quote": str(r.get("quote") or r.get("source_quote") or "").strip(),
            })
        doc_source = any(r["document_name"] for r in refs)
        cat_facts = [f for f in valid_facts if f.get("category_code") == cat]

        support_text = " ".join(
            [corpus]
            + [f"{r['matched_term']} {r['quote']}" for r in refs]
            + [f"{f.get('product_name_normalized', '')} {f.get('source_quote', '')}" for f in cat_facts]
        )
        ev = evaluate_category(cat, support_text)
        code_pos = list(ev["positive_signals"])
        code_neg = list(ev["negative_signals"])

        downgrade = None
        if rel in _POSITIVE_LEVELS:
            if not (doc_source and (refs or cat_facts)):
                rel, downgrade = "NONE", "POSITIVE_WITHOUT_EVIDENCE"
            elif not code_pos:
                rel, downgrade = "NONE", "POSITIVE_WITHOUT_SEMANTIC_SUPPORT"
            elif code_neg and rel in ("STRONG", "MODERATE"):
                rel, downgrade = "WEAK", "NEGATIVE_CONTEXT_CAP"

        medal = relevance_to_medal(rel)  # STRONG->GOLD, MODERATE->SILVER, WEAK->BRONZE, NONE->WOOD
        evidence_supported = bool(
            rel in _POSITIVE_LEVELS and doc_source and (refs or cat_facts) and code_pos
        )

        pos_merged = list(dict.fromkeys([str(s) for s in (c.get("positive_signals") or []) if s] + code_pos))
        neg_merged = list(dict.fromkeys([str(s) for s in (c.get("negative_signals") or []) if s] + code_neg))
        findings = [str(x) for x in (c.get("findings") or []) if x]

        validated.append({
            "category_code": cat,
            "relevance_level": rel,
            "relevance_medal": medal,
            "category_model_medal": medal,  # backwards-compatible reader key
            "category_model_score": _DIAGNOSTIC_SCORES.get(medal, 10),
            "reason": str(c.get("reason") or c.get("category_reason") or c.get("evidence_summary") or ""),
            "findings": findings,
            "evidence_refs": refs,
            "positive_signals": pos_merged,
            "negative_signals": neg_merged,
            "commercial_exclusions": c.get("commercial_exclusions") or [],
            "evidence_supported": evidence_supported,
            "findings_count": len(cat_facts),
            "evidence_ref_count": len(refs),
            "downgrade_reason": downgrade,
        })
    data["category_evaluations"] = validated

    # ── overall model medal = strongest supported canonical category medal ────
    overall = strongest_category_medal(validated, require_evidence=True)
    if not analysis_ready:
        model_medal: Optional[str] = None
        model_state = "UNASSESSED"
    else:
        model_medal = overall or "WOOD"
        model_state = "ASSESSED"
    data["model_medal"] = model_medal
    data["model_state"] = model_state
    data["model_score"] = _DIAGNOSTIC_SCORES.get(model_medal or "UNASSESSED", 0)

    if model_medal is None:
        supp = "CATEGORY_EVALUATION"
    elif model_medal == "WOOD":
        supp = "NEGATIVE/EXCLUSION"
    elif valid_facts and validated:
        supp = "MIXED"
    elif valid_facts:
        supp = "FACT"
    else:
        supp = "CATEGORY_EVALUATION"
    data["medal_support_type"] = supp

    data["raw_model_suggestion"] = raw_suggestion
    data["price_used_for_medal"] = False
    data["semantics_version"] = MEDAL_SEMANTICS_VERSION
    data["semantics_tag"] = MEDAL_SEMANTICS_TAG
    data["model_name"] = SECOND_PASS_MODEL
    data["prompt_version"] = SECOND_PASS_PROMPT_VERSION
    return data


def persist_second_pass(crm_conn, procurement_id: int, prompt: str, raw_text: str, parsed: Dict[str, Any], meta: Dict[str, Any]) -> int:
    """Persist a semantics-v2 Second Pass result (run + current assessment + facts)."""
    prompt_h = compute_hash(prompt)
    raw_h = compute_hash(raw_text)

    run_meta = dict(meta or {})
    run_meta["medal_semantics_version"] = MEDAL_SEMANTICS_VERSION
    run_meta["semantics_tag"] = MEDAL_SEMANTICS_TAG
    run_meta["prompt_version"] = SECOND_PASS_PROMPT_VERSION
    run_meta["model_name"] = SECOND_PASS_MODEL
    run_meta["price_used_for_medal"] = False

    medal = parsed.get("model_medal") or "UNASSESSED"
    diagnostic_score = float(parsed.get("model_score") or 0)

    with crm_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO crm_v3_model_inference_runs (
                procurement_id, run_kind, model_name, model_version, prompt_version,
                schema_version, prompt_hash, raw_model_text, raw_model_sha256,
                raw_model_json, parse_status, validated_model_result,
                validated_model_sha256, validation_status, validation_errors,
                ollama_metadata, retry_count, run_status
            ) VALUES (
                %s, 'PRODUCTION', %s, 'v3', %s,
                '1.0', %s, %s, %s,
                %s, 'PARSED_OK', %s,
                %s, 'VALIDATED_SUCCESS', '[]'::jsonb,
                %s, 0, 'COMPLETED'
            ) RETURNING id
            """,
            (
                procurement_id,
                SECOND_PASS_MODEL,
                SECOND_PASS_PROMPT_VERSION,
                prompt_h,
                raw_text,
                raw_h,
                json.dumps(parsed),
                json.dumps(parsed),
                compute_hash(json.dumps(parsed)),
                json.dumps(run_meta),
            ),
        )
        run_id = cur.fetchone()[0]

        cur.execute("UPDATE procurement_ai_assessments SET is_current = FALSE WHERE procurement_id = %s", (procurement_id,))
        cur.execute("SELECT COALESCE(MAX(assessment_version), 0) + 1 FROM procurement_ai_assessments WHERE procurement_id = %s", (procurement_id,))
        next_ver = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO procurement_ai_assessments (
                authoritative_id, procurement_id, assessment_version, is_current,
                status, input_fingerprint, model_version, prompt_version,
                rules_version, proposed_object_type, proposed_level,
                confidence, reasons, normalized_result, inference_run_id
            ) VALUES (
                %s, %s, %s, TRUE,
                'SUCCESS', %s, %s, %s,
                3, %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                procurement_id,
                procurement_id,
                next_ver,
                prompt_h,
                SECOND_PASS_MODEL,
                SECOND_PASS_PROMPT_VERSION,
                parsed.get("object_classification", {}).get("object_type", ""),
                medal,
                min(1.0, max(0.0, diagnostic_score / 100.0)),
                parsed.get("model_reason", ""),
                json.dumps(parsed),
                run_id,
            ),
        )

        for fact in parsed.get("found_facts", []):
            qty_val = None
            try:
                if fact.get("quantity"):
                    qty_val = float(str(fact.get("quantity")).replace(",", ".").replace(" ", ""))
            except Exception:
                pass
            cur.execute(
                """
                INSERT INTO crm_v3_product_findings (
                    procurement_id, model_run_id, category_code,
                    product_name_normalized,
                    quantity, unit, unit_price, total_price,
                    document_name, evidence_text, extraction_confidence
                ) VALUES (
                    %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    procurement_id,
                    run_id,
                    fact.get("category_code"),
                    fact.get("product_name_normalized"),
                    qty_val,
                    fact.get("unit"),
                    fact.get("unit_price"),
                    fact.get("total_price") if isinstance(fact.get("total_price"), (int, float)) else None,
                    fact.get("document_name"),
                    fact.get("source_quote"),
                    diagnostic_score,
                ),
            )
        crm_conn.commit()
    return run_id
