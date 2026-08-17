"""Select exactly four real golden procurements and define reference labels BEFORE Qwen."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from src.services.commercial_routing_v3.okpd_priors import match_okpd_priors
from src.services.commercial_routing_v3.procurement_form import classify_procurement_form

MAX_CASES = 4


@dataclass
class ReferenceExpectation:
    case_key: str
    case_label: str
    procurement_id: int
    contract_number: Optional[str]
    auction_name: str
    okpd_code: str
    okpd_name: str
    expected_category: str
    expected_tracks: List[str]
    expected_form_hint: str
    expected_subcategory: str = "SUBCATEGORY_NOT_ASSIGNED"
    expected_medal_range: List[str] = field(default_factory=lambda: ["GOLD", "SILVER", "BRONZE", "WOOD"])
    selection_score: float = 0.0
    selection_rationale: str = ""
    prior_hits: List[Dict[str, Any]] = field(default_factory=list)
    source_table: str = ""
    source_id: Any = None
    initial_price: float = 0.0
    customer: str = ""
    crm_stage: str = ""
    award_status: str = ""
    defined_at: str = ""
    before_qwen: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _row_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _fetch_candidates(crm_db, sql: str, params: Sequence[Any] | None = None) -> List[Dict[str, Any]]:
    rows = crm_db.execute_query(sql, params) if params is not None else crm_db.execute_query(sql)
    return [_row_dict(r) for r in (rows or [])]


def _score_lighting(r: Dict[str, Any]) -> tuple[float, str]:
    title = (r.get("auction_name") or "").lower()
    okpd = (r.get("okpd_code") or "")
    okpd_name = (r.get("okpd_name") or "").lower()
    score = 0.0
    reasons = []
    if okpd.startswith("27.40"):
        score += 40
        reasons.append("okpd_27.40")
    if "поставк" in title:
        score += 25
        reasons.append("title_supply")
    if any(w in title for w in ("светильн", "освещ", "светодиод", "прожектор")):
        score += 25
        reasons.append("title_lighting")
    if any(w in okpd_name for w in ("свет", "осветительн", "прожектор")):
        score += 10
        reasons.append("okpd_name_lighting")
    if "отоплен" in title:
        score -= 50
        reasons.append("neg_heating")
    if "ремонт" in title and "поставк" not in title:
        score -= 20
    return score, ",".join(reasons)


def _score_computers(r: Dict[str, Any]) -> tuple[float, str]:
    title = (r.get("auction_name") or "").lower()
    okpd = (r.get("okpd_code") or "")
    score = 0.0
    reasons = []
    if okpd.startswith("26.20") or okpd.startswith("26.2"):
        score += 40
        reasons.append("okpd_26.20")
    if "поставк" in title or "закупк" in title:
        score += 20
        reasons.append("title_supply")
    if any(w in title for w in ("компьютер", "ноутбук", "моноблок", "сервер", "рабоч", "пк ", " пк")):
        score += 30
        reasons.append("title_computers")
    if any(w in title for w in ("медицин", "томограф", "мрт")):
        score -= 40
        reasons.append("neg_medical")
    return score, ",".join(reasons)


def _score_embedded(r: Dict[str, Any]) -> tuple[float, str]:
    title = (r.get("auction_name") or "").lower()
    okpd = (r.get("okpd_code") or "")
    form = classify_procurement_form(
        {
            "auction_name": r.get("auction_name"),
            "okpd_code": okpd,
            "okpd_name": r.get("okpd_name"),
        }
    )
    score = 0.0
    reasons = []
    if okpd.startswith(("41.", "42.", "43.")):
        score += 30
        reasons.append("okpd_construction")
    if form.value == "CONSTRUCTION_WORKS":
        score += 25
        reasons.append("form_construction")
    if any(w in title for w in ("строительств", "реконструкц", "капитальн", "ремонт", "благоустройств")):
        score += 20
        reasons.append("title_works")
    # plausible material opportunity signals (not category proof)
    if any(w in title for w in ("гидроизол", "кровл", "фасад", "освещ", "кабель", "дренаж", "водоотвод")):
        score += 15
        reasons.append("material_hint")
    if "поставк" in title and not any(w in title for w in ("работ", "строительств", "ремонт")):
        score -= 30
        reasons.append("looks_like_goods")
    return score, ",".join(reasons)


def _score_design(r: Dict[str, Any]) -> tuple[float, str]:
    title = (r.get("auction_name") or "").lower()
    okpd = (r.get("okpd_code") or "")
    form = classify_procurement_form(
        {
            "auction_name": r.get("auction_name"),
            "okpd_code": okpd,
            "okpd_name": r.get("okpd_name"),
        }
    )
    score = 0.0
    reasons = []
    if okpd.startswith(("71.", "74.")):
        score += 30
        reasons.append("okpd_design")
    if form.value in ("DESIGN_ONLY", "SURVEY_AND_DESIGN", "DESIGN_AND_BUILD", "DESIGN_EXPERTISE_AND_BUILD"):
        score += 30
        reasons.append(f"form_{form.value}")
    if any(
        w in title
        for w in (
            "проектн",
            "проектирован",
            "пир",
            "изыскан",
            "рабоч",
            "сметн",
            "архитектур",
        )
    ):
        score += 25
        reasons.append("title_design")
    if "поставк" in title and "проект" not in title:
        score -= 40
        reasons.append("goods_disguise")
    return score, ",".join(reasons)


def _pick_best(
    crm_db,
    *,
    sql: str,
    scorer,
    case_key: str,
    case_label: str,
    expected_category: str,
    expected_tracks: List[str],
    expected_form_hint: str,
    priors: List[Dict[str, Any]],
    exclude_ids: set,
) -> ReferenceExpectation:
    cands = _fetch_candidates(crm_db, sql)
    ranked = []
    for r in cands:
        pid = int(r["id"])
        if pid in exclude_ids:
            continue
        score, rationale = scorer(r)
        ranked.append((score, rationale, r))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 40:
        raise RuntimeError(f"NO_QUALITY_CANDIDATE:{case_key}")
    score, rationale, r = ranked[0]
    okpd = str(r.get("okpd_code") or "")
    prior_hits = [
        {
            "commercial_category_code": p.get("commercial_category_code"),
            "okpd_pattern": p.get("okpd_pattern"),
            "prior_weight": p.get("prior_weight"),
        }
        for p in match_okpd_priors(okpd, priors)
    ]
    return ReferenceExpectation(
        case_key=case_key,
        case_label=case_label,
        procurement_id=int(r["id"]),
        contract_number=r.get("contract_number"),
        auction_name=str(r.get("auction_name") or ""),
        okpd_code=okpd,
        okpd_name=str(r.get("okpd_name") or ""),
        expected_category=expected_category,
        expected_tracks=list(expected_tracks),
        expected_form_hint=expected_form_hint,
        expected_subcategory="SUBCATEGORY_NOT_ASSIGNED",
        expected_medal_range=["GOLD", "SILVER", "BRONZE", "WOOD"],
        selection_score=float(score),
        selection_rationale=rationale,
        prior_hits=prior_hits,
        source_table=str(r.get("source_table") or ""),
        source_id=r.get("source_id"),
        initial_price=float(r.get("initial_price") or 0),
        customer=str(r.get("customer_name") or r.get("organizer_name") or r.get("customer") or ""),
        crm_stage=str(r.get("crm_stage") or ""),
        award_status=str(r.get("award_status") or r.get("status") or ""),
        defined_at=datetime.now(timezone.utc).isoformat(),
        before_qwen=True,
    )


def select_four_reference_cases(crm_db, priors: Optional[List[Dict[str, Any]]] = None) -> List[ReferenceExpectation]:
    """Select exactly 4 real cases and define expectations BEFORE any model call."""
    from src.services.commercial_routing_v3.engine import _DEFAULT_OKPD_PRIORS

    priors = priors if priors is not None else _DEFAULT_OKPD_PRIORS
    exclude: set = set()
    cases: List[ReferenceExpectation] = []

    a = _pick_best(
        crm_db,
        sql="""
        SELECT id, contract_number, auction_name, okpd_code, okpd_name, initial_price, crm_stage,
               source_table, source_id
        FROM crm_procurements
        WHERE coalesce(okpd_code,'') LIKE '27.40%%'
          AND auction_name ILIKE '%%поставк%%'
          AND (
            auction_name ILIKE '%%свет%%'
            OR auction_name ILIKE '%%светильн%%'
            OR auction_name ILIKE '%%освещ%%'
            OR auction_name ILIKE '%%прожектор%%'
            OR coalesce(okpd_name,'') ILIKE '%%свет%%'
          )
          AND auction_name NOT ILIKE '%%отоплен%%'
        ORDER BY id DESC
        LIMIT 80
        """,
        scorer=_score_lighting,
        case_key="A_DIRECT_LIGHTING",
        case_label="DIRECT LIGHTING",
        expected_category="lighting",
        expected_tracks=["DIRECT_SUPPLY"],
        expected_form_hint="DIRECT_GOODS_PURCHASE",
        priors=priors,
        exclude_ids=exclude,
    )
    exclude.add(a.procurement_id)
    cases.append(a)

    b = _pick_best(
        crm_db,
        sql="""
        SELECT id, contract_number, auction_name, okpd_code, okpd_name, initial_price, crm_stage,
               source_table, source_id
        FROM crm_procurements
        WHERE (coalesce(okpd_code,'') LIKE '26.20%%' OR coalesce(okpd_code,'') LIKE '26.2.%%')
          AND (
            auction_name ILIKE '%%компьютер%%'
            OR auction_name ILIKE '%%ноутбук%%'
            OR auction_name ILIKE '%%моноблок%%'
            OR auction_name ILIKE '%%сервер%%'
            OR auction_name ILIKE '%%рабоч%%мест%%'
          )
          AND (auction_name ILIKE '%%поставк%%' OR auction_name ILIKE '%%закупк%%')
          AND auction_name NOT ILIKE '%%медицин%%'
        ORDER BY id DESC
        LIMIT 80
        """,
        scorer=_score_computers,
        case_key="B_DIRECT_COMPUTERS",
        case_label="DIRECT COMPUTERS",
        expected_category="computers",
        expected_tracks=["DIRECT_SUPPLY"],
        expected_form_hint="DIRECT_GOODS_PURCHASE",
        priors=priors,
        exclude_ids=exclude,
    )
    exclude.add(b.procurement_id)
    cases.append(b)

    c = _pick_best(
        crm_db,
        sql="""
        SELECT id, contract_number, auction_name, okpd_code, okpd_name, initial_price, crm_stage,
               source_table, source_id
        FROM crm_procurements
        WHERE (
              coalesce(okpd_code,'') LIKE '41.%%'
           OR coalesce(okpd_code,'') LIKE '42.%%'
           OR coalesce(okpd_code,'') LIKE '43.%%'
        )
          AND (
            auction_name ILIKE '%%строительств%%'
            OR auction_name ILIKE '%%реконструкц%%'
            OR auction_name ILIKE '%%капитальн%%'
            OR auction_name ILIKE '%%ремонт%%'
            OR auction_name ILIKE '%%благоустройств%%'
          )
          AND auction_name NOT ILIKE '%%поставка %%'
        ORDER BY id DESC
        LIMIT 120
        """,
        scorer=_score_embedded,
        case_key="C_CONSTRUCTION_EMBEDDED",
        case_label="CONSTRUCTION + EMBEDDED MATERIAL",
        expected_category="*",  # any commercial keep category with EMBEDDED track
        expected_tracks=["EMBEDDED_MATERIAL"],
        expected_form_hint="CONSTRUCTION_WORKS",
        priors=priors,
        exclude_ids=exclude,
    )
    exclude.add(c.procurement_id)
    cases.append(c)

    d = _pick_best(
        crm_db,
        sql="""
        SELECT id, contract_number, auction_name, okpd_code, okpd_name, initial_price, crm_stage,
               source_table, source_id
        FROM crm_procurements
        WHERE (
              coalesce(okpd_code,'') LIKE '71.%%'
           OR coalesce(okpd_code,'') LIKE '74.%%'
           OR auction_name ILIKE '%%проектн%%'
           OR auction_name ILIKE '%%проектирован%%'
           OR auction_name ILIKE '%%изыскан%%'
           OR auction_name ILIKE '%%ПИР%%'
        )
          AND auction_name NOT ILIKE '%%поставка товар%%'
          AND auction_name NOT ILIKE '%%поставка компьютер%%'
        ORDER BY id DESC
        LIMIT 120
        """,
        scorer=_score_design,
        case_key="D_DESIGN_PIR",
        case_label="DESIGN / PIR",
        expected_category="*",
        expected_tracks=["DESIGN_REQUIREMENT", "DESIGN_INFLUENCE"],
        expected_form_hint="DESIGN_*",
        priors=priors,
        exclude_ids=exclude,
    )
    exclude.add(d.procurement_id)
    cases.append(d)

    if len(cases) != MAX_CASES:
        raise RuntimeError(f"EXPECTED_{MAX_CASES}_CASES_GOT_{len(cases)}")
    return cases


def load_procurement_for_routing(crm_db, procurement_id: int) -> Dict[str, Any]:
    rows = crm_db.execute_query(
        """
        SELECT id, contract_number, auction_name, okpd_code, okpd_name,
               initial_price, source_table, source_id, crm_stage
        FROM crm_procurements WHERE id = %s
        """,
        (procurement_id,),
    )
    if not rows:
        raise RuntimeError(f"PROCUREMENT_NOT_FOUND:{procurement_id}")
    r = _row_dict(rows[0])
    # optional customer columns if present in wider SELECT attempts
    customer = ""
    for col in ("customer_name", "organizer_name", "customer", "winner_name"):
        if col in r and r.get(col):
            customer = str(r.get(col) or "")
            break
    return {
        "id": int(r["id"]),
        "procurement_id": int(r["id"]),
        "contract_number": r.get("contract_number"),
        "title": r.get("auction_name"),
        "auction_name": r.get("auction_name"),
        "okpd_code": r.get("okpd_code") or "",
        "okpd_name": r.get("okpd_name") or "",
        "price": float(r.get("initial_price") or 0),
        "initial_price": float(r.get("initial_price") or 0),
        "source_table": r.get("source_table") or "",
        "source_id": r.get("source_id"),
        "crm_stage": r.get("crm_stage"),
        "customer": customer,
        "customer_name": customer,
    }
