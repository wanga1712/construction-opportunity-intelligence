"""OKPD-centric analytics aggregates (Level-A + prepared priors).

Runs inside V3AnalyticsRefreshService only — not on Streamlit rerun.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.services.commercial_routing_v3.legacy_okpd_knowledge import normalize_okpd_code
from src.services.v3_analytics_metric_state import MetricState

ANALYTICS_CACHE_SUPPORTS_OKPD = True
ANALYTICS_CACHE_SUPPORTS_SUBCATEGORY = True
ANALYTICS_OKPD_CACHE_IS_AGGREGATE_ONLY = True
RAW_CATEGORY_CODE_AS_PRIMARY_LABEL = False
SUBCATEGORY_NOT_ASSIGNED = "SUBCATEGORY_NOT_ASSIGNED"
SUBCATEGORY_NOT_ASSIGNED_LABEL_RU = "Подкатегория не определена"

NOT_STARTED = "NOT_STARTED"
NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass
class OkpdFunnelRow:
    okpd_code: str
    okpd_name: str = ""
    source_received: int = 0
    source_44: int = 0
    source_223: int = 0
    source_waiting: int = 0
    technically_eligible: int = 0
    technically_rejected: int = 0
    reject_missing_identity: int = 0
    reject_malformed: int = 0
    reject_unsupported: int = 0
    reject_true_duplicate: int = 0
    reject_other: int = 0
    title_negative_signal: Any = NOT_STARTED  # soft; not a drop
    hard_excluded: Any = NOT_STARTED
    projected_to_crm: int = 0
    pending_routing: Any = NOT_STARTED
    routed: Any = NOT_STARTED
    with_opportunities: Any = NOT_STARTED
    no_opportunity: Any = NOT_STARTED
    discovery_required: Any = NOT_STARTED
    review_required: Any = NOT_STARTED
    candidate_gold: Any = NOT_STARTED
    candidate_silver: Any = NOT_STARTED
    candidate_bronze: Any = NOT_STARTED
    candidate_wood: Any = NOT_STARTED
    prepared_prior_categories: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _scalar_rows(
    db,
    sql: str,
    params: Any = None,
    *,
    columns: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Normalize DB rows to dicts (CRM=dicts, tender source=tuples)."""
    try:
        rows = db.execute_query(sql, params) if params is not None else db.execute_query(sql)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(dict(r))
        elif columns is not None:
            out.append({columns[i]: r[i] for i in range(min(len(columns), len(r)))})
        else:
            out.append({"_0": r[0]})
    return out


def _agg_source_okpd(tender_db, table: str, contour: str) -> Dict[str, Dict[str, Any]]:
    """Grouped source counts by normalized OKPD text via collection_codes_okpd."""
    # collection_codes_okpd uses main_code/sub_code (not `code`)
    sql = f"""
        SELECT
          COALESCE(
            NULLIF(
              btrim(
                CASE
                  WHEN o.sub_code IS NOT NULL AND btrim(o.sub_code) <> '' THEN
                    CASE
                      WHEN o.main_code IS NOT NULL
                           AND (
                             btrim(o.sub_code) LIKE btrim(o.main_code) || '.%%'
                             OR btrim(o.sub_code) LIKE btrim(o.main_code) || '%%'
                           )
                      THEN btrim(o.sub_code)
                      WHEN o.main_code IS NOT NULL AND btrim(o.main_code) <> ''
                      THEN btrim(o.main_code) || '.' || btrim(o.sub_code)
                      ELSE btrim(o.sub_code)
                    END
                  WHEN o.main_code IS NOT NULL AND btrim(o.main_code) <> ''
                  THEN btrim(o.main_code)
                  ELSE NULL
                END
              ),
              ''
            ),
            '(null)'
          ) AS okpd_code,
          max(COALESCE(o.name, '')) AS okpd_name,
          count(*) AS received,
          count(*) FILTER (
            WHERE r.contract_number IS NOT NULL AND btrim(r.contract_number::text) <> ''
          ) AS eligible,
          count(*) FILTER (
            WHERE r.contract_number IS NULL OR btrim(r.contract_number::text) = ''
          ) AS missing_identity
        FROM {table} r
        LEFT JOIN collection_codes_okpd o ON o.id = r.okpd_id
        GROUP BY 1
    """
    out: Dict[str, Dict[str, Any]] = {}
    for row in _scalar_rows(
        tender_db,
        sql,
        columns=("okpd_code", "okpd_name", "received", "eligible", "missing_identity"),
    ):
        disp = str(row.get("okpd_code") or "(null)")
        key = disp
        bucket = out.setdefault(
            key,
            {
                "okpd_code": disp,
                "okpd_name": str(row.get("okpd_name") or ""),
                "received": 0,
                "eligible": 0,
                "missing_identity": 0,
                "source_44": 0,
                "source_223": 0,
                "waiting": 0,
            },
        )
        n = int(row.get("received") or 0)
        el = int(row.get("eligible") or 0)
        mi = int(row.get("missing_identity") or 0)
        bucket["received"] += n
        bucket["eligible"] += el
        bucket["missing_identity"] += mi
        if row.get("okpd_name") and not bucket["okpd_name"]:
            bucket["okpd_name"] = str(row["okpd_name"])
        if contour == "44":
            bucket["source_44"] += n
        elif contour == "223":
            bucket["source_223"] += n
    return out


