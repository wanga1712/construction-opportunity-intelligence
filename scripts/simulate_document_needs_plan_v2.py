#!/usr/bin/env python3
"""Read-only RESEARCH_ACTION_V2 + DOCUMENT_NEEDS_PLAN_V2 simulation.

PRODUCTION_WRITES=0, QUEUE_WRITES=0, HTTP_REQUESTS=0, DOCUMENT_DOWNLOADS=0.

For every CURRENT category opportunity:
  opportunity? -> documents needed? -> which facts? -> which classes?
and for sampled procurements: which concrete source files are SELECTED /
SKIPPED_NOT_RELEVANT / UNKNOWN_NEEDS_REVIEW, plus the HTTP simulation,
recall audit, routing and reuse simulation.
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.services.commercial_routing_v3.document_classifier_v1 import (  # noqa: E402
    DOCUMENT_CLASSIFIER_VERSION,
    DocumentClass,
    classify_document_metadata,
)
from src.services.commercial_routing_v3.document_needs_plan_v2 import (  # noqa: E402
    DOCUMENT_NEEDS_POLICY_VERSION,
    DOCUMENT_SELECTION_POLICY_VERSION,
    FALLBACK_MAX_PER_UNIT,
    SELECTED_FALLBACK,
    SELECTED,
    SKIPPED_NOT_RELEVANT,
    UNKNOWN_NEEDS_REVIEW,
    adapt_category_registry,
    build_document_needs_plan,
    category_plan,
    select_unit_documents,
)
from src.services.commercial_routing_v3.research_action_v2 import (  # noqa: E402
    RESEARCH_ACTION_POLICY_VERSION,
    GROUP_DIRECT,
    GROUP_EMBEDDED,
    ResearchAction,
    decide_research_action,
    track_group,
)

SAMPLE_BUCKETS: Tuple[Tuple[str, str, int], ...] = (
    (GROUP_DIRECT, "computers", 10),
    (GROUP_DIRECT, "lighting", 10),
    (GROUP_EMBEDDED, "lighting", 10),
    (GROUP_EMBEDDED, "waterproofing", 5),
    (GROUP_EMBEDDED, "flooring", 5),
    (GROUP_EMBEDDED, "composite_structures", 5),
    (GROUP_EMBEDDED, "drainage_water_management", 5),
    (GROUP_EMBEDDED, "curbstone", 5),
)
MAX_MULTI_CATEGORY_PIDS = 10
TRACE_PIDS = 6

#: (category, document_class) -> parser route, normalizer route.
ROUTES: Dict[DocumentClass, Tuple[Optional[str], Optional[str]]] = {
    DocumentClass.ESTIMATE: (
        "parsers.ExcelParser + xlsx_table_reader",
        "parse_extractors.extract_and_persist (embedded_category_facts)",
    ),
    DocumentClass.BOQ: (
        "parsers.ExcelParser + xlsx_table_reader",
        "parse_extractors.extract_and_persist (work_volume/quantity/unit)",
    ),
    DocumentClass.MATERIAL_SPECIFICATION: (
        "parsers.ExcelParser / parsers.WordParser",
        "structured_fact_extractor (material_facts)",
    ),
    DocumentClass.PRODUCT_SPECIFICATION: (
        "parsers.WordParser / parsers.ExcelParser / parsers.PdfParser",
        "structured_fact_extractor (product_facts)",
    ),
    DocumentClass.TECH_SPEC: (
        "parsers.WordParser / parsers.PdfParser",
        "structured_fact_extractor (product_facts/delivery)",
    ),
    DocumentClass.PROJECT_DOCUMENTATION: (
        "parsers.PdfParser / archive_extractor -> match_engine.MatchEngine",
        "matcher.MatchEngine (section/embedded facts)",
    ),
    DocumentClass.WORKING_DOCUMENTATION: (
        "parsers.PdfParser / archive_extractor -> match_engine.MatchEngine",
        "matcher.MatchEngine (section/embedded facts)",
    ),
    DocumentClass.CONTRACT_PROJECT: (
        "parsers.WordParser / parsers.PdfParser",
        "contract_classifier + structured_fact_extractor (delivery/contract terms)",
    ),
    DocumentClass.NMCK_JUSTIFICATION: (
        "parsers.ExcelParser",
        "parse_estimate_corpus (nmck/price facts)",
    ),
    # Fallback classes ride the generic pipeline: generic parser by extension and
    # the generic category keyword/section matcher (this is exactly how the
    # historical positive matches in these files were produced).
    DocumentClass.PARTICIPANT_REQUIREMENTS: (
        "parsers.WordParser / parsers.PdfParser (generic)",
        "matcher.MatchEngine (generic category keyword matcher)",
    ),
    DocumentClass.SECURITY_REQUIREMENTS: (
        "parsers.WordParser / parsers.PdfParser (generic)",
        "matcher.MatchEngine (generic category keyword matcher)",
    ),
    DocumentClass.LEGAL_GENERAL: (
        "parsers.WordParser / parsers.PdfParser (generic)",
        "matcher.MatchEngine (generic category keyword matcher)",
    ),
    DocumentClass.OTHER: (
        "parsers.* by extension + archive_extractor (generic)",
        "matcher.MatchEngine (generic category keyword matcher)",
    ),
}


def crm_dsn() -> dict:
    return {
        "host": os.getenv("CRM_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("CRM_DB_PORT", "5432")),
        "dbname": os.getenv("CRM_DB_DATABASE") or os.getenv("CRM_DB_NAME") or "crm",
        "user": os.getenv("CRM_DB_USER", "crm_app"),
        "password": os.getenv("CRM_DB_PASSWORD", ""),
    }


def di_dsn() -> dict:
    return {
        "host": os.getenv("S13_DOCUMENT_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("S13_DOCUMENT_DB_PORT", "5432")),
        "dbname": os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence"),
        "user": os.getenv("S13_DOCUMENT_DB_USER", "doc_worker"),
        "password": os.getenv("S13_DOCUMENT_DB_PASSWORD", ""),
    }


def query(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


REGISTRY_SQL = """
SELECT category_code, category_name, default_role, applicable_routes,
       document_search_plan, section_search_plan, extraction_fields
  FROM crm_product_categories
 WHERE is_active
 ORDER BY sort_order, category_code
