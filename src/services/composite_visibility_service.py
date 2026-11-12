"""Factual-card visibility for object/project procurements.

The read model is projection-only: it does not delete or rescore
opportunities. It exposes three distinct card kinds:

* opportunity-backed: current opportunity + gate-valid material fact;
* fact-only: gate-valid material fact without a matching current opportunity;
* evidence-only: material/attribute evidence without qty/unit/total.

Object/project facts come from resolved `structured_estimate_rows`;
`structured_entities` remains a compatibility fallback for DIRECT supply.

Fact-only and evidence-only cards never receive an invented medal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import psycopg2
import psycopg2.extras

from src.services.good_supply_facts_service import (
    classify_supply_row,
    load_good_supply_rows,
    to_flat_fact,
)

COMPOSITE_CATEGORY_CODE = "composite_structures"
_UNCLASSIFIED_SENTINEL = "SUBCATEGORY_NOT_ASSIGNED"
_DIRECT_SUPPLY = "DIRECT_SUPPLY"
_EMBEDDED_MATERIAL = "EMBEDDED_MATERIAL"
_OBJECT_SCOPE_TYPES = (
    "DESIGN_PROJECT",
    "WORKS_WITH_EMBEDDED_PRODUCTS",
)
_EVIDENCE_REASONS = frozenset({"no_quantity", "no_total"})

_WORK_EVIDENCE_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"работы|текущее\s+обслуживание|техническое\s+обслуживание|"
    r"ежемесячное\s+обслуживание|обслуживание|"
    r"ямочный\s+ремонт|ремонт|проверка|очистка|"
    r"копание|огрунтовка|окрашивание|сборка|разборка|"
    r"установка|монтаж|демонтаж|замена|регулировка|"
    r"диагностика|испытание|продувка|промывка|"
    r"перевозка|засыпка|обратн\w*\s+.*?засыпка|"
    r"укладка|нанесение|герметизация|содержание|"
    r"устройство|планировка|разработка|"
    r"ведомост\w*|перечень\s+работ|смета\b"
    r")\b",
    re.IGNORECASE,
)
_STRONG_MATERIAL_RE = re.compile(
    r"(?:"
    r"огражден\w*|дождеприем\w*|решетк\w*|"
    r"праймер\w*|грунтовк\w*|светофор\w*|светильник\w*|"
    r"контроллер\w*|боллард\w*|табло|пульт\w*|"
    r"лент\w*|мембран\w*|"
    r"пропитк\w*|состав\w*|смол\w*|мастик\w*|герметик\w*|"
    r"смес\w*|оборудован\w*|аппарат\w*|прибор\w*|"
    r"кабел\w*|провод\w*|труб\w*|шкаф\w*|блок\w*|"
    r"модул\w*|панел\w*|плит\w*|элемент\w*|издели\w*|"
    r"краск\w*|эмал\w*|лак\w*|кле\w*|крепеж\w*|"
    r"болт\w*|гайк\w*|профил\w*|лист\w*|рулон\w*|"
    r"линолеум\w*|ламинат\w*|паркет\w*|подложк\w*|"
    r"керамогранит\w*|плитк\w*|обои|стеклообои|"
    r"наливн\w*\s+пол\w*"
    r")",
    re.IGNORECASE,
)
_WEAK_EVIDENCE_CONTEXT_RE = re.compile(
    r"^\s*(?:"
    r"грунтовк\w*(?:\s*[,.;]|\s+"
    r"(?:бетоноконтакт|обои|стеклообои|поверхност|"
    r"под\b|с\s+последующей))|"
    r"грунтовк\w*\s*,\s*покраск\w*|"
    r"подвесн\w*\b"
    r")",
    re.IGNORECASE,
)
_NON_MATERIAL_RATE_RE = re.compile(
    r"(?:без\s+уч[её]та\s+стоимости\s+материалов)",
    re.IGNORECASE,
)


def _is_strong_material_evidence(row: Mapping[str, Any]) -> bool:
    """Keep real materials while rejecting broad work/maintenance evidence."""
    if str(
        row.get("row_kind")
        or row.get("row_type")
        or ""
    ) == "SPECIAL_WORK_REVIEW":
        return True
    name = str(
        row.get("product_name_normalized")
        or row.get("product_name_raw")
        or row.get("name_normalized")
        or row.get("name_raw")
        or row.get("material")
        or ""
    ).strip()
    if (
        not name
        or _WORK_EVIDENCE_PREFIX_RE.match(name)
        or _WEAK_EVIDENCE_CONTEXT_RE.match(name)
        or _NON_MATERIAL_RATE_RE.search(name)
    ):
        return False
    category = str(row.get("category_code") or "").strip()
    if category:
        from tender_documents_research.document_processor.estimate_row_taxonomy import (
            category_semantic_guard,
        )

        if not category_semantic_guard(category, name):
            return False
    return bool(_STRONG_MATERIAL_RE.search(name))


@dataclass(frozen=True)
class CategoryFactVisibility:
    visible_pairs: frozenset[tuple[int, str, str]] = field(
        default_factory=frozenset
    )
    fact_only_pairs: frozenset[tuple[int, str, str]] = field(
        default_factory=frozenset
    )
    evidence_only_pairs: frozenset[tuple[int, str, str]] = field(
        default_factory=frozenset
    )
    evidence_rows: Mapping[int, tuple[dict[str, Any], ...]] = field(
        default_factory=dict
    )
    confirmed_goods_value_by_pair: Mapping[
        tuple[int, str, str], float
    ] = field(default_factory=dict)
    ok: bool = True
    reason: Optional[str] = None

    @property
    def visible_pids(self) -> frozenset[int]:
        return frozenset(pid for pid, _category, _subcategory in self.visible_pairs)

    @property
    def visible_categories(self) -> frozenset[str]:
        return frozenset(
            category for _pid, category, _subcategory in self.visible_pairs
        )

    @property
    def opportunity_pairs(self) -> frozenset[tuple[int, str, str]]:
        return (
            self.visible_pairs
            - self.fact_only_pairs
            - self.evidence_only_pairs
        )

    @property
    def inferred_subcategories(self) -> Mapping[int, str]:
        """Compatibility projection for callers handling one composite subcat."""
        grouped: Dict[int, set[str]] = {}
        for pid, category, subcategory in self.visible_pairs:
            if category == COMPOSITE_CATEGORY_CODE and subcategory:
                grouped.setdefault(pid, set()).add(subcategory)
        return {
            pid: next(iter(subcategories))
            for pid, subcategories in grouped.items()
            if len(subcategories) == 1
        }

    def pairs_for(
        self,
        procurement_id: int,
        category_code: str,
    ) -> tuple[tuple[int, str, str], ...]:
        return tuple(
            pair for pair in self.visible_pairs
            if pair[0] == int(procurement_id)
            and pair[1] == str(category_code)
        )

    def has_pair(
        self,
        procurement_id: int,
        category_code: str,
        subcategory_code: str | None = None,
    ) -> bool:
        return any(
            pid == int(procurement_id)
            and category == str(category_code)
            and (
                subcategory_code is None
                or subcategory == str(subcategory_code)
            )
            for pid, category, subcategory in self.visible_pairs
        )

    def is_evidence_only(
        self,
        procurement_id: int,
        category_code: str,
        subcategory_code: str | None = None,
    ) -> bool:
        return any(
            pid == int(procurement_id)
            and category == str(category_code)
            and (
                subcategory_code is None
                or subcategory == str(subcategory_code)
            )
            for pid, category, subcategory in self.evidence_only_pairs
        )

    def synthetic_opportunities_for(
        self,
        procurement_id: int,
    ) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for pair in sorted(
            self.fact_only_pairs | self.evidence_only_pairs
        ):
            pid, category, subcategory = pair
            if pid != int(procurement_id):
                continue
            evidence_only = pair in self.evidence_only_pairs
            rows.append(
                {
                    "procurement_id": pid,
                    "commercial_category_code": category,
                    "commercial_subcategory_code": subcategory,
                    "opportunity_track": _EMBEDDED_MATERIAL,
                    "status": "CURRENT",
                    "commercial_state": None,
                    "candidate_initial_score": None,
                    "candidate_initial_medal": None,
                    "confirmed_base_score": None,
                    "confirmed_base_medal": None,
                    "current_effective_score": None,
                    "current_effective_medal": None,
                    "current_effective_reason": None,
                    "factual_only": True,
                    "evidence_only": evidence_only,
                }
            )
        return tuple(rows)

    def evidence_for(
        self,
        procurement_id: int,
    ) -> tuple[dict[str, Any], ...]:
        if not procurement_id:
            return ()
        return tuple(self.evidence_rows.get(int(procurement_id), ()))

    def confirmed_value_for(
        self,
        procurement_id: int,
        category_code: str,
        subcategory_code: str | None = None,
    ) -> float:
        """Sum confirmed goods value for a procurement/category scope."""
        pid = int(procurement_id)
        category = str(category_code or "")
        subcategory = (
            None if subcategory_code is None else str(subcategory_code or "")
        )
        return sum(
            float(value or 0)
            for (row_pid, row_category, row_subcategory), value
            in self.confirmed_goods_value_by_pair.items()
            if row_pid == pid
            and row_category == category
            and (subcategory is None or row_subcategory == subcategory)
        )

    def confirmed_value_by_category(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for (_pid, category, _subcategory), value in (
            self.confirmed_goods_value_by_pair.items()
        ):
            totals[category] = totals.get(category, 0.0) + float(value or 0)
        return totals

    def confirmed_value_by_subcategory(self) -> dict[tuple[str, str], float]:
        totals: dict[tuple[str, str], float] = {}
        for (_pid, category, subcategory), value in (
            self.confirmed_goods_value_by_pair.items()
        ):
            key = (category, subcategory)
            totals[key] = totals.get(key, 0.0) + float(value or 0)
        return totals

    @property
    def confirmed_goods_total(self) -> float:
        return sum(
            float(value or 0)
            for value in self.confirmed_goods_value_by_pair.values()
        )


CompositeVisibility = CategoryFactVisibility


def _clean_subcategory(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or text == _UNCLASSIFIED_SENTINEL:
        return None
    return text


def resolve_category_fact_visibility(
    opportunities: Iterable[Dict[str, Any]],
    supply_facts: Iterable[Dict[str, Any]],
    *,
    procurement_id: Optional[int] = None,
    evidence_rows: Iterable[Dict[str, Any]] = (),
    object_scope_pids: Optional[Iterable[int]] = None,
) -> CategoryFactVisibility:
    """Resolve factual category/subcategory pairs from already-loaded rows."""
    from src.services.procurement_card_category_service import (
        build_category_cards,
    )

    all_opps = [dict(row) for row in opportunities or []]
    all_facts = [dict(row) for row in supply_facts or []]
    all_evidence = [dict(row) for row in evidence_rows or []]
    opps_by_pid: Dict[int, list[dict]] = {}
    facts_by_pid: Dict[int, list[dict]] = {}
    for opp in all_opps:
        pid = int(opp.get("procurement_id") or 0)
        if pid:
            opps_by_pid.setdefault(pid, []).append(opp)
    for fact in all_facts:
        pid = int(fact.get("procurement_id") or 0)
        if pid:
            facts_by_pid.setdefault(pid, []).append(fact)
    evidence_by_pid: Dict[int, list[dict]] = {}
    for evidence in all_evidence:
        if not _is_strong_material_evidence(evidence):
            continue
        pid = int(evidence.get("procurement_id") or 0)
        if pid:
            evidence_by_pid.setdefault(pid, []).append(evidence)

    pids = (
        {int(procurement_id)}
        if procurement_id is not None
        else set(opps_by_pid) | set(facts_by_pid) | set(evidence_by_pid)
    )
    opportunity_pairs: set[tuple[int, str, str]] = set()
    consumed_fact_pairs: set[tuple[int, str, str]] = set()
    fact_only_pairs: set[tuple[int, str, str]] = set()
    evidence_only_pairs: set[tuple[int, str, str]] = set()
    scope = (
        {int(pid) for pid in object_scope_pids}
        if object_scope_pids is not None
        else None
    )
    if scope is not None:
        scope.update(
            pid
            for pid, pid_opps in opps_by_pid.items()
            if any(
                str(opportunity.get("opportunity_track") or "").upper()
                != _DIRECT_SUPPLY
                for opportunity in pid_opps
            )
        )
    for pid in sorted(pids):
        opps = opps_by_pid.get(pid) or []
        facts = facts_by_pid.get(pid) or []
        if not opps or not facts:
            continue
        cards = build_category_cards(
            opportunities=opps,
            supply_facts=facts,
            documents=[],
            queue_progress={},
            procurement_id=pid,
            model_counts={},
            extraction_outcomes={},
        )
        for card in cards:
            category = str(card.get("category_code") or "").strip()
            subcategory = _clean_subcategory(card.get("subcategory_code"))
            track = str(card.get("track") or "").strip().upper()
            if not category:
                continue
            if track == _DIRECT_SUPPLY and not subcategory:
                continue
            if subcategory:
                opportunity_pairs.add((pid, category, subcategory))
            for product in card.get("products") or []:
                product_category = str(
                    product.get("category_code") or ""
                ).strip()
                product_subcategory = _clean_subcategory(
                    product.get("subcategory_code")
                )
                if product_category and product_subcategory:
                    consumed_fact_pairs.add(
                        (pid, product_category, product_subcategory)
                    )

    gate_pairs = opportunity_pairs | {
        (
            int(fact["procurement_id"]),
            str(fact.get("category_code") or "").strip(),
            _clean_subcategory(fact.get("subcategory_code")) or "",
        )
        for fact in all_facts
        if fact.get("category_code")
        and _clean_subcategory(fact.get("subcategory_code"))
    }
    for fact in all_facts:
        pid = int(fact.get("procurement_id") or 0)
        category = str(fact.get("category_code") or "").strip()
        subcategory = _clean_subcategory(fact.get("subcategory_code"))
        if not pid or not category or not subcategory:
            continue
        pair = (pid, category, subcategory)
        if (
            pair in opportunity_pairs
            or pair in consumed_fact_pairs
            or pair in fact_only_pairs
        ):
            continue
        if scope is not None and pid not in scope:
            continue
        fact_only_pairs.add(pair)

    for evidence in all_evidence:
        pid = int(evidence.get("procurement_id") or 0)
        category = str(evidence.get("category_code") or "").strip()
        subcategory = _clean_subcategory(evidence.get("subcategory_code"))
        if not pid or not category or not subcategory:
            continue
        pair = (pid, category, subcategory)
        if pair in gate_pairs:
            continue
        if scope is not None and pid not in scope:
            continue
        evidence_only_pairs.add(pair)

    visible_pair_set = (
        opportunity_pairs | fact_only_pairs | evidence_only_pairs
    )
    confirmed_values: dict[tuple[int, str, str], float] = {}
    for fact in all_facts:
        classification_row = dict(fact)
        if classification_row.get("quantity_value") is None:
            classification_row["quantity_value"] = classification_row.get(
                "quantity"
            )
        if not classification_row.get("quantity_unit_normalized"):
            classification_row["quantity_unit_normalized"] = (
                classification_row.get("unit")
            )
        if not classification_row.get("product_name_normalized"):
            classification_row["product_name_normalized"] = (
                classification_row.get("product_name_raw")
                or classification_row.get("material")
            )
        if classification_row.get("total_price_value") is None:
            classification_row["total_price_value"] = (
                classification_row.get("total")
            )
        if classify_supply_row(classification_row) is not None:
            continue
        pid = int(fact.get("procurement_id") or 0)
        category = str(fact.get("category_code") or "").strip()
        subcategory = _clean_subcategory(fact.get("subcategory_code"))
        if not pid or not category or not subcategory:
            continue
        pair = (pid, category, subcategory)
        if pair not in visible_pair_set:
            continue
        try:
            value = float(
                classification_row.get("total_price_value") or 0
            )
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        confirmed_values[pair] = confirmed_values.get(pair, 0.0) + value

    return CategoryFactVisibility(
        visible_pairs=frozenset(visible_pair_set),
        fact_only_pairs=frozenset(fact_only_pairs),
        evidence_only_pairs=frozenset(evidence_only_pairs),
        evidence_rows={
            pid: tuple(rows)
            for pid, rows in evidence_by_pid.items()
        },
        confirmed_goods_value_by_pair=confirmed_values,
        ok=True,
    )


resolve_composite_visibility = resolve_category_fact_visibility


def _load_supply_facts(conn, pids: Sequence[int]) -> list[dict]:
    if not pids:
        return []
    facts = []
    for row in load_good_supply_rows(conn, pids):
        if not _clean_subcategory(row.get("subcategory_code")):
            continue
        if classify_supply_row(row) is not None:
            continue
        facts.append(
            to_flat_fact(row) | {"procurement_id": row["procurement_id"]}
        )
    return facts


def _load_evidence_rows(conn, pids: Sequence[int]) -> list[dict]:
    if not pids:
        return []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH evidence_candidates AS (
                SELECT r.procurement_id, r.category_code, r.subcategory_code,
                       'PRODUCT'::text AS entity_type, r.name_raw AS product_name_raw,
                       coalesce(r.name_normalized, r.name_raw)
                           AS product_name_normalized,
                       r.quantity_value, r.unit_raw AS quantity_unit_raw,
                       r.unit_normalized AS quantity_unit_normalized,
                       r.unit_price_value, r.total_value AS total_price_value,
                       r.source_quote, r.row_ref AS row_or_line,
                       r.sheet_or_page AS page_or_sheet,
                       r.layout_status,
                       'ESTIMATE_ROW_RESOLVED'::text
                           AS structured_fact_trust_state,
                       r.row_kind, r.special_work_family,
                       COALESCE((
                         SELECT jsonb_agg(jsonb_build_object(
                                  'name', a->>'attribute_name',
                                  'name_normalized',
                                      a->>'attribute_name_normalized',
                                  'raw_value', a->>'raw_value',
                                  'normalized_value', a->>'normalized_value',
                                  'numeric_value',
                                      (a->>'numeric_value')::numeric,
                                  'unit',
                                      coalesce(a->>'unit_normalized',
                                               a->>'unit_raw'))
                                ORDER BY ordinality)
                           FROM jsonb_array_elements(
                                    r.technical_attributes)
                                WITH ORDINALITY AS attrs(a, ordinality)
                       ), '[]'::jsonb) AS attributes
                  FROM structured_estimate_rows r
                 WHERE r.procurement_id = ANY(%s)
                   AND r.category_code IS NOT NULL
                   AND coalesce(r.subcategory_code, '') <> ''
                   AND r.row_kind IN ('GOODS', 'SPECIAL_WORK_REVIEW')
                   AND coalesce(r.source_quote, '') <> ''
                   AND r.source_quote !~ 'ТЦ_'
                   AND (
                        r.row_kind = 'SPECIAL_WORK_REVIEW'
                        OR r.quantity_value IS NULL
                        OR coalesce(r.unit_normalized, '') = ''
                        OR r.total_value IS NULL
                   )
                UNION ALL
                SELECT se.procurement_id, se.category_code, se.subcategory_code,
                       se.entity_type, se.product_name_raw,
                       se.product_name_normalized, se.quantity_value,
                       se.quantity_unit_raw, se.quantity_unit_normalized,
                       se.unit_price_value, se.total_price_value,
                       se.source_quote, se.row_or_line, se.page_or_sheet,
                       se.layout_status,
                       se.structured_fact_trust_state,
                       NULL::text AS row_kind,
                       NULL::text AS special_work_family,
                       COALESCE((
                         SELECT jsonb_agg(jsonb_build_object(
                                  'name', a.attribute_name,
                                  'name_normalized', a.attribute_name_normalized,
                                  'raw_value', a.raw_value,
                                  'normalized_value', a.normalized_value,
                                  'numeric_value', a.numeric_value,
                                  'unit', a.unit_normalized)
                                ORDER BY a.id)
                           FROM structured_attributes a
                          WHERE a.entity_id = se.id
                       ), '[]'::jsonb)
                  FROM structured_entities se
                 WHERE se.entity_type = 'PRODUCT'
                   AND se.procurement_id = ANY(%s)
                   AND coalesce(se.category_code, '') NOT IN ('', 'unknown')
                   AND coalesce(se.subcategory_code, '') <> ''
                   AND coalesce(se.source_quote, '') <> ''
                   AND (
                        se.quantity_value IS NULL
                        OR coalesce(se.quantity_unit_normalized, '') = ''
                        OR se.total_price_value IS NULL
                   )
            )
            SELECT * FROM evidence_candidates
             ORDER BY procurement_id, category_code, subcategory_code, product_name_raw
            """,
            (list(pids), list(pids)),
        )
        rows = [dict(row) for row in cur.fetchall()]
    evidence: list[dict] = []
    seen: set[tuple] = set()
    for row in rows:
        reason = classify_supply_row(row)
        special_work = str(row.get("row_kind") or "") == "SPECIAL_WORK_REVIEW"
        if reason not in _EVIDENCE_REASONS and not special_work:
            continue
        if special_work:
            reason = "special_work_review"
        if not _is_strong_material_evidence(row):
            continue
        name = row.get("product_name_normalized") or row.get("product_name_raw")
        key = (
            int(row["procurement_id"]),
            str(row.get("category_code") or ""),
            str(row.get("subcategory_code") or ""),
            str(name or ""),
            str(row.get("row_or_line") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        evidence.append(
            {
                **row,
                "material": name,
                "quantity": row.get("quantity_value"),
                "unit": row.get("quantity_unit_normalized")
                or row.get("quantity_unit_raw"),
                "unit_price": row.get("unit_price_value"),
                "total": row.get("total_price_value"),
                "evidence_only": True,
                "evidence_reason": reason,
            }
        )
    return evidence


def _load_object_scope_pids(
    crm_db: Any = None,
    crm_cursor: Any = None,
    procurement_id: Optional[int] = None,
) -> list[int]:
    query = """
        SELECT procurement_id
          FROM crm_procurement_scope_authority
         WHERE admission_state = 'ELIGIBLE'
           AND procurement_scope_type = ANY(%s)
    """
    params: tuple[Any, ...] = (list(_OBJECT_SCOPE_TYPES),)
    if procurement_id is not None:
        query += " AND procurement_id = %s"
        params += (int(procurement_id),)
    if crm_cursor is not None:
        crm_cursor.execute(query, params)
        rows = crm_cursor.fetchall()
    elif crm_db is not None:
        rows = crm_db.execute_query(query, params) or []
    else:
        return []
    return sorted({
        int(row["procurement_id"])
        for row in rows
        if row.get("procurement_id")
    })


def _doc_connection():
    from src.services.doc_db_runtime import require_doc_db_connect_kwargs

    kwargs = dict(require_doc_db_connect_kwargs())
    kwargs["connect_timeout"] = 5
    return psycopg2.connect(**kwargs)


def load_category_fact_visibility(
    crm_db: Any = None,
    *,
    crm_cursor: Any = None,
    doc_conn: Any = None,
    procurement_id: Optional[int] = None,
) -> CategoryFactVisibility:
    """Load factual visibility globally or for one procurement dossier."""
    own_doc = doc_conn is None
    try:
        query = """
            SELECT procurement_id, commercial_category_code,
                   commercial_subcategory_code, opportunity_track,
                   status, candidate_initial_score,
                   candidate_initial_medal, confirmed_base_score,
                   confirmed_base_medal, current_effective_score,
                   current_effective_medal, current_effective_reason
              FROM crm_procurement_category_opportunities
             WHERE status = 'CURRENT'
        """
        params: tuple[Any, ...] = ()
        if procurement_id is not None:
            query += " AND procurement_id = %s"
            params = (int(procurement_id),)
        if crm_cursor is not None:
            crm_cursor.execute(query, params)
            opportunities = [dict(row) for row in crm_cursor.fetchall()]
        elif crm_db is not None:
            opportunities = [
                dict(row)
                for row in (crm_db.execute_query(query, params) or [])
            ]
        else:
            raise ValueError("crm_db or crm_cursor is required")

        object_scope_pids = _load_object_scope_pids(
            crm_db=crm_db,
            crm_cursor=crm_cursor,
            procurement_id=procurement_id,
        )
        opportunity_pids = {
            int(row["procurement_id"])
            for row in opportunities
            if row.get("procurement_id")
        }
        if procurement_id is not None:
            opportunity_pids &= {int(procurement_id)}
        value_pids = sorted(set(object_scope_pids) | opportunity_pids)
        conn = doc_conn or _doc_connection()
        try:
            facts = _load_supply_facts(conn, value_pids)
            evidence_rows = _load_evidence_rows(conn, object_scope_pids)
        finally:
            if own_doc:
                conn.close()
        return resolve_category_fact_visibility(
            opportunities,
            facts,
            procurement_id=procurement_id,
            evidence_rows=evidence_rows,
            object_scope_pids=object_scope_pids,
        )
    except Exception as exc:
        return CategoryFactVisibility(
            visible_pairs=frozenset(),
            fact_only_pairs=frozenset(),
            evidence_only_pairs=frozenset(),
            evidence_rows={},
            confirmed_goods_value_by_pair={},
            ok=False,
            reason=str(exc),
        )


load_composite_visibility = load_category_fact_visibility


def visibility_sql_params(
    visibility: CategoryFactVisibility,
) -> tuple[list[int], list[str], list[str]]:
    pairs = sorted(visibility.visible_pairs)
    return (
        [pid for pid, _category, _subcategory in pairs],
        [category for _pid, category, _subcategory in pairs],
        [subcategory for _pid, _category, subcategory in pairs],
    )


def synthetic_visibility_sql_params(
    visibility: CategoryFactVisibility,
) -> tuple[list[int], list[str], list[str], list[bool]]:
    pairs = sorted(
        visibility.fact_only_pairs | visibility.evidence_only_pairs
    )
    return (
        [pid for pid, _category, _subcategory in pairs],
        [category for _pid, category, _subcategory in pairs],
        [subcategory for _pid, _category, subcategory in pairs],
        [pair in visibility.evidence_only_pairs for pair in pairs],
    )


def synthetic_visibility_cte_sql(name: str = "synthetic_facts") -> str:
    return (
        f"{name}(procurement_id, category_code, subcategory_code, evidence_only) "
        "AS (SELECT * FROM unnest(%s::bigint[], %s::text[], %s::text[], "
        "%s::boolean[]))"
    )


def synthetic_visibility_named_cte_sql(
    name: str = "synthetic_facts",
    param_name: str = "synthetic_facts",
) -> str:
    return (
        f"{name}(procurement_id, category_code, subcategory_code, evidence_only) "
        f"AS (SELECT * FROM unnest(%({param_name}_pids)s::bigint[], "
        f"%({param_name}_categories)s::text[], "
        f"%({param_name}_subcategories)s::text[], "
        f"%({param_name}_evidence)s::boolean[]))"
    )


def visibility_cte_sql(name: str = "visible_facts") -> str:
    return (
        f"{name}(procurement_id, category_code, subcategory_code) AS ("
        "SELECT * FROM unnest(%s::bigint[], %s::text[], %s::text[])"
        ")"
    )


def visibility_named_cte_sql(
    name: str = "visible_facts",
    param_name: str = "visible_facts",
) -> str:
    return (
        f"{name}(procurement_id, category_code, subcategory_code) AS ("
        f"SELECT * FROM unnest(%({param_name}_pids)s::bigint[], "
        f"%({param_name}_categories)s::text[], "
        f"%({param_name}_subcategories)s::text[])"
        ")"
    )


def visible_fact_exists_sql(
    alias: str,
    *,
    cte_name: str = "visible_facts",
) -> str:
    return (
        f"EXISTS (SELECT 1 FROM {cte_name} vf "
        f"WHERE vf.procurement_id = {alias}.procurement_id "
        f"AND vf.category_code = {alias}.commercial_category_code)"
    )
