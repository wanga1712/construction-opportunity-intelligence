"""Explicit SOURCE vs CRM database role contract.

CRM V3 target architecture:
  SOURCE (procurement history) = S7 tender_monitor  — READ ONLY from S13
  CRM (intelligence / hot state) = S13 canonical CRM DB — WRITE target

Current production still points CRM DSN at 10.8.0.7:5432/crm.
This module does not switch production; it encodes the contract and
validates that source and CRM roles are configured independently.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


# Documented target after controlled cutover (not applied in this WIP).
PROPOSED_S13_CRM_DB_NAME = "crm"
PROPOSED_S13_CRM_DB_HOST = "127.0.0.1"
PROPOSED_S13_CRM_DB_PORT = "5432"
PROPOSED_S13_CRM_DB_ROLE = "crm_app"

# S7 remains procurement source authority.
PROCUREMENT_SOURCE_AUTHORITY = "S7"
CRM_PROJECTION_OWNER = "S13"

SOURCE_ENV_KEYS = (
    "TENDER_MONITOR_DB_HOST",
    "TENDER_MONITOR_DB_PORT",
    "TENDER_MONITOR_DB_DATABASE",
    "TENDER_MONITOR_DB_USER",
)

CRM_ENV_KEYS = (
    "CRM_DB_HOST",
    "CRM_DB_PORT",
    "CRM_DB_DATABASE",
    "CRM_DB_USER",
)

ENV_KEYS_TO_CHANGE_FOR_CUTOVER = (
    "CRM_DB_HOST",
    "CRM_DB_PORT",
    "CRM_DB_DATABASE",
    "CRM_DB_USER",
    "CRM_DB_PASSWORD",
)


@dataclass(frozen=True)
class DbEndpoint:
    role: str
    host: str
    port: str
    database: str
    user: str

    @property
    def route(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class DbRoleContract:
    source: DbEndpoint
    crm: DbEndpoint
    source_role_explicit: bool
    crm_role_explicit: bool
    same_server: bool
    same_database: bool
    ambiguous_generic_fallback: bool

    @property
    def roles_separated(self) -> bool:
        return (
            self.source_role_explicit
            and self.crm_role_explicit
            and not self.ambiguous_generic_fallback
            and not self.same_database
        )


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    return str(env.get(key) or default).strip()


def resolve_db_role_contract(env: Optional[Mapping[str, str]] = None) -> DbRoleContract:
    """Resolve SOURCE and CRM endpoints from env without inventing credentials."""
    e = env if env is not None else os.environ

    source_host = _get(e, "TENDER_MONITOR_DB_HOST")
    source_db = _get(e, "TENDER_MONITOR_DB_DATABASE")
    source_user = _get(e, "TENDER_MONITOR_DB_USER")
    source_port = _get(e, "TENDER_MONITOR_DB_PORT", "5432") or "5432"

    crm_host = _get(e, "CRM_DB_HOST")
    crm_db = _get(e, "CRM_DB_DATABASE") or _get(e, "CRM_DB_NAME")
    crm_user = _get(e, "CRM_DB_USER")
    crm_port = _get(e, "CRM_DB_PORT", "5432") or "5432"

    # Forbidden ambiguity: CRM falling back to tender host/db or vice versa.
    ambiguous = False
    if not crm_host and source_host:
        ambiguous = True
        crm_host = source_host
    if not source_host and crm_host:
        ambiguous = True
        source_host = crm_host
    if not crm_db and source_db:
        ambiguous = True
        crm_db = source_db
    if not source_db and crm_db:
        ambiguous = True
        source_db = crm_db

    source_explicit = bool(source_host and source_db and source_user)
    crm_explicit = bool(crm_host and crm_db and crm_user)

    source = DbEndpoint(
        role="source_db",
        host=source_host or "?",
        port=source_port,
        database=source_db or "?",
        user=source_user or "?",
    )
    crm = DbEndpoint(
        role="crm_db",
        host=crm_host or "?",
        port=crm_port,
        database=crm_db or "?",
        user=crm_user or "?",
    )

    same_server = bool(source.host != "?" and source.host == crm.host)
    same_database = bool(
        source.host == crm.host
        and source.port == crm.port
        and source.database == crm.database
        and source.database != "?"
    )

    return DbRoleContract(
        source=source,
        crm=crm,
        source_role_explicit=source_explicit,
        crm_role_explicit=crm_explicit,
        same_server=same_server,
        same_database=same_database,
        ambiguous_generic_fallback=ambiguous,
    )


def assert_v3_writes_target_crm_only(target_role: str) -> None:
    """V3 persistence must use crm_db, never tender_monitor/source_db."""
    if target_role != "crm_db":
        raise AssertionError(
            f"V3 write target must be crm_db, got {target_role!r}"
        )


def assert_no_tender_monitor_write_in_v3(sql: str) -> None:
    """Static guard helper for tests — V3 SQL must not mutate source tables."""
    lowered = sql.lower()
    forbidden = (
        "into reestr_contract_",
        "update reestr_contract_",
        "delete from reestr_contract_",
        "into collection_codes_okpd",
        "update collection_codes_okpd",
        "into okpd_from_users",
        "update okpd_from_users",
    )
    for token in forbidden:
        if token in lowered:
            raise AssertionError(f"V3 must not write tender_monitor source: {token}")