"""

CURRENT_SQL = """
SELECT o.procurement_id, o.commercial_category_code AS category_code,
       o.opportunity_track, o.commercial_state, o.commercial_priority_score,
       o.candidate_initial_medal, o.expected_category_value, o.category_value_basis,
       o.research_action, p.auction_name, p.okpd_code, p.initial_price,
       p.final_contract_price, p.start_date, p.end_date, p.source_status
  FROM crm_procurement_category_opportunities o
  JOIN crm_procurements p ON p.id = o.procurement_id
 WHERE o.status = 'CURRENT'
 ORDER BY o.procurement_id, o.commercial_category_code
"""

EVIDENCE_PAIR_SQL = """
SELECT DISTINCT m.procurement_id, d.category_code
  FROM document_match_details d
  JOIN document_matches m ON m.id = d.match_id
"""

KNOWN_POSITIVE_SQL = """
SELECT DISTINCT m.procurement_id, d.category_code, m.document_name
  FROM document_match_details d
  JOIN document_matches m ON m.id = d.match_id
 WHERE m.document_name IS NOT NULL
"""

ARTIFACT_SQL = """
SELECT procurement_id,
       count(*) FILTER (WHERE download_status = 'COMPLETED') AS completed,
       count(*) FILTER (
           WHERE download_status = 'COMPLETED'
             AND local_path IS NOT NULL AND local_deleted_at IS NULL
       ) AS local_present
  FROM document_files
 GROUP BY 1
"""

DOCS_SQL = """
SELECT id, procurement_id, source_table, source_id, url, url_hash, file_name,
       physical_download_key, download_status, pipeline_generation,
       (local_path IS NOT NULL AND local_deleted_at IS NULL) AS has_local_file
  FROM document_files
 WHERE procurement_id = ANY(%s)