def _agg_crm_okpd(crm_db) -> Dict[str, Dict[str, Any]]:
    sql = """
        SELECT
          COALESCE(NULLIF(btrim(okpd_code), ''), '(null)') AS okpd_code,
          max(COALESCE(okpd_name, '')) AS okpd_name,
          count(*) AS projected,
          count(*) FILTER (WHERE source_table ILIKE '%44%') AS c44,
          count(*) FILTER (WHERE source_table ILIKE '%223%') AS c223
        FROM crm_procurements
        GROUP BY 1
    """
    out: Dict[str, Dict[str, Any]] = {}
    for row in _scalar_rows(crm_db, sql):
        key = str(row.get("okpd_code") or "(null)")
        out[key] = {
            "okpd_code": key,
            "okpd_name": str(row.get("okpd_name") or ""),
            "projected": int(row.get("projected") or 0),
            "c44": int(row.get("c44") or 0),
            "c223": int(row.get("c223") or 0),
        }
    return out


def load_prepared_okpd_prior_index(project_root: Optional[Path] = None) -> Dict[str, List[Dict[str, str]]]:
    """Map okpd_pattern → list of {code, display_name} from seed SQL (PREPARED, not AI)."""
    root = project_root or Path(__file__).resolve().parents[2]
    seed = root / "src" / "migrations" / "commercial_routing_v3_seed.sql"
    taxonomy = root / "src" / "migrations" / "commercial_taxonomy_seed_1.sql"
    names: Dict[str, str] = {}
    # category display names from taxonomy seed INSERT values and live defaults
    default_names = {
        "lighting": "Освещение",
        "waterproofing": "Гидроизоляция",
        "drainage_water_management": "Водоотведение",
        "curbstone": "Бордюрный камень",
        "composite_structures": "Композитные конструкции",
        "flooring": "Напольные покрытия",
        "computers": "Компьютеры",
        "cable_support_systems": "Кабеленесущие системы",
        "concrete_repair_materials": "Материалы для ремонта бетона",
    }
    names.update(default_names)
    if taxonomy.is_file():
        text = taxonomy.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
            r"'(?P<code>[a-z0-9_]+)',\s*'(?P<name>[^']+)'",
            text,
        ):
            # noisy; only keep known family codes
            if m.group("code") in default_names or m.group("code").endswith("_materials"):
                names[m.group("code")] = m.group("name")

    index: Dict[str, List[Dict[str, str]]] = {}
    if not seed.is_file():
        return index
    text = seed.read_text(encoding="utf-8", errors="ignore")
    for m in re.finditer(
        r"\('(?P<cat>[a-z0-9_]+)',\s*'(?P<pat>[0-9.]+)',\s*'(?P<mt>PREFIX|EXACT)'",
        text,
    ):
        cat = m.group("cat")
        pat = normalize_okpd_code(m.group("pat"))
        index.setdefault(pat, []).append(
            {
                "category_code": cat,
                "display_name": names.get(cat, cat),
                "match_type": m.group("mt"),
                "label": "PREPARED PRIOR",
            }
        )
    return index


def match_prepared_priors(okpd_code: str, prior_index: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, str]]:
    code = normalize_okpd_code(okpd_code)
    if not code or code == "(null)":
        return []
    hits: List[Dict[str, str]] = []
    seen = set()
    # exact then prefix patterns (longest first)
    patterns = sorted(prior_index.keys(), key=len, reverse=True)
    for pat in patterns:
        if code == pat or code.startswith(pat + ".") or (pat and code.startswith(pat)):
            for item in prior_index[pat]:
                key = item["category_code"]
                if key in seen:
                    continue
                seen.add(key)
                hits.append(dict(item))
    return hits


