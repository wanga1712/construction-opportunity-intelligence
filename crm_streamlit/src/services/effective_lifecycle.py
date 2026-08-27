"""Effective lifecycle authority for analytics worksets.

Canonical logical identity: (law_family, factual contract_number).
Source lineage rows may coexist; presentation uses one effective stage:

  AWARDED/COMPLETED > COMMISSION/WAITING > OPEN

Unknown / unproven submission deadline is never treated as OPEN.
"""
from __future__ import annotations

from typing import Literal

from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
from src.services.source_contour import LAW_44, LAW_223, LAW_615, resolve_source_contour

LawFilter = Literal["ALL", "44-FZ", "223-FZ", "615-PP"]

LAW_FILTER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("ALL", "Все"),
    (LAW_44, "44-ФЗ"),
    (LAW_223, "223-ФЗ"),
    (LAW_615, "615-ПП"),
)

# Proven: projection_writer._SOURCE_PULLS has no 615 tables.
LAW_615_IN_ANALYTICS_WORKSET = False
LAW_615_MISSING_PATH = (
    "reestr_contract_615_pp exists in source DB, but commercial_routing_v3."
    "projection_writer._SOURCE_PULLS does not include 615 OPEN/COMMISSION/AWARDED "
    "tables, so CRM analytics workset has zero 615 rows."
)


def law_family_sql(alias: str = "cp") -> str:
    """SQL CASE mapping source_table → law family code (factual tokens only)."""
    return f"""
    CASE
      WHEN {alias}.source_table ILIKE '%%615%%'
        OR {alias}.source_table ILIKE '%%kapremont%%'
        OR {alias}.source_table ILIKE '%%capital_repair%%'
        THEN '{LAW_615}'
      WHEN {alias}.source_table ILIKE '%%223%%' THEN '{LAW_223}'
      WHEN {alias}.source_table ILIKE '%%44%%' THEN '{LAW_44}'
      ELSE 'UNKNOWN'
    END
    """.strip()


def law_filter_sql(alias: str, law: str | None) -> str:
    if not law or law == "ALL":
        return "TRUE"
    if law == LAW_44:
        return (
            f"({alias}.source_table ILIKE '%%44%%' "
            f"AND {alias}.source_table NOT ILIKE '%%223%%' "
            f"AND {alias}.source_table NOT ILIKE '%%615%%')"
        )
    if law == LAW_223:
        return f"{alias}.source_table ILIKE '%%223%%'"
    if law == LAW_615:
        return (
            f"({alias}.source_table ILIKE '%%615%%' "
            f"OR {alias}.source_table ILIKE '%%kapremont%%' "
            f"OR {alias}.source_table ILIKE '%%capital_repair%%')"
        )
    return "TRUE"


def same_logical_identity_sql(left: str, right: str) -> str:
    """Match two crm_procurements aliases as one logical procurement."""
    return f"""
    btrim(COALESCE({left}.contract_number,'')) <> ''
    AND btrim({left}.contract_number) = btrim({right}.contract_number)
    AND ({law_family_sql(left)}) = ({law_family_sql(right)})
    """.strip()


def not_superseded_by_awarded_sql(alias: str = "cp") -> str:
    return f"""
    NOT EXISTS (
      SELECT 1 FROM crm_procurements aw
      WHERE aw.crm_stage = 'razygranye'
        AND {same_logical_identity_sql(alias, "aw")}
        AND aw.id <> {alias}.id
    )
    """.strip()


def not_superseded_by_commission_sql(alias: str = "cp") -> str:
    return f"""
    NOT EXISTS (
      SELECT 1 FROM crm_procurements w
      WHERE (
          (w.crm_stage = 'torgi'
           AND w.award_status IN ('submission_closed_waiting_award', 'award_not_found'))
          OR w.crm_stage = 'commission'
        )
        AND {same_logical_identity_sql(alias, "w")}
        AND w.id <> {alias}.id
    )
    """.strip()


def factual_open_torgi_sql(alias: str = "cp", *, law: str | None = "ALL") -> str:
    """Идут торги: proven OPEN only — deadline known, actionable, not superseded."""
    return f"""
    {alias}.crm_stage = 'torgi'
    AND {alias}.award_status = 'submission_open'
    AND {alias}.end_date IS NOT NULL
    AND {actionable_submission_sql(alias)}
    AND {not_superseded_by_awarded_sql(alias)}
    AND {not_superseded_by_commission_sql(alias)}
    AND {law_filter_sql(alias, law)}
    """.strip()


def factual_commission_sql(alias: str = "cp", *, law: str | None = "ALL") -> str:
    """Комиссия: waiting after a known past deadline, or explicit commission stage."""
    return f"""
    (
      (
        {alias}.crm_stage = 'torgi'
        AND {alias}.award_status IN ('submission_closed_waiting_award', 'award_not_found')
        AND {alias}.end_date IS NOT NULL
        AND {alias}.end_date < CURRENT_DATE
      )
      OR {alias}.crm_stage = 'commission'
    )
    AND {not_superseded_by_awarded_sql(alias)}
    AND {law_filter_sql(alias, law)}
    """.strip()


def factual_awarded_sql(alias: str = "cp", *, law: str | None = "ALL") -> str:
    return f"""
    {alias}.crm_stage = 'razygranye'
    AND {law_filter_sql(alias, law)}
    """.strip()


def classify_deadline_for_open(end_date) -> str:
    """Writer helper: NULL deadline is UNKNOWN, never OPEN."""
    if end_date is None:
        return "UNKNOWN"
    return "KNOWN"


def open_row_award_status(end_date, *, today=None):
    """Map open-table row deadline → award_status without treating NULL as open."""
    from datetime import date

    today = today or date.today()
    if end_date is None:
        # Not submission_open — excluded from Идут торги and from commission
        # (commission requires known past end_date).
        return "award_not_found"
    if today <= end_date:
        return "submission_open"
    return "submission_closed_waiting_award"


def law_code_from_source_table(source_table: str | None) -> str:
    return resolve_source_contour(source_table)["law_code"]
