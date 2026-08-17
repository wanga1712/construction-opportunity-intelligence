"""S7 read-only enrich for CRM procurement rows before canonical card build."""
from __future__ import annotations

import os
from typing import Any, Dict

import psycopg2
import psycopg2.extras


def enrich_procurement_from_s7(proc: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing source fields from S7 reestr tables (READ ONLY)."""
    table = str(proc.get("source_table") or "")
    sid = proc.get("source_id")
    if not table.startswith("reestr_contract_") or sid is None:
        return proc
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST") or "10.8.0.7",
        port=int(os.getenv("DB_PORT") or 5432),
        dbname=os.getenv("DB_NAME") or "tender_monitor",
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET default_transaction_read_only = on")
            cust = "placer, placer_inn" if "223" in table else "customer"
            cur.execute(
                f"""
                SELECT c.created_at AS source_created_at, c.updated_at AS source_updated_at,
                       c.start_date, c.end_date, c.delivery_start_date, c.delivery_end_date,
                       c.delivery_address, c.delivery_region, c.region_id, r.name AS region_name,
                       c.okpd_id AS source_okpd_id, o.sub_code AS okpd_code, o.name AS okpd_name,
                       c.tender_link, c.initial_price, c.final_price,
                       c.customer_id AS source_customer_id, c.contractor_id AS source_contractor_id,
                       COALESCE(ct.short_name, ct.full_name) AS winner_name, ct.inn AS winner_inn,
                       {cust}
                FROM {table} c
                LEFT JOIN collection_codes_okpd o ON o.id = c.okpd_id
                LEFT JOIN region r ON r.id = c.region_id
                LEFT JOIN contractor ct ON ct.id = c.contractor_id
                WHERE c.id = %s
                """,
                (int(sid),),
            )
            row = cur.fetchone()
            if not row:
                return proc
            out = dict(proc)
            for k, v in dict(row).items():
                if v is None:
                    continue
                if k == "placer":
                    out["customer"] = out.get("customer") or v
                elif k == "placer_inn":
                    out["customer_inn"] = out.get("customer_inn") or v
                elif k == "okpd_code" and not out.get("okpd_code"):
                    out["okpd_code"] = v
                elif k == "delivery_region":
                    out["delivery_region"] = out.get("delivery_region") or v
                elif k == "region_name" and not out.get("delivery_region"):
                    out["region_name"] = v
                    out["delivery_region"] = out.get("delivery_region") or v
                else:
                    out[k] = out.get(k) or v
            return out
    except Exception:
        return proc
    finally:
        conn.close()