def load_category_subcategory_registry(crm_db=None, project_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Dynamic registry rows with display names. Falls back to seed constants."""
    rows: List[Dict[str, Any]] = []
    if crm_db is not None:
        try:
            q = """
                SELECT c.category_code,
                       c.category_name,
                       s.subcategory_code,
                       s.subcategory_name,
                       COALESCE(c.is_active, TRUE) AS cat_active,
                       COALESCE(s.is_active, TRUE) AS sub_active
                FROM crm_product_categories c
                LEFT JOIN crm_product_subcategories s ON s.category_id = c.id
                ORDER BY c.sort_order NULLS LAST, c.category_code, s.sort_order NULLS LAST
            """
            for r in _scalar_rows(crm_db, q):
                rows.append(
                    {
                        "category_code": r.get("category_code"),
                        "category_display_name": r.get("category_name") or r.get("category_code"),
                        "subcategory_code": r.get("subcategory_code"),
                        "subcategory_display_name": r.get("subcategory_name"),
                        "cat_active": bool(r.get("cat_active", True)),
                        "sub_active": bool(r.get("sub_active", True)),
                    }
                )
            if rows:
                return rows
        except Exception:
            pass
    # prepared fallback from report coverage + default names
    from src.services.v3_analytics_precutover import load_prepared_configuration

    prep = load_prepared_configuration(project_root)
    for c in prep.get("category_coverage") or []:
        code = c.get("category_code")
        rows.append(
            {
                "category_code": code,
                "category_display_name": {
                    "lighting": "Освещение",
                    "computers": "Компьютеры",
                    "waterproofing": "Гидроизоляция",
                    "cable_support_systems": "Кабеленесущие системы",
                    "composite_structures": "Композитные конструкции",
                    "curbstone": "Бордюрный камень",
                    "drainage_water_management": "Водоотведение",
                    "flooring": "Напольные покрытия",
                    "concrete_repair_materials": "Материалы для ремонта бетона",
                }.get(code, code),
                "subcategory_code": None,
                "subcategory_display_name": None,
                "okpd_priors": c.get("total_okpd_priors", 0),
            }
        )
    return rows


def build_okpd_funnel_level_a(
    tender_db,
    crm_db,
    *,
    project_root: Optional[Path] = None,
    contour: str = "ALL",
) -> Tuple[List[OkpdFunnelRow], Dict[str, Any]]:
    """Aggregate OKPD funnel Level-A. Returns (rows, meta)."""
    t0 = time.perf_counter()
    buckets: Dict[str, Dict[str, Any]] = {}

    def merge(src: Dict[str, Dict[str, Any]], *, waiting: bool = False) -> None:
        for key, b in src.items():
            dst = buckets.setdefault(
                key,
                {
                    "okpd_code": key,
                    "okpd_name": "",
                    "received": 0,
                    "eligible": 0,
                    "missing_identity": 0,
                    "source_44": 0,
                    "source_223": 0,
                    "waiting": 0,
                    "projected": 0,
                },
            )
            dst["received"] += int(b.get("received") or 0)
            dst["eligible"] += int(b.get("eligible") or 0)
            dst["missing_identity"] += int(b.get("missing_identity") or 0)
            dst["source_44"] += int(b.get("source_44") or 0)
            dst["source_223"] += int(b.get("source_223") or 0)
            dst["waiting"] += int(b.get("waiting") or 0)
            if b.get("okpd_name"):
                dst["okpd_name"] = b["okpd_name"]

    if tender_db:
        if contour in ("ALL", "44"):
            merge(_agg_source_okpd(tender_db, "reestr_contract_44_fz", "44"))
            for k, b in _agg_source_okpd(
                tender_db, "reestr_contract_44_fz_commission_work", "WAITING"
            ).items():
                dst = buckets.setdefault(
                    k,
                    {
                        "okpd_code": k,
                        "okpd_name": "",
                        "received": 0,
                        "eligible": 0,
                        "missing_identity": 0,
                        "source_44": 0,
                        "source_223": 0,
                        "waiting": 0,
                        "projected": 0,
                    },
                )
                n = int(b.get("received") or 0)
                dst["received"] += n
                dst["eligible"] += int(b.get("eligible") or 0)
                dst["missing_identity"] += int(b.get("missing_identity") or 0)
                dst["waiting"] += n
                dst["source_44"] += n
                if b.get("okpd_name"):
                    dst["okpd_name"] = b["okpd_name"]
        if contour in ("ALL", "223"):
            merge(_agg_source_okpd(tender_db, "reestr_contract_223_fz", "223"))
            for k, b in _agg_source_okpd(
                tender_db, "reestr_contract_223_fz_commission_work", "WAITING"
            ).items():
                dst = buckets.setdefault(
                    k,
                    {
                        "okpd_code": k,
                        "okpd_name": "",
                        "received": 0,
                        "eligible": 0,
                        "missing_identity": 0,
                        "source_44": 0,
                        "source_223": 0,
                        "waiting": 0,
                        "projected": 0,
                    },
                )
                n = int(b.get("received") or 0)
                dst["received"] += n
                dst["eligible"] += int(b.get("eligible") or 0)
                dst["missing_identity"] += int(b.get("missing_identity") or 0)
                dst["waiting"] += n
                dst["source_223"] += n
                if b.get("okpd_name"):
                    dst["okpd_name"] = b["okpd_name"]

    if crm_db:
        for k, b in _agg_crm_okpd(crm_db).items():
            dst = buckets.setdefault(
                k,
                {
                    "okpd_code": k,
                    "okpd_name": b.get("okpd_name") or "",
                    "received": 0,
                    "eligible": 0,
                    "missing_identity": 0,
                    "source_44": 0,
                    "source_223": 0,
                    "waiting": 0,
                    "projected": 0,
                },
            )
            dst["projected"] = int(b.get("projected") or 0)
            if b.get("okpd_name"):
                dst["okpd_name"] = b["okpd_name"]

    prior_index = load_prepared_okpd_prior_index(project_root)
    rows: List[OkpdFunnelRow] = []
    for key, b in buckets.items():
        received = int(b.get("received") or 0)
        eligible = int(b.get("eligible") or 0)
        missing = int(b.get("missing_identity") or 0)
        # Technical reject ≈ missing identity for Level-A (no NOT_INTERESTING)
        rejected = missing
        projected = int(b.get("projected") or 0)
        row = OkpdFunnelRow(
            okpd_code=str(b.get("okpd_code") or key),
            okpd_name=str(b.get("okpd_name") or ""),
            source_received=received,
            source_44=int(b.get("source_44") or 0),
            source_223=int(b.get("source_223") or 0),
            source_waiting=int(b.get("waiting") or 0),
            technically_eligible=eligible,
            technically_rejected=rejected,
            reject_missing_identity=missing,
            reject_malformed=0,
            reject_unsupported=0,
            reject_true_duplicate=0,
            reject_other=max(0, rejected - missing),
            title_negative_signal=NOT_STARTED,
            hard_excluded=NOT_STARTED,
            projected_to_crm=projected,
            pending_routing=NOT_STARTED,
            routed=NOT_STARTED,
            with_opportunities=NOT_STARTED,
            no_opportunity=NOT_STARTED,
            discovery_required=NOT_STARTED,
            review_required=NOT_STARTED,
            candidate_gold=NOT_STARTED,
            candidate_silver=NOT_STARTED,
            candidate_bronze=NOT_STARTED,
            candidate_wood=NOT_STARTED,
            prepared_prior_categories=match_prepared_priors(str(b.get("okpd_code") or key), prior_index),
        )
        rows.append(row)

    rows.sort(key=lambda r: (-r.source_received, -r.projected_to_crm, r.okpd_code))
    dur_ms = int((time.perf_counter() - t0) * 1000)
    meta = {
        "okpd_group_count": len(rows),
        "okpd_aggregation_duration_ms": dur_ms,
        "analytics_cache_supports_okpd": ANALYTICS_CACHE_SUPPORTS_OKPD,
        "analytics_cache_supports_subcategory": ANALYTICS_CACHE_SUPPORTS_SUBCATEGORY,
        "aggregate_only": ANALYTICS_OKPD_CACHE_IS_AGGREGATE_ONLY,
    }
    return rows, meta


def okpd_rows_to_payload(rows: Sequence[OkpdFunnelRow], meta: Dict[str, Any]) -> Dict[str, Any]:
    return {"rows": [r.to_dict() for r in rows], "meta": meta}


def filter_okpd_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    contour: str = "ALL",
    okpd_query: str = "",
    category_code: str = "ALL",
) -> List[Dict[str, Any]]:
    q = (okpd_query or "").strip().lower()
    out = []
    for r in rows:
        if contour == "44" and int(r.get("source_44") or 0) <= 0 and int(r.get("projected_to_crm") or 0) <= 0:
            continue
        if contour == "223" and int(r.get("source_223") or 0) <= 0 and int(r.get("projected_to_crm") or 0) <= 0:
            continue
        if q:
            blob = f"{r.get('okpd_code','')} {r.get('okpd_name','')}".lower()
            priors = " ".join(
                f"{p.get('category_code','')} {p.get('display_name','')}"
                for p in (r.get("prepared_prior_categories") or [])
            ).lower()
            if q not in blob and q not in priors:
                continue
        if category_code and category_code != "ALL":
            cats = {p.get("category_code") for p in (r.get("prepared_prior_categories") or [])}
            if category_code not in cats:
                continue
        out.append(r)
    return out


def display_cell(value: Any) -> str:
    if value == NOT_STARTED:
        return "— · NOT STARTED"
    if value == NOT_AVAILABLE:
        return "— · NOT AVAILABLE"
    if value is None:
        return "—"
    return str(value)