"""


def physical_key(row: Dict[str, Any]) -> str:
    return (
        row.get("physical_download_key")
        or row.get("url_hash")
        or (row.get("url") or "").strip().lower()
        or (row.get("file_name") or "").strip().lower()
        or f"row:{row.get('id')}"
    )


STATUS_RANK = {"COMPLETED": 0, "PENDING": 1, "FAILED": 2, "SKIPPED": 3}


def dedupe_source_documents(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = physical_key(row)
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        score = (STATUS_RANK.get(row.get("download_status"), 9), 0 if row.get("has_local_file") else 1)
        cur_score = (
            STATUS_RANK.get(current.get("download_status"), 9),
            0 if current.get("has_local_file") else 1,
        )
        if score < cur_score:
            best[key] = row
    return list(best.values())


def dedupe_by_file_name(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The selection decision is a function of the file name.

    The same file reached through several source links must not be counted as
    several potential requests for the same decision.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = (row.get("file_name") or "").strip().lower() or physical_key(row)
        current = best.get(key)
        if current is None or STATUS_RANK.get(row.get("download_status"), 9) < STATUS_RANK.get(
            current.get("download_status"), 9
        ):
            best[key] = row
    return list(best.values())


def build_asset_index(docs: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    index: Dict[int, Dict[str, Any]] = {}
    for row in docs:
        pid = row["procurement_id"]
        entry = index.setdefault(pid, {"completed": 0, "local_present": 0})
        if row.get("download_status") == "COMPLETED":
            entry["completed"] += 1
            if row.get("has_local_file"):
                entry["local_present"] += 1
    return index


def reuse_class(doc: Dict[str, Any], has_match: bool) -> str:
    if doc.get("download_status") == "COMPLETED" and doc.get("has_local_file"):
        return "REUSE_NO_HTTP"
    if has_match:
        return "REPROCESS_NO_HTTP"
    return "NEW_DOWNLOAD_REQUIRED"


def main() -> int:
    crm = psycopg2.connect(**crm_dsn())
    di = psycopg2.connect(**di_dsn())
    try:
        registry_rows = query(crm, REGISTRY_SQL)
        opportunities = query(crm, CURRENT_SQL)
        asset_index = {int(r["procurement_id"]): dict(r) for r in query(di, ARTIFACT_SQL)}
        evidence_pairs = {(int(r["procurement_id"]), r["category_code"]) for r in query(di, EVIDENCE_PAIR_SQL)}
        known_positives = query(di, KNOWN_POSITIVE_SQL)
        adapted, adapter_report = adapt_category_registry(registry_rows)

        print("=" * 78)
        print("PHASE 6 - CATEGORY REGISTRY ADAPTER (existing registry -> V2)")
        print(f"CATEGORY_REGISTRY_ROWS={adapter_report.registry_rows}")
        print(f"MAPPED_TO_V2={adapter_report.mapped_to_v2}")
        print(f"UNMAPPED={len(adapter_report.unmapped)}")
        print(f"AMBIGUOUS={len(adapter_report.ambiguous)}")
        print(f"UNMAPPED_DETAIL={sorted(set(adapter_report.unmapped))}")
        print(f"AMBIGUOUS_DETAIL={sorted(set(adapter_report.ambiguous))}")

        # ---------------------------------------------------- Phase 1-3 actions
        groups_by_category: Dict[str, set] = defaultdict(set)
        decisions = []
        action_counts = Counter()
        reason_counts = Counter()
        per_category = defaultdict(Counter)
        for opp in opportunities:
            group = track_group(opp["opportunity_track"])
            category = opp["category_code"]
            groups_by_category[category].add(group)
            pid = opp["procurement_id"]
            assets = asset_index.get(pid, {})
            has_evidence = (pid, category) in evidence_pairs
            decision = decide_research_action(
                category_code=category,
                opportunity_track=opp["opportunity_track"],
                commercial_state=opp["commercial_state"],
                candidate_medal=opp["candidate_initial_medal"],
                has_confirmed_facts=has_evidence,
                has_reusable_artifacts=bool(assets.get("local_present")),
                window_closed=(opp["commercial_state"] or "").upper()
                in {"CLOSED", "ARCHIVED", "FOLLOW_UP_AWARDED"},
            )
            record = {"opp": opp, "group": group, "decision": decision}
            decisions.append(record)
            action_counts[decision.action.value] += 1
            reason_counts[decision.reason] += 1
            per_category[category][decision.action.value] += 1

        print("=" * 78)
        print("PHASE 1/13 - RESEARCH_ACTION_V2 + CATEGORY PLAN COVERAGE")
        print(f"CURRENT_OPPORTUNITIES={len(opportunities)}")
        print(f"CURRENT_CATEGORIES_TOTAL={len(groups_by_category)}")
        for name in ("NO_OPPORTUNITY", "NO_DOCUMENT_RESEARCH",
                     "DOCUMENT_RESEARCH_REQUIRED", "DOCUMENT_CONFIRMATION_REQUIRED"):
            print(f"ACTION_{name}={action_counts.get(name, 0)}")
        print(f"TOP_REASONS={reason_counts.most_common(8)}")

        planned_categories = 0
        unexplained = []
        for category, groups in sorted(groups_by_category.items()):
            plans = [category_plan(category, g) for g in sorted(groups)]
            has_plan = any(p.required_classes for p in plans)
            if has_plan:
                planned_categories += 1
            else:
                unexplained.append(category)
            source = ",".join(sorted({p.source for p in plans}))
            union_facts = sorted({f.value for p in plans for f in p.required_facts})
            union_classes = sorted({c.value for p in plans for c in p.required_classes})
            print(
                f"CATEGORY_PLAN {category}: current={sum(per_category[category].values())} "
                f"groups={','.join(sorted(groups))} facts={len(union_facts)} "
                f"classes_union={','.join(union_classes)} source={source}"
            )
            for plan in plans:
                print(
                    f"  PLAN {plan.track_group}: classes="
                    f"{','.join(c.value for c in plan.required_classes) or '-'} "
                    f"optional={','.join(c.value for c in plan.optional_classes) or '-'}"
                )
            print(f"  ACTIONS={dict(per_category[category])}")
        coverage = 100.0 * planned_categories / max(len(groups_by_category), 1)
        print(f"CURRENT_CATEGORY_PLAN_COVERAGE={coverage:.1f}%")
        print(f"UNEXPLAINED_NO_PLAN={unexplained}")

        # ------------------------------------------------------- Phase 14 sample
        docs_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        opps_by_pid: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for opp in opportunities:
            opps_by_pid[opp["procurement_id"]].append(opp)

        def docs_present(pid: int) -> int:
            return asset_index.get(pid, {}).get("completed", 0) or 0

        sampled: List[int] = []
        sample_notes = []
        for group, category, want in SAMPLE_BUCKETS:
            candidates = sorted(
                {
                    r["opp"]["procurement_id"]
                    for r in decisions
                    if r["group"] == group and r["opp"]["category_code"] == category
                },
                key=lambda pid: (-docs_present(pid), pid),
            )
            take = candidates[:want]
            sample_notes.append((group, category, want, len(candidates), len(take)))
            sampled.extend(take)

        multi_candidates = sorted(
            {
                pid
                for pid, items in opps_by_pid.items()
                if len({i["category_code"] for i in items}) > 1
            }
            - set(sampled),
            key=lambda pid: (-docs_present(pid), pid),
        )[:MAX_MULTI_CATEGORY_PIDS]

        all_pids = sampled + multi_candidates
        all_docs = query(di, DOCS_SQL, (all_pids,)) if all_pids else []
        for row in all_docs:
            docs_by_pid[row["procurement_id"]].append(row)

        print("=" * 78)
        print("PHASE 14 - SAMPLE (policy: source docs present first, then pid asc)")
        for group, category, want, available, taken in sample_notes:
            print(f"SAMPLE {group}/{category}: want={want} available={available} taken={taken}")
        print(f"MULTI_CATEGORY_PIDS={len(multi_candidates)}")
        print(f"SAMPLED_PROCUREMENTS={len(sampled)}")
        print(f"SCANNED_PROCUREMENTS_TOTAL={len(all_pids)}")

        # --------------------------------------------------- Phases 7-10 selection
        sel_counts = Counter()
        class_counts = Counter()
        skipped_reasons = Counter()
        unknown_reasons = Counter()
        per_track = defaultdict(Counter)
        http_before = 0
        http_after_selected = 0
        http_after_fallback = 0
        physical_keys_total = 0
        file_name_total = 0
        reuse_counts = Counter()
        route_counts = Counter()
        samples_for_trace = []
        invariant_violations = 0
        selected_docs = []
        multi_category_plans = {}
        unknown_unknown = 0
        unknown_when_required = 0
        same_url_multi_name = 0
        fallback_units = 0
        accepted_units = 0
        fallback_violations = 0
        fallback_reasons = Counter()

        for pid in all_pids:
            opps = opps_by_pid.get(pid, [])
            units: Dict[str, set] = defaultdict(set)
            for o in opps:
                units[o["category_code"]].add(track_group(o["opportunity_track"]))
            if len(units) > 1:
                multi_category_plans[pid] = build_document_needs_plan(
                    pid,
                    [
                        category_plan(category, group)
                        for category in sorted(units)
                        for group in sorted(units[category])
                    ],
                )
            docs = dedupe_source_documents(docs_by_pid.get(pid, []))
            physical_keys_total += len(docs)
            docs = dedupe_by_file_name(docs)
            file_name_total += len(docs)
            http_before += len(docs)
            names_by_url = defaultdict(set)
            for doc in docs:
                names_by_url[doc.get("url_hash") or doc.get("url")].add(
                    (doc.get("file_name") or "").lower()
                )
            same_url_multi_name += sum(1 for names in names_by_url.values() if len(names) > 1)
            has_match = any((pid, o["category_code"]) in evidence_pairs for o in opps)
            classified = [
                (
                    doc,
                    classify_document_metadata(
                        doc.get("file_name"), source_table=doc.get("source_table")
                    ),
                )
                for doc in docs
            ]
            items = [
                (doc.get("source_id"), doc.get("file_name") or "", classification)
                for doc, classification in classified
            ]

            unit_plans: Dict[str, Any] = {}
            unit_selections: Dict[str, list] = {}
            for category in sorted(units):
                unit_plan = build_document_needs_plan(
                    pid, [category_plan(category, g) for g in sorted(units[category])]
                )
                unit_plans[category] = unit_plan
                selections, promoted = select_unit_documents(
                    unit_plan, procurement_id=pid, category_code=category, documents=items
                )
                unit_selections[category] = selections
                if promoted is not None:
                    fallback_units += 1
                    fallback_reasons[
                        promoted.selection_reason.split(":")[0] + ":" + promoted.document_class.value
                    ] += 1
                    if any(s.selection_decision == SELECTED for s in selections):
                        fallback_violations += 1
                else:
                    accepted_units += 1

            for category, selections in unit_selections.items():
                unit_required = set(unit_plans[category].required_classes)
                for selection in selections:
                    if (
                        selection.selection_decision == SELECTED
                        and selection.document_class not in unit_required
                    ):
                        invariant_violations += 1

            decision_rank = {
                SELECTED: 0,
                SELECTED_FALLBACK: 1,
                UNKNOWN_NEEDS_REVIEW: 2,
                SKIPPED_NOT_RELEVANT: 3,
            }
            best: Dict[str, str] = {}
            best_class: Dict[str, str] = {}
            best_reason: Dict[str, str] = {}
            doc_by_key: Dict[str, Any] = {}
            for category in sorted(units):
                for (doc, _classification), selection in zip(
                    classified, unit_selections[category]
                ):
                    key = (doc.get("file_name") or "").strip().lower()
                    doc_by_key[key] = doc
                    if key not in best or decision_rank[selection.selection_decision] < decision_rank[best[key]]:
                        best[key] = selection.selection_decision
                        best_class[key] = selection.document_class.value
                        best_reason[key] = selection.selection_reason
            per_pid_selected = 0
            per_pid_fallback = 0
            per_pid_unknown = 0
            for key, decision in best.items():
                doc = doc_by_key[key]
                class_counts[best_class[key]] += 1
                if decision == SELECTED:
                    per_pid_selected += 1
                elif decision == SELECTED_FALLBACK:
                    per_pid_fallback += 1
                elif decision == UNKNOWN_NEEDS_REVIEW:
                    per_pid_unknown += 1
                    unknown_reasons[best_reason[key].split(":")[1] if ":" in best_reason[key] else best_reason[key]] += 1
                else:
                    skipped_reasons[best_reason[key].split(":")[0]] += 1
                if decision in (SELECTED, SELECTED_FALLBACK):
                    sel_counts[decision] += 1
                    reuse_key = reuse_class(doc, has_match)
                    reuse_counts[reuse_key] += 1
                    document_class = DocumentClass(best_class[key])
                    parser_route, normalizer_route = ROUTES.get(document_class, (None, None))
                    route_counts[
                        ("PARSER_OK" if parser_route else "PARSER_GAP", document_class.value)
                    ] += 1
                    route_counts[
                        ("NORMALIZER_OK" if normalizer_route else "NORMALIZER_GAP", document_class.value)
                    ] += 1
                    selected_docs.append((pid, document_class.value, reuse_key))
                else:
                    sel_counts[decision] += 1
                if decision == SELECTED:
                    http_after_selected += 1
                    http_after_fallback += 1
                elif decision == SELECTED_FALLBACK:
                    http_after_fallback += 1
            http_after_fallback += per_pid_unknown
            unknown_unknown += per_pid_unknown
            if per_pid_unknown and (per_pid_selected or per_pid_fallback):
                unknown_when_required += per_pid_unknown
            for group in {track_group(o["opportunity_track"]) for o in opps}:
                per_track[group]["PROCUREMENTS"] += 1
                per_track[group]["DOCS"] += len(docs)
                per_track[group]["SELECTED"] += per_pid_selected
                per_track[group]["SELECTED_FALLBACK"] += per_pid_fallback
                per_track[group]["UNKNOWN"] += per_pid_unknown
            if len(samples_for_trace) < 40 and docs:
                samples_for_trace.append((pid, opps, unit_plans, unit_selections, classified))

        # Prefer one multi-category procurement in the trace (Phase 12 evidence).
        multi_trace = [s for s in samples_for_trace if len(s[3]) > 1]
        single_trace = [s for s in samples_for_trace if len(s[3]) == 1]
        samples_for_trace = (multi_trace[:1] + single_trace)[:TRACE_PIDS]

        print("=" * 78)
        print("PHASE 15 - PROCUREMENT TRACES")
        for pid, opps, unit_plans, unit_selections, classified in samples_for_trace:
            print(f"PROCUREMENT_ID={pid}")
            for o in opps:
                print(
                    f"  CURRENT_CATEGORY={o['category_code']} TRACK={o['opportunity_track']} "
                    f"STATE={o['commercial_state']} MEDAL={o['candidate_initial_medal']} "
                    f"START={o['start_date']} END={o['end_date']}"
                )
            for category in sorted(unit_selections):
                plan = unit_plans[category]
                selections = unit_selections[category]
                print(f"  UNIT={category}")
                print(f"    REQUIRED_FACTS={','.join(f.value for f in plan.required_facts)}")
                print(f"    REQUIRED_CLASSES={','.join(c.value for c in plan.required_classes)}")
                print(f"    OPTIONAL_CLASSES={','.join(c.value for c in plan.optional_classes) or '-'}")
                for (doc, _classification), selection in list(zip(classified, selections))[:12]:
                    print(
                        f"    FILE={(doc.get('file_name') or '')[:66]!r} "
                        f"CLASS={selection.document_class.value} "
                        f"DECISION={selection.selection_decision} "
                        f"REASON={selection.selection_reason[:52]}"
                    )
            print(
                f"  POTENTIAL_HTTP_BEFORE={len(classified)} "
                f"AFTER_SELECTED={sum(1 for s in unit_selections.get(sorted(unit_selections)[0], []) if s.selection_decision == SELECTED)}"
            )

        print("=" * 78)
        print("PHASE 16 - AGGREGATE HTTP SIMULATION (document_selection_v2)")
        print("DEDUPE_LEVEL=DISTINCT_FILE_NAME_PER_PROCUREMENT")
        print(f"DISTINCT_PHYSICAL_KEYS={physical_keys_total}")
        print(f"DISTINCT_FILE_NAMES={file_name_total}")
        print(f"SOURCE_DOCUMENTS_TOTAL={sel_counts.total()}")
        print(f"SELECTED={sel_counts.get(SELECTED, 0)}")
        print(f"SELECTED_FALLBACK={sel_counts.get(SELECTED_FALLBACK, 0)}")
        print(f"SKIPPED_NOT_RELEVANT={sel_counts.get(SKIPPED_NOT_RELEVANT, 0)}")
        print(f"UNKNOWN_NEEDS_REVIEW={sel_counts.get(UNKNOWN_NEEDS_REVIEW, 0)}")
        print(f"UNITS_WITH_ACCEPTED_DOC={accepted_units}")
        print(f"UNITS_USING_FALLBACK={fallback_units}")
        print(f"FALLBACK_MAX_PER_PROCUREMENT_CATEGORY={FALLBACK_MAX_PER_UNIT}")
        print(
            "FALLBACK_SELECTED_ONLY_WHEN_NO_ACCEPTED_DOC="
            f"{'YES' if fallback_violations == 0 else 'NO'}"
        )
        print(f"FALLBACK_VIOLATIONS={fallback_violations}")
        print(f"FALLBACK_REASONS={fallback_reasons.most_common(8)}")
        print(f"HTTP_BEFORE={http_before}")
        print(f"HTTP_AFTER_SELECTED={http_after_selected}")
        http_after_v2 = sel_counts.get(SELECTED, 0) + sel_counts.get(SELECTED_FALLBACK, 0)
        print(f"HTTP_AFTER_V2={http_after_v2}")
        print(f"HTTP_AFTER_V2_WITH_UNKNOWN={http_after_fallback}")
        if http_before:
            print(f"HTTP_REDUCTION_PCT={100.0 * (1 - http_after_v2 / http_before):.1f}")
            print(
                "HTTP_REDUCTION_PCT_WITH_UNKNOWN="
                f"{100.0 * (1 - http_after_fallback / http_before):.1f}"
            )
        print(f"TOP_SKIPPED_REASONS={skipped_reasons.most_common(6)}")
        print(f"TOP_UNKNOWN_REASONS={unknown_reasons.most_common(6)}")
        print(f"DOCUMENT_CLASSES={class_counts.most_common()}")
        print(f"UNKNOWN_TOTAL={unknown_unknown} UNKNOWN_WHEN_REQUIRED_FOUND={unknown_when_required}")
        print(f"SAME_URL_MULTIPLE_FILENAMES={same_url_multi_name}")
        print(f"SELECTION_INVARIANT_VIOLATIONS={invariant_violations}")
        for group in (GROUP_DIRECT, GROUP_EMBEDDED):
            print(f"TRACK_{group}={dict(per_track[group])}")

        # ------------------------------------------------------- Phase 17 recall
        required_classes_by_category = {
            category: {
                c
                for group in groups
                for c in category_plan(category, group).required_classes
            }
            for category, groups in groups_by_category.items()
        }
        current_pid_set = {o["procurement_id"] for o in opportunities}
        recall = Counter()
        doc_status = Counter()
        skipped_class_examples = Counter()
        loss_class_combo = Counter()
        current_loss_combo = Counter()
        current_loss_examples: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = []
        by_unit: Dict[Tuple[int, str], List[str]] = defaultdict(list)
        for row in known_positives:
            by_unit[(int(row["procurement_id"]), row["category_code"])].append(row["document_name"])

        recall_losses: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = []
        unit_plans: Dict[Tuple[int, str], Any] = {}
        for (pid, category), names in by_unit.items():
            required = required_classes_by_category.get(category)
            if not required:
                recall["CATEGORY_NOT_IN_CURRENT"] += 1
                continue
            plan = unit_plans.get((pid, category))
            if plan is None:
                plan = build_document_needs_plan(
                    pid,
                    [category_plan(category, g) for g in sorted(groups_by_category[category])],
                )
                unit_plans[(pid, category)] = plan
            names = sorted(set(names))
            classifications = [classify_document_metadata(name) for name in names]
            items = [(None, name, classification) for name, classification in zip(names, classifications)]
            selections, promoted = select_unit_documents(
                plan, procurement_id=pid, category_code=category, documents=items
            )
            classes: Dict[str, int] = {}
            unit_has_selected = False
            if promoted is not None:
                recall["FALLBACK_UNITS"] += 1
                if pid in current_pid_set:
                    recall["FALLBACK_UNITS_CURRENT"] += 1
            for name, classification, selection in zip(names, classifications, selections):
                classes[classification.document_class.value] = (
                    classes.get(classification.document_class.value, 0) + 1
                )
                if selection.selection_decision in (SELECTED, SELECTED_FALLBACK):
                    doc_status["KNOWN_POSITIVE_DOC_SELECTED"] += 1
                    if selection.selection_decision == SELECTED_FALLBACK:
                        doc_status["KNOWN_POSITIVE_DOC_SELECTED_FALLBACK"] += 1
                    unit_has_selected = True
                elif selection.selection_decision == UNKNOWN_NEEDS_REVIEW:
                    doc_status["KNOWN_POSITIVE_DOC_DEFERRED_UNKNOWN"] += 1
                else:
                    doc_status["KNOWN_POSITIVE_DOC_SKIPPED"] += 1
                    skipped_class_examples[(category, classification.document_class.value)] += 1
                    recall["SKIPPED_REASON_" + selection.selection_reason.split(":")[0]] += 1
            if unit_has_selected:
                recall["RECALL_OK_UNITS"] += 1
                if pid in current_pid_set:
                    recall["RECALL_OK_UNITS_CURRENT"] += 1
            else:
                recall["RECALL_LOSS_UNITS"] += 1
                loss_class_combo[(category, tuple(sorted(classes)))] += 1
                recall_losses.append(
                    (category, tuple(sorted(classes)), tuple(sorted(set(names))[:3]))
                )
                if pid in current_pid_set:
                    recall["RECALL_LOSS_UNITS_CURRENT"] += 1
                    current_loss_combo[(category, tuple(sorted(classes)))] += 1
                    if len(current_loss_examples) < 12:
                        current_loss_examples.append(
                            (category, tuple(sorted(classes)), tuple(sorted(set(names))[:3]))
                        )

        print("=" * 78)
        print("PHASE 17 - RECALL SAFETY AUDIT (document_matches known positives)")
        print(f"KNOWN_POSITIVE_UNITS={recall['RECALL_OK_UNITS'] + recall['RECALL_LOSS_UNITS']}")
        total_docs = doc_status["KNOWN_POSITIVE_DOC_SELECTED"] + doc_status["KNOWN_POSITIVE_DOC_SKIPPED"] + doc_status["KNOWN_POSITIVE_DOC_DEFERRED_UNKNOWN"]
        print(f"KNOWN_POSITIVE_DOCUMENTS={total_docs}")
        print(f"KNOWN_POSITIVE_SELECTED={doc_status['KNOWN_POSITIVE_DOC_SELECTED']}")
        print(f"KNOWN_POSITIVE_SELECTED_FALLBACK={doc_status['KNOWN_POSITIVE_DOC_SELECTED_FALLBACK']}")
        print(f"KNOWN_POSITIVE_DEFERRED_UNKNOWN={doc_status['KNOWN_POSITIVE_DOC_DEFERRED_UNKNOWN']}")
        print(f"KNOWN_POSITIVE_SKIPPED={doc_status['KNOWN_POSITIVE_DOC_SKIPPED']}")
        print(f"RECALL_OK_UNITS={recall['RECALL_OK_UNITS']}")
        print(f"RECALL_LOSS_UNITS={recall['RECALL_LOSS_UNITS']}")
        print(f"CURRENT_RECALL_OK_UNITS={recall['RECALL_OK_UNITS_CURRENT']}")
        print(f"CURRENT_RECALL_LOSS_UNITS={recall['RECALL_LOSS_UNITS_CURRENT']}")
        print(f"KNOWN_POSITIVE_CURRENT_LOSS={recall['RECALL_LOSS_UNITS_CURRENT']}")
        print(f"KNOWN_POSITIVE_GLOBAL_LOSS={recall['RECALL_LOSS_UNITS']}")
        print(f"RECALL_FALLBACK_UNITS={recall['FALLBACK_UNITS']}")
        print(f"CURRENT_RECALL_FALLBACK_UNITS={recall['FALLBACK_UNITS_CURRENT']}")
        print(f"CATEGORY_NOT_IN_CURRENT_UNITS={recall['CATEGORY_NOT_IN_CURRENT']}")
        units = recall["RECALL_OK_UNITS"] + recall["RECALL_LOSS_UNITS"]
        if units:
            print(f"KNOWN_POSITIVE_RECALL={100.0 * recall['RECALL_OK_UNITS'] / units:.1f}%")
        print(f"SKIPPED_REASON_TOTALS={[(k, v) for k, v in recall.items() if k.startswith('SKIPPED_REASON_')]}")
        print(f"SKIPPED_CLASS_EXAMPLES={skipped_class_examples.most_common(12)}")
        print(f"RECALL_LOSS_EXAMPLES={recall_losses[:6]}")
        print(f"RECALL_LOSS_CLASS_COMBOS={loss_class_combo.most_common(10)}")
        print(f"CURRENT_RECALL_LOSS_CLASS_COMBOS={current_loss_combo.most_common(10)}")
        print(f"CURRENT_RECALL_LOSS_EXAMPLES={current_loss_examples}")

        # --------------------------------------------- Phases 18-20 routing/reuse
        print("=" * 78)
        print("PHASE 18 - PARSER/NORMALIZER ROUTING")
        parser_ok = sum(v for (k, _), v in route_counts.items() if k == "PARSER_OK")
        parser_gap = sum(v for (k, _), v in route_counts.items() if k == "PARSER_GAP")
        norm_ok = sum(v for (k, _), v in route_counts.items() if k == "NORMALIZER_OK")
        norm_gap = sum(v for (k, _), v in route_counts.items() if k == "NORMALIZER_GAP")
        print(f"SELECTED_WITH_PARSER_ROUTE={parser_ok}")
        print(f"SELECTED_WITHOUT_PARSER_ROUTE={parser_gap}")
        print(f"SELECTED_WITH_NORMALIZER_ROUTE={norm_ok}")
        print(f"SELECTED_WITHOUT_NORMALIZER_ROUTE={norm_gap}")
        gaps = sorted({cls for (kind, cls), v in route_counts.items() if kind.endswith("GAP") and v})
        print(f"EXPLICIT_GAP_LIST={gaps}")

        print("=" * 78)
        print("PHASE 19 - ARTIFACT REUSE SIMULATION")
        print(f"SELECTED_TOTAL={len(selected_docs)}")
        for key in ("REUSE_NO_HTTP", "REPROCESS_NO_HTTP", "NEW_DOWNLOAD_REQUIRED"):
            print(f"{key}={reuse_counts.get(key, 0)}")

        print("=" * 78)
        print("PHASE 20 - FUTURE QUEUE PAYLOAD (NOT WRITTEN)")
        print(f"MULTI_CATEGORY_PLANS={len(multi_category_plans)}")
        for pid, plan in list(multi_category_plans.items())[:3]:
            opps = opps_by_pid[pid]
            payload = {
                "procurement_id": pid,
                "work_tier": None,
                "source_start_date": str(opps[0]["start_date"]),
                "candidate_initial_medal": opps[0]["candidate_initial_medal"],
                "research_action_v2": sorted(
                    {r["decision"].action.value for r in decisions if r["opp"]["procurement_id"] == pid}
                ),
                "document_plan_version": DOCUMENT_NEEDS_POLICY_VERSION,
                "category_codes": sorted({o["category_code"] for o in opps}),
                "required_document_types": [c.value for c in plan.required_classes],
                "required_facts": [f.value for f in plan.required_facts],
            }
            print(f"PAYLOAD={payload}")

        print("=" * 78)
        print("POLICY VERSIONS / SAFETY")
        print(f"RESEARCH_ACTION_POLICY_VERSION={RESEARCH_ACTION_POLICY_VERSION}")
        print(f"DOCUMENT_NEEDS_POLICY_VERSION={DOCUMENT_NEEDS_POLICY_VERSION}")
        print(f"DOCUMENT_CLASSIFIER_VERSION={DOCUMENT_CLASSIFIER_VERSION}")
        print(f"DOCUMENT_SELECTION_POLICY_VERSION={DOCUMENT_SELECTION_POLICY_VERSION}")
        print("PRODUCTION_WRITES=0")
        print("QUEUE_WRITES=0")
        print("HTTP_REQUESTS=0")
        print("DOCUMENT_DOWNLOADS=0")
        return 0
    finally:
        crm.close()
        di.close()


if __name__ == "__main__":
    raise SystemExit(main())
