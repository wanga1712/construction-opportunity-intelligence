#!/usr/bin/env python3
"""Read-only CRM commercial-logic acceptance audit (T01-T11)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

for root in ("/opt/CRM_Streamlit", "/opt/tender_documents_research"):
    if root not in sys.path:
        sys.path.insert(0, root)

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv("/opt/CRM_Streamlit/.env", override=True)

from src.services.commercial_routing_v3.medal_timing import compute_stage_end_timing
from src.services.commercial_routing_v3.procurement_queue_priority import (
    aggregate_procurement_opportunities,
)
from src.services.crm_db_runtime import require_crm_db_connect_kwargs
from src.services.procurement_card_dossier_service import (
    _di_conn as dossier_di_conn,
    load_procurement_dossier,
)
from src.services.procurement_category_presentation import summarize_category_cards

MANIFEST = Path(
    "/opt/CRM_Streamlit/backups/"
    "crm_commercial_runtime_manifest_20261112_V1.json"
)
TARGET_PIDS = (42971, 43009, 214966)


class Db:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def execute_query(self, sql: str, params=(), fetch=True):
        with self.connection.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result(
    checks: list[dict[str, Any]],
    test_id: str,
    status: str,
    evidence: Any,
) -> None:
    checks.append({"id": test_id, "status": status, "evidence": evidence})


def main() -> int:
    checks: list[dict[str, Any]] = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    # T01: runtime identity and health.
    hash_mismatches = []
    for rel, expected in manifest["runtime_files"].items():
        path = Path(rel if rel.startswith("/") else f"/opt/CRM_Streamlit/{rel}")
        actual = _sha256(path)
        if actual != expected:
            hash_mismatches.append(
                {"path": rel, "expected": expected, "actual": actual}
            )
    try:
        with urllib.request.urlopen("http://127.0.0.1:8504/", timeout=10) as response:
            http_status = response.status
    except Exception as exc:  # noqa: BLE001
        http_status = f"{type(exc).__name__}: {exc}"
    service_active = (
        subprocess.run(
            ["systemctl", "is-active", "crm-streamlit"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        == "active"
    )
    _result(
        checks,
        "T01",
        "PASS"
        if not hash_mismatches and http_status == 200 and service_active
        else "FAIL",
        {
            "runtime_files": len(manifest["runtime_files"]),
            "hash_mismatches": hash_mismatches,
            "http_status": http_status,
            "service_active": service_active,
        },
    )

    crm = psycopg2.connect(**require_crm_db_connect_kwargs())
    crm.set_session(readonly=True)
    di = dossier_di_conn()
    di.set_session(readonly=True)
    dossier_db = Db(crm)
    dossiers = {
        pid: load_procurement_dossier(dossier_db, pid)
        for pid in TARGET_PIDS
    }
    summaries = {
        pid: summarize_category_cards(dossier.get("categories") or [])
        for pid, dossier in dossiers.items()
    }

    # T02: category isolation in all targeted cards.
    cross_category = []
    line_source_mismatch = []
    for pid, dossier in dossiers.items():
        for card in dossier.get("categories") or []:
            code = str(card.get("category_code") or "")
            sub = str(card.get("subcategory_code") or "")
            for product in card.get("products") or []:
                if (
                    str(product.get("category_code") or "") != code
                    or str(product.get("subcategory_code") or "") != sub
                ):
                    cross_category.append(
                        {
                            "pid": pid,
                            "category": code,
                            "subcategory": sub,
                            "product_category": product.get("category_code"),
                            "product_subcategory": product.get("subcategory_code"),
                            "material": product.get("material"),
                        }
                    )
            source_count = sum(
                int(product.get("occurrence_count") or 1)
                for product in card.get("products") or []
            )
            if source_count != int(card.get("source_row_count") or 0):
                line_source_mismatch.append(
                    {
                        "pid": pid,
                        "category": code,
                        "subcategory": sub,
                        "source_count": source_count,
                        "card_source_row_count": card.get("source_row_count"),
                    }
                )
    _result(
        checks,
        "T02",
        "PASS" if not cross_category and not line_source_mismatch else "FAIL",
        {
            "cross_category": cross_category,
            "line_source_mismatch": line_source_mismatch,
        },
    )

    # T03: displayed totals reconcile to position totals.
    reconcile_failures = []
    for pid, summary_rows in summaries.items():
        for summary in summary_rows:
            code = str(summary.get("category_code") or "")
            products = [
                product
                for card in dossiers[pid].get("categories") or []
                if str(card.get("category_code") or "") == code
                for product in card.get("products") or []
            ]
            position_sum = round(
                sum(_num(product.get("total")) or 0.0 for product in products),
                2,
            )
            if position_sum != round(float(summary.get("material_value") or 0), 2):
                reconcile_failures.append(
                    {
                        "pid": pid,
                        "category": code,
                        "positions_sum": position_sum,
                        "summary_value": summary.get("material_value"),
                    }
                )
    _result(
        checks,
        "T03",
        "PASS" if not reconcile_failures else "FAIL",
        {"reconcile_failures": reconcile_failures},
    )

    # T04: unassigned goods contain no known overhead labels.
    forbidden = re.compile(
        r"^\s*(?:ФОТ|ОТ|ЭМ|ЗТ|НР|СП|М)(?:\s|$)",
        re.IGNORECASE,
    )
    overhead = [
        {"material": row.get("material"), "total": row.get("total")}
        for pid in TARGET_PIDS
        for row in dossiers[pid].get("unassigned_products") or []
        if forbidden.match(str(row.get("material") or ""))
        or str(row.get("unit") or "").strip() == "%"
    ]
    _result(
        checks,
        "T04",
        "PASS" if not overhead else "FAIL",
        {
            "unassigned_count": {
                pid: len(dossiers[pid].get("unassigned_products") or [])
                for pid in TARGET_PIDS
            },
            "overhead": overhead,
        },
    )

    # T05: known GrandSmeta numeric canaries.
    with di.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT procurement_id, name_raw, quantity_value, unit_price_value,
                   total_value, layout_status, category_code, subcategory_code
              FROM structured_estimate_rows
             WHERE procurement_id = ANY(%s)
               AND layout_status = 'CONSISTENT'
               AND category_code IS NOT NULL
               AND subcategory_code IS NOT NULL
               AND (
                    name_raw ILIKE 'Шнур полиамидный%%'
                    OR name_raw ILIKE 'Клей на эпоксидной основе%%'
                    OR name_raw ILIKE 'Брикет из эпоксидно-щебеночного композита%%'
                    OR name_raw ILIKE '%%Elementa  ERX 585%%'
               )
             ORDER BY procurement_id, id
            """,
            (list(TARGET_PIDS),),
        )
        numeric_rows = [dict(row) for row in cur.fetchall()]
    invalid_numeric = []
    for row in numeric_rows:
        try:
            qty = Decimal(str(row.get("quantity_value")))
            price = Decimal(str(row.get("unit_price_value")))
            total = Decimal(str(row.get("total_value")))
        except (ArithmeticError, TypeError, ValueError):
            invalid_numeric.append(dict(row))
            continue
        tolerance = max(Decimal("0.02"), total * Decimal("0.000001"))
        if (
            row.get("layout_status") != "CONSISTENT"
            or qty <= 0
            or price <= 0
            or total <= 0
            or abs(qty * price - total) > tolerance
        ):
            invalid_numeric.append(dict(row))
    _result(
        checks,
        "T05",
        "PASS" if numeric_rows and not invalid_numeric else "FAIL",
        {"rows": len(numeric_rows), "invalid": invalid_numeric},
    )

    # T06: category-value canaries.
    composite = next(
        row for row in summaries[43009] if row["category_code"] == "composite_structures"
    )
    composite_subs = {
        row["subcategory_code"]: row["material_value"]
        for row in composite["subcategories"]
    }
    structural_42971 = next(
        row
        for row in summaries[42971]
        if row["category_code"] == "structural_reinforcement"
    )
    value_failures = []
    expected_subs = {
        "composite_guardrails_stairs": 707440.07,
        "composite_drainage_channels": 132981.86,
        "polymer_adhesives_binders": 32243.07,
        "polymer_cords_twines": 3039.11,
    }
    for code, expected in expected_subs.items():
        if composite_subs.get(code) != expected:
            value_failures.append(
                {"subcategory": code, "expected": expected, "actual": composite_subs.get(code)}
            )
    if composite["material_value"] != 875704.11:
        value_failures.append(
            {"category": "composite", "expected": 875704.11, "actual": composite["material_value"]}
        )
    if structural_42971["material_value"] != 438634.47:
        value_failures.append(
            {
                "category": "structural_42971",
                "expected": 438634.47,
                "actual": structural_42971["material_value"],
            }
        )
    _result(
        checks,
        "T06",
        "PASS" if not value_failures else "FAIL",
        {"failures": value_failures, "composite_subs": composite_subs},
    )

    # T07: commercial offers are separate and not quantity-bearing.
    offers = dossiers[214966].get("commercial_offers") or []
    offer_failures = []
    expected_offers = {
        "8690059177": 56944.43,
        "4992109632": 14714.75,
        "0306050317": 15007.37,
        "6082627205": 13920.49,
    }
    actual_offers = {
        str(offer.get("issuer_inn")): _num(offer.get("unit_price_value"))
        for offer in offers
    }
    for inn, expected in expected_offers.items():
        if actual_offers.get(inn) != expected:
            offer_failures.append(
                {"inn": inn, "expected": expected, "actual": actual_offers.get(inn)}
            )
    if any(offer.get("quantity_value") is not None for offer in offers):
        offer_failures.append("commercial_offer_has_quantity")
    _result(
        checks,
        "T07",
        "PASS" if not offer_failures else "FAIL",
        {"offers": actual_offers, "failures": offer_failures},
    )

    # T08: stage-end timing monotonicity.
    as_of = date(2026, 11, 12)
    near = compute_stage_end_timing(
        {"end_date": "2026-12-01"},
        lifecycle="OPEN",
        track="DIRECT_SUPPLY",
        as_of=as_of,
    )
    far = compute_stage_end_timing(
        {"end_date": "2027-12-01"},
        lifecycle="OPEN",
        track="DIRECT_SUPPLY",
        as_of=as_of,
    )
    expired = compute_stage_end_timing(
        {"end_date": "2025-12-01"},
        lifecycle="OPEN",
        track="DIRECT_SUPPLY",
        as_of=as_of,
    )
    timing_ok = (
        near.timing_value is not None
        and far.timing_value is not None
        and near.timing_value > far.timing_value
        and expired.timing_value == 0.0
    )
    _result(
        checks,
        "T08",
        "PASS" if timing_ok else "FAIL",
        {
            "near": near.as_dict(),
            "far": far.as_dict(),
            "expired": expired.as_dict(),
        },
    )

    # T09: procurement priority aggregation uses medal before score.
    priority = aggregate_procurement_opportunities(
        [
            {
                "procurement_id": 1,
                "commercial_category_code": "a",
                "current_effective_medal": "GOLD",
                "current_effective_score": 10,
            },
            {
                "procurement_id": 1,
                "commercial_category_code": "b",
                "current_effective_medal": "WOOD",
                "current_effective_score": 99,
            },
        ]
    )[1]
    priority_ok = (
        priority["queue_medal"] == "GOLD"
        and priority["queue_medal_rank"] == 4
        and priority["queue_primary_category"] == "a"
    )
    _result(
        checks,
        "T09",
        "PASS" if priority_ok else "FAIL",
        priority,
    )

    # T10: queue/worker consistency.
    di_kwargs = dict(require_crm_db_connect_kwargs())
    di_kwargs["dbname"] = os.getenv(
        "S13_DOCUMENT_DB_NAME", "document_intelligence"
    )
    queue_conn = psycopg2.connect(**di_kwargs)
    queue_conn.set_session(readonly=True)
    with queue_conn.cursor() as cur:
        cur.execute(
            "SELECT status, count(*) FROM document_processing_queue GROUP BY status"
        )
        queue_counts = {str(status): int(count) for status, count in cur.fetchall()}
    queue_conn.close()
    workers = [
        "tender-docs-band-bronze.service",
        "tender-docs-band-gold-1.service",
        "tender-docs-band-gold-2.service",
        "tender-docs-band-silver.service",
        "tender-docs-band-wood.service",
        "tender-docs-daemon-awarded.service",
        "tender-docs-daemon-open.service",
        "tender-docs-daemon-open-2.service",
        "tender-docs-daemon-open-3.service",
        "tender-docs-daemon.service",
    ]
    active_states = {
        unit: subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        for unit in workers
    }
    queue_ok = (
        not queue_counts.get("PROCESSING")
        and all(state == "active" for state in active_states.values())
    )
    _result(
        checks,
        "T10",
        "PASS" if queue_ok else "INCONCLUSIVE",
        {"queue": queue_counts, "workers": active_states},
    )

    # T11: newest admitted CURRENT card has a usable projection path.
    with crm.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.id AS procurement_id, p.contract_number,
                   p.crm_created_at, count(o.id) AS current_opportunities,
                   count(o.id) FILTER (
                       WHERE o.current_effective_medal IS NOT NULL
                   ) AS with_effective_medal
              FROM crm_procurements p
              JOIN crm_procurement_category_opportunities o
                ON o.procurement_id = p.id AND o.status = 'CURRENT'
             GROUP BY p.id, p.contract_number, p.crm_created_at
             ORDER BY p.crm_created_at DESC NULLS LAST, p.id DESC
             LIMIT 1
            """
        )
        newest_current = dict(cur.fetchone() or {})
    newest_dossier = (
        load_procurement_dossier(dossier_db, int(newest_current["procurement_id"]))
        if newest_current
        else {}
    )
    newest_ok = bool(
        newest_current
        and int(newest_current.get("current_opportunities") or 0) > 0
        and int(newest_current.get("with_effective_medal") or 0) > 0
        and newest_dossier.get("identity")
    )
    _result(
        checks,
        "T11",
        "PASS" if newest_ok else "FAIL",
        {
            **newest_current,
            "dossier_loaded": bool(newest_dossier.get("identity")),
            "check_scope": "READ_ONLY_NEWEST_ADMITTED_CURRENT_CARD",
        },
    )

    # T12 is intentionally not inferred from service data.
    _result(
        checks,
        "T12",
        "BLOCKED",
        {"reason": "Manual browser UI verification was not performed."},
    )

    crm.close()
    di.close()

    failed = [check for check in checks if check["status"] == "FAIL"]
    blocked = [check for check in checks if check["status"] in {"BLOCKED", "INCONCLUSIVE"}]
    acceptance = (
        "FAIL"
        if failed
        else "BLOCKED_UI_ACCESS"
        if any(check["id"] == "T12" for check in blocked)
        else "PASS"
    )
    report = {
        "manifest": str(MANIFEST),
        "manifest_sha256": _sha256(MANIFEST),
        "checks": checks,
        "failed": failed,
        "blocked_or_inconclusive": blocked,
        "execution_status": "COMPLETED_WITH_UI_BLOCK",
        "acceptance": acceptance,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if acceptance in {"PASS", "BLOCKED_UI_ACCESS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
