"""Legacy user OKPD → global commercial category knowledge migration (local only)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from src.domain.commercial_taxonomy import (
    COMMERCIAL_KEEP_CODES,
    TARGET_COMMERCIAL_CODES,
)
from src.services.commercial_routing_v3.okpd_priors import (
    match_okpd_priors,
    normalize_okpd_code,
    prefix_matches,
)

OKPD_CODE_SOURCE = "collection_codes_okpd.sub_code"

# Discrete prior weights — expert-selected, not learned probabilities.
PRIOR_WEIGHT_HIGH = 70
PRIOR_WEIGHT_MEDIUM = 50
PRIOR_WEIGHT_LOW = 35
PRIOR_WEIGHT_MODEL = "DISCRETE_EXPERT_SCALE_HIGH_70_MEDIUM_50_LOW_35"

REGISTRY_VERSION = 3

LEGACY_CATEGORY_DESIGN = "Проектирование"
LEGACY_CATEGORY_CONSTRUCTION = "Стройка"
LEGACY_CATEGORY_COMPUTERS = "Компьютеры"

LEGACY_CATEGORY_BY_PROFILE_ID: Dict[int, str] = {
    1: LEGACY_CATEGORY_DESIGN,
    2: LEGACY_CATEGORY_CONSTRUCTION,
    3: LEGACY_CATEGORY_COMPUTERS,
    7: LEGACY_CATEGORY_DESIGN,
    8: LEGACY_CATEGORY_CONSTRUCTION,
    9: LEGACY_CATEGORY_COMPUTERS,
}

# Construction OKPD prefix → multiple commercial categories (ONE_OKPD_ONE_CATEGORY=NO).
# Derived from legacy expert "Стройка" profile + commercial taxonomy + OKPD_ROUTE_PROPOSAL.
CONSTRUCTION_OKPD_FANOUT: Dict[str, List[Tuple[str, int]]] = {
    "42.11": [
        ("lighting", PRIOR_WEIGHT_MEDIUM),
        ("waterproofing", PRIOR_WEIGHT_MEDIUM),
        ("drainage_water_management", PRIOR_WEIGHT_MEDIUM),
        ("curbstone", PRIOR_WEIGHT_LOW),
        ("composite_structures", PRIOR_WEIGHT_LOW),
    ],
    "42.12": [("lighting", PRIOR_WEIGHT_LOW), ("curbstone", PRIOR_WEIGHT_LOW)],
    "42.13": [("composite_structures", PRIOR_WEIGHT_MEDIUM)],
    "42.21": [("drainage_water_management", PRIOR_WEIGHT_MEDIUM)],
    "42.99": [
        ("composite_structures", PRIOR_WEIGHT_LOW),
        ("drainage_water_management", PRIOR_WEIGHT_LOW),
    ],
    "41.2": [
        ("flooring", PRIOR_WEIGHT_MEDIUM),
        ("waterproofing", PRIOR_WEIGHT_LOW),
        ("composite_structures", PRIOR_WEIGHT_LOW),
    ],
    "41.20": [("flooring", PRIOR_WEIGHT_MEDIUM), ("waterproofing", PRIOR_WEIGHT_LOW)],
    "43.21": [("cable_support_systems", PRIOR_WEIGHT_MEDIUM), ("lighting", PRIOR_WEIGHT_LOW)],
    "43.22": [("drainage_water_management", PRIOR_WEIGHT_MEDIUM)],
    "43.33": [("flooring", PRIOR_WEIGHT_HIGH)],
    "43.39": [("flooring", PRIOR_WEIGHT_MEDIUM), ("waterproofing", PRIOR_WEIGHT_LOW)],
    "43.99": [("waterproofing", PRIOR_WEIGHT_LOW), ("composite_structures", PRIOR_WEIGHT_LOW)],
    "27.40": [("lighting", PRIOR_WEIGHT_HIGH)],
    "27.32": [("cable_support_systems", PRIOR_WEIGHT_MEDIUM)],
}

COMPUTERS_OKPD_PREFIXES = {"26.20", "26.2", "26.20.1", "26.20.11", "26.20.17", "26.20.22", "26.20.9"}

# Supplemental expert priors not present in legacy user OKPD lists but required for
# direct-product categories. Provenance MUST NOT be LEGACY_USER_SETTING.
SUPPLEMENTAL_EXPERT_PROVENANCE = "SUPPLEMENTAL_EXPERT_RULE"
SUPPLEMENTAL_EXPERT_SOURCE_TABLE = "supplemental_expert_rule"
SUPPLEMENTAL_EXPERT_PRIORS: List[Tuple[str, str, str, int]] = [
    ("lighting", "27.40", "PREFIX", PRIOR_WEIGHT_HIGH),
    ("cable_support_systems", "27.32", "PREFIX", PRIOR_WEIGHT_MEDIUM),
]

# Legacy title stop words are soft negatives pending model calibration.
LEGACY_STOP_SIGNAL_STRENGTH = "LEGACY_SOFT_NEGATIVE_DEFAULT"
LEGACY_STOP_HARD_SKIP = False

MISPLACED_COMPUTER_OKPD_PREFIXES = {"22.23", "47", "26"}  # broad or wrong family

CLASSIFICATION_VALUES = {
    "MIGRATE_CONFIDENT",
    "REVIEW_REQUIRED",
    "CONTEXT_ONLY",
    "MATERIAL_FAMILY_ONLY",
    "NEGATIVE_RULE",
    "OBSOLETE",
    "UNMAPPED",
}


@dataclass
class LegacyOkpdRule:
    legacy_rule_id: int
    source_table: str
    source_user_id: Optional[int]
    source_profile_id: Optional[int]
    okpd_code: str
    okpd_prefix: str
    match_semantics: str
    include_exclude: str
    legacy_category: Optional[str]
    description: Optional[str]
    active: bool = True
    provenance: str = "okpd_from_users"


@dataclass
class MigrationAuditRow:
    source_table: str
    source_row_id: int
    source_user_id: Optional[str]
    source_profile_id: Optional[str]
    okpd_pattern: Optional[str]
    legacy_category: Optional[str]
    classification: str
    target_category_code: Optional[str]
    target_signal_role: Optional[str]
    migration_status: str
    review_reason: Optional[str] = None


@dataclass
class GeneratedPrior:
    commercial_category_code: str
    okpd_pattern: str
    match_type: str
    prior_weight: int
    signal_role: str
    provenance: str
    source_table: str
    source_row_id: int
    source_user_id: Optional[str]
    migration_class: str


@dataclass
class GeneratedRoutingSignal:
    commercial_category_code: Optional[str]
    signal_type: str
    signal_scope: str
    phrase: str
    provenance: str
    source_table: str
    source_row_id: int
    migration_class: str
    signal_strength: str = LEGACY_STOP_SIGNAL_STRENGTH


@dataclass
class MigrationBundle:
    priors: List[GeneratedPrior] = field(default_factory=list)
    routing_signals: List[GeneratedRoutingSignal] = field(default_factory=list)
    audit_rows: List[MigrationAuditRow] = field(default_factory=list)
    classification_counts: Counter = field(default_factory=Counter)


def normalize_okpd_code(code: str) -> str:
    return re.sub(r"\s+", "", (code or "").strip())


def infer_match_type(okpd_code: str, all_codes: Set[str]) -> str:
    """Leaf legacy selections → EXACT; branch/prefix selections → PREFIX."""
    code = normalize_okpd_code(okpd_code)
    if not code:
        return "PREFIX"
    for other in all_codes:
        if other != code and other.startswith(code + "."):
            return "PREFIX"
    return "EXACT"


def _longest_fanout_prefix(okpd_code: str) -> Optional[str]:
    code = normalize_okpd_code(okpd_code)
    best = None
    for prefix in CONSTRUCTION_OKPD_FANOUT:
        if prefix_matches(code, prefix, "PREFIX"):
            if best is None or len(prefix) > len(best):
                best = prefix
    return best


def classify_legacy_rule(rule: LegacyOkpdRule, all_codes: Set[str]) -> Tuple[str, Optional[str], Optional[str]]:
    code = normalize_okpd_code(rule.okpd_code)
    cat = (rule.legacy_category or "").strip()

    if not code:
        return "OBSOLETE", None, "empty_okpd_code"

    if not cat:
        return "UNMAPPED", None, "missing_legacy_category"

    if cat == LEGACY_CATEGORY_DESIGN or code.startswith("71"):
        return "CONTEXT_ONLY", None, "design_services_not_sellable_category"

    if cat == LEGACY_CATEGORY_COMPUTERS:
        if any(code == p or prefix_matches(code, p, "PREFIX") for p in MISPLACED_COMPUTER_OKPD_PREFIXES if p != "26.20"):
            if code.startswith("22.23"):
                return "REVIEW_REQUIRED", "composite_structures", "miscategorized_under_computers_profile"
            if code.startswith("47"):
                return "OBSOLETE", None, "retail_services_not_computers"
            if code == "26":
                return "REVIEW_REQUIRED", "computers", "overbroad_26_includes_medical"
        if any(prefix_matches(code, p, "PREFIX") for p in COMPUTERS_OKPD_PREFIXES):
            return "MIGRATE_CONFIDENT", "computers", None
        return "REVIEW_REQUIRED", "computers", "computers_profile_unrecognized_okpd"

    if cat == LEGACY_CATEGORY_CONSTRUCTION:
        fanout_key = _longest_fanout_prefix(code)
        if fanout_key:
            return "MIGRATE_CONFIDENT", None, None
        if code.startswith(("41.", "42.", "43.")):
            return "REVIEW_REQUIRED", None, "construction_okpd_without_confident_fanout"
        return "CONTEXT_ONLY", None, "construction_profile_non_building_okpd"

    return "UNMAPPED", None, f"unknown_legacy_category:{cat}"


def rules_from_audit_json(raw: Dict[str, Any]) -> List[LegacyOkpdRule]:
    out: List[LegacyOkpdRule] = []
    for row in raw.get("rules") or []:
        code = normalize_okpd_code(row.get("okpd_code") or "")
        profile_id = row.get("category_id")
        legacy_category = None
        if profile_id is not None:
            legacy_category = LEGACY_CATEGORY_BY_PROFILE_ID.get(int(profile_id))
        if not legacy_category:
            legacy_category = row.get("category_name")
        out.append(
            LegacyOkpdRule(
                legacy_rule_id=int(row["id"]),
                source_table="okpd_from_users",
                source_user_id=row.get("user_id"),
                source_profile_id=row.get("category_id"),
                okpd_code=code,
                okpd_prefix=code,
                match_semantics="PREFIX",  # legacy queue used prefix semantics
                include_exclude="INCLUDE",
                legacy_category=legacy_category,
                description=row.get("name"),
            )
        )
    return out


def stop_rules_from_audit_json(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(raw.get("rules") or raw.get("stop_sample") or [])


def build_migration_bundle(legacy_rules: Iterable[LegacyOkpdRule]) -> MigrationBundle:
    bundle = MigrationBundle()
    rules = list(legacy_rules)
    all_codes = {r.okpd_code for r in rules if r.okpd_code}

    # Deduplicate global priors by (category, pattern, match_type) while preserving audit per source row.
    prior_keys: Set[Tuple[str, str, str]] = set()

    for rule in rules:
        classification, single_target, reason = classify_legacy_rule(rule, all_codes)
        bundle.classification_counts[classification] += 1
        match_type = infer_match_type(rule.okpd_code, all_codes)

        bundle.audit_rows.append(
            MigrationAuditRow(
                source_table=rule.source_table,
                source_row_id=rule.legacy_rule_id,
                source_user_id=str(rule.source_user_id) if rule.source_user_id is not None else None,
                source_profile_id=str(rule.source_profile_id) if rule.source_profile_id is not None else None,
                okpd_pattern=rule.okpd_code or None,
                legacy_category=rule.legacy_category,
                classification=classification,
                target_category_code=single_target,
                target_signal_role="CANDIDATE_SIGNAL" if classification == "MIGRATE_CONFIDENT" else None,
                migration_status="PREPARED" if classification == "MIGRATE_CONFIDENT" else "AUDIT_ONLY",
                review_reason=reason,
            )
        )

        if classification == "MIGRATE_CONFIDENT" and rule.legacy_category == LEGACY_CATEGORY_COMPUTERS:
            key = ("computers", rule.okpd_code, match_type)
            if key not in prior_keys:
                prior_keys.add(key)
                bundle.priors.append(
                    GeneratedPrior(
                        commercial_category_code="computers",
                        okpd_pattern=rule.okpd_code,
                        match_type=match_type,
                        prior_weight=PRIOR_WEIGHT_HIGH if rule.okpd_code.startswith("26.20") else PRIOR_WEIGHT_MEDIUM,
                        signal_role="CANDIDATE_SIGNAL",
                        provenance="legacy_okpd_from_users",
                        source_table=rule.source_table,
                        source_row_id=rule.legacy_rule_id,
                        source_user_id=str(rule.source_user_id) if rule.source_user_id is not None else None,
                        migration_class="MIGRATE_CONFIDENT",
                    )
                )

        elif classification == "MIGRATE_CONFIDENT" and rule.legacy_category == LEGACY_CATEGORY_CONSTRUCTION:
            fanout_key = _longest_fanout_prefix(rule.okpd_code)
            targets = CONSTRUCTION_OKPD_FANOUT.get(fanout_key or "", [])
            for cat_code, weight in targets:
                if cat_code not in COMMERCIAL_KEEP_CODES:
                    continue
                key = (cat_code, rule.okpd_code, match_type)
                if key in prior_keys:
                    continue
                prior_keys.add(key)
                bundle.priors.append(
                    GeneratedPrior(
                        commercial_category_code=cat_code,
                        okpd_pattern=rule.okpd_code,
                        match_type=match_type,
                        prior_weight=weight,
                        signal_role="CANDIDATE_SIGNAL",
                        provenance="legacy_okpd_from_users",
                        source_table=rule.source_table,
                        source_row_id=rule.legacy_rule_id,
                        source_user_id=str(rule.source_user_id) if rule.source_user_id is not None else None,
                        migration_class="MIGRATE_CONFIDENT",
                    )
                )

    for cat_code, pattern, match_type, weight in SUPPLEMENTAL_EXPERT_PRIORS:
        key = (cat_code, pattern, match_type)
        if key in prior_keys:
            continue
        prior_keys.add(key)
        bundle.priors.append(
            GeneratedPrior(
                commercial_category_code=cat_code,
                okpd_pattern=pattern,
                match_type=match_type,
                prior_weight=weight,
                signal_role="CANDIDATE_SIGNAL",
                provenance=SUPPLEMENTAL_EXPERT_PROVENANCE,
                source_table=SUPPLEMENTAL_EXPERT_SOURCE_TABLE,
                source_row_id=0,
                source_user_id=None,
                migration_class="MIGRATE_CONFIDENT",
            )
        )
        bundle.audit_rows.append(
            MigrationAuditRow(
                source_table=SUPPLEMENTAL_EXPERT_SOURCE_TABLE,
                source_row_id=0,
                source_user_id=None,
                source_profile_id=None,
                okpd_pattern=pattern,
                legacy_category=None,
                classification="MIGRATE_CONFIDENT",
                target_category_code=cat_code,
                target_signal_role="CANDIDATE_SIGNAL",
                migration_status="PREPARED",
                review_reason="SUPPLEMENTAL_EXPERT_RULE:not_legacy_user_setting",
            )
        )

    return bundle


def build_stop_word_bundle(stop_rows: List[Dict[str, Any]]) -> Tuple[List[GeneratedRoutingSignal], List[MigrationAuditRow], Counter]:
    signals: List[GeneratedRoutingSignal] = []
    audit: List[MigrationAuditRow] = []
    counts: Counter = Counter()
    seen: Set[Tuple[Optional[str], str]] = set()

    category_hints = {
        "отоплен": "lighting",
        "светильник": "lighting",
        "освещен": "lighting",
        "гидроизоляц": "waterproofing",
    }

    for row in stop_rows:
        phrase = (row.get("stop_word") or "").strip().lower()
        if not phrase:
            counts["OBSOLETE"] += 1
            continue

        # Legacy title stop words are soft negatives by default — not global hard skip.
        assert LEGACY_STOP_HARD_SKIP is False
        classification = "NEGATIVE_SIGNAL"
        signal_type = "NEGATIVE_SIGNAL"
        counts[classification] += 1

        cat: Optional[str] = None
        for hint, category in category_hints.items():
            if hint in phrase:
                cat = category
                break

        key = (cat, phrase)
        if key in seen:
            continue
        seen.add(key)

        signals.append(
            GeneratedRoutingSignal(
                commercial_category_code=cat,
                signal_type=signal_type,
                signal_scope="PRELIMINARY_TITLE",
                phrase=phrase,
                provenance="legacy_stop_words_names",
                source_table="stop_words_names",
                source_row_id=int(row.get("id") or 0),
                migration_class="MIGRATE_CONFIDENT",
                signal_strength=LEGACY_STOP_SIGNAL_STRENGTH,
            )
        )
        audit.append(
            MigrationAuditRow(
                source_table="stop_words_names",
                source_row_id=int(row.get("id") or 0),
                source_user_id=str(row.get("user_id")) if row.get("user_id") is not None else None,
                source_profile_id=str(row.get("setting_id")) if row.get("setting_id") is not None else None,
                okpd_pattern=None,
                legacy_category=None,
                classification=classification,
                target_category_code=cat,
                target_signal_role=signal_type,
                migration_status="PREPARED",
                review_reason=None,
            )
        )

    return signals, audit, counts


def load_audit_json(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8")
    return json.loads(text)


def category_coverage_report(priors: List[GeneratedPrior], signals: List[GeneratedRoutingSignal]) -> List[Dict[str, Any]]:
    rows = []
    for cat in sorted(TARGET_COMMERCIAL_CODES):
        cat_priors = [p for p in priors if p.commercial_category_code == cat]
        cat_signals = [s for s in signals if s.commercial_category_code == cat]
        rows.append(
            {
                "category_code": cat,
                "total_okpd_priors": len(cat_priors),
                "exact_priors": sum(1 for p in cat_priors if p.match_type == "EXACT"),
                "prefix_priors": sum(1 for p in cat_priors if p.match_type == "PREFIX"),
                "positive_signals": sum(1 for s in cat_signals if s.signal_type == "POSITIVE_SIGNAL"),
                "negative_signals": sum(1 for s in cat_signals if s.signal_type == "NEGATIVE_SIGNAL"),
                "hard_exclusions": sum(1 for s in cat_signals if s.signal_type == "HARD_EXCLUSION"),
                "review_required": 0,
            }
        )
    return rows


def multi_category_okpd_count(priors: List[GeneratedPrior]) -> int:
    by_pattern: Dict[str, Set[str]] = defaultdict(set)
    for p in priors:
        by_pattern[p.okpd_pattern].add(p.commercial_category_code)
    return sum(1 for cats in by_pattern.values() if len(cats) > 1)


def sql_escape(value: str) -> str:
    return value.replace("'", "''")


def render_migration_sql(bundle: MigrationBundle, stop_signals: List[GeneratedRoutingSignal], stop_audit: List[MigrationAuditRow]) -> str:
    lines = [
        "-- GENERATED: legacy OKPD expert knowledge migration (DO NOT APPLY IN PRODUCTION WITHOUT REVIEW)",
        "-- SOURCE: tender_monitor.okpd_from_users + stop_words_names (read-only audit)",
        f"-- REGISTRY_VERSION: {REGISTRY_VERSION}",
        "",
    ]

    if bundle.priors:
        lines.append("INSERT INTO crm_category_okpd_priors (")
        lines.append("    commercial_category_code, okpd_pattern, match_type, prior_weight, signal_role,")
        lines.append("    active, provenance, source_table, source_row_id, source_user_id, migration_class, registry_version")
        lines.append(") VALUES")
        value_lines = []
        for p in bundle.priors:
            value_lines.append(
                "    ('{cat}', '{pat}', '{mt}', {w}, '{role}', TRUE, '{prov}', '{st}', {sid}, {uid}, '{mc}', {rv})".format(
                    cat=sql_escape(p.commercial_category_code),
                    pat=sql_escape(p.okpd_pattern),
                    mt=sql_escape(p.match_type),
                    w=p.prior_weight,
                    role=sql_escape(p.signal_role),
                    prov=sql_escape(p.provenance),
                    st=sql_escape(p.source_table),
                    sid=p.source_row_id,
                    uid=f"'{sql_escape(p.source_user_id)}'" if p.source_user_id else "NULL",
                    mc=sql_escape(p.migration_class),
                    rv=REGISTRY_VERSION,
                )
            )
        lines.append(",\n".join(value_lines))
        lines.append("ON CONFLICT (commercial_category_code, okpd_pattern, match_type) DO UPDATE SET")
        lines.append("    prior_weight = EXCLUDED.prior_weight,")
        lines.append("    signal_role = EXCLUDED.signal_role,")
        lines.append("    migration_class = EXCLUDED.migration_class,")
        lines.append("    updated_at = NOW();")
        lines.append("")

    if stop_signals:
        lines.append("INSERT INTO crm_category_routing_signals (")
        lines.append("    commercial_category_code, signal_type, signal_scope, phrase,")
        lines.append("    active, provenance, source_table, source_row_id, migration_class,")
        lines.append("    signal_strength, registry_version")
        lines.append(") VALUES")
        sig_lines = []
        for s in stop_signals:
            cat_sql = f"'{sql_escape(s.commercial_category_code)}'" if s.commercial_category_code else "NULL"
            sig_lines.append(
                "    ({cat}, '{stype}', '{scope}', '{phrase}', TRUE, '{prov}', '{st}', {sid}, '{mc}', '{strength}', {rv})".format(
                    cat=cat_sql,
                    stype=sql_escape(s.signal_type),
                    scope=sql_escape(s.signal_scope),
                    phrase=sql_escape(s.phrase),
                    prov=sql_escape(s.provenance),
                    st=sql_escape(s.source_table),
                    sid=s.source_row_id,
                    mc=sql_escape(s.migration_class),
                    strength=sql_escape(s.signal_strength),
                    rv=REGISTRY_VERSION,
                )
            )
        lines.append(",\n".join(sig_lines))
        lines.append(";")
        lines.append("")

    all_audit = bundle.audit_rows + stop_audit
    if all_audit:
        lines.append("INSERT INTO crm_legacy_okpd_migration_audit (")
        lines.append("    source_table, source_row_id, source_user_id, source_profile_id, okpd_pattern,")
        lines.append("    legacy_category, classification, target_category_code, target_signal_role,")
        lines.append("    migration_status, review_reason")
        lines.append(") VALUES")
        audit_lines = []
        for a in all_audit:
            audit_lines.append(
                "    ('{st}', {sid}, {uid}, {pid}, {okpd}, {lcat}, '{cls}', {tcat}, {trole}, '{ms}', {rr})".format(
                    st=sql_escape(a.source_table),
                    sid=a.source_row_id,
                    uid=f"'{sql_escape(a.source_user_id)}'" if a.source_user_id else "NULL",
                    pid=f"'{sql_escape(a.source_profile_id)}'" if a.source_profile_id else "NULL",
                    okpd=f"'{sql_escape(a.okpd_pattern)}'" if a.okpd_pattern else "NULL",
                    lcat=f"'{sql_escape(a.legacy_category)}'" if a.legacy_category else "NULL",
                    cls=sql_escape(a.classification),
                    tcat=f"'{sql_escape(a.target_category_code)}'" if a.target_category_code else "NULL",
                    trole=f"'{sql_escape(a.target_signal_role)}'" if a.target_signal_role else "NULL",
                    ms=sql_escape(a.migration_status),
                    rr=f"'{sql_escape(a.review_reason)}'" if a.review_reason else "NULL",
                )
            )
        lines.append(",\n".join(audit_lines))
        lines.append(";")

    return "\n".join(lines) + "\n"
