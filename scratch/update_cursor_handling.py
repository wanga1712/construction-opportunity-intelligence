#!/usr/bin/env python3
"""
Applies robust target claim starvation fix to context_validator_service.py.
Handles both RealDictCursor and standard tuple cursors safely.
"""
import os
import re

SERVICE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tender_documents_research",
    "document_processor",
    "context_validator_service.py",
)

with open(SERVICE_PATH, "r", encoding="utf-8") as f:
    src = f.read()

# Replace get_target_procurement_ids to handle dict & tuple cursor returns safely
old_get_target = '''def get_target_procurement_ids(
    crm_conn,
    priors: List[Dict[str, Any]],
) -> List[int]:
    """Retrieves list of active TARGET procurement IDs from CRM database.

    Uses distinct OKPD classification optimization for high efficiency across 160k+ procurements.
    """
    with crm_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT okpd_code FROM crm_procurements WHERE okpd_code IS NOT NULL AND okpd_code != ''")
        distinct_okpds = [r[0] for r in cur.fetchall()]

    target_okpds = [okpd for okpd in distinct_okpds if classify_target_okpd(okpd, priors)[0] == ADMISSION_TARGET]
    if not target_okpds:
        return []

    with crm_conn.cursor() as cur:
        cur.execute("SELECT id FROM crm_procurements WHERE okpd_code = ANY(%s)", (target_okpds,))
        return sorted([r[0] for r in cur.fetchall()])'''

new_get_target = '''def get_target_procurement_ids(
    crm_conn,
    priors: List[Dict[str, Any]],
) -> List[int]:
    """Retrieves list of active TARGET procurement IDs from CRM database.

    Uses distinct OKPD classification optimization for high efficiency across 160k+ procurements.
    Handles both dict and tuple cursors safely.
    """
    with crm_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT okpd_code FROM crm_procurements WHERE okpd_code IS NOT NULL AND okpd_code != ''")
        rows = cur.fetchall()
        distinct_okpds = [r[0] if isinstance(r, (list, tuple)) else r["okpd_code"] for r in rows if r]

    target_okpds = [okpd for okpd in distinct_okpds if classify_target_okpd(okpd, priors)[0] == ADMISSION_TARGET]
    if not target_okpds:
        return []

    with crm_conn.cursor() as cur:
        cur.execute("SELECT id FROM crm_procurements WHERE okpd_code = ANY(%s)", (target_okpds,))
        rows = cur.fetchall()
        return sorted([r[0] if isinstance(r, (list, tuple)) else r["id"] for r in rows if r])'''

assert old_get_target in src, "old get_target_procurement_ids not found"
src = src.replace(old_get_target, new_get_target, 1)

with open(SERVICE_PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Updated get_target_procurement_ids cursor handling in context_validator_service.py")
