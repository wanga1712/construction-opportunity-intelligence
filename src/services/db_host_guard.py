"""Fail-fast guard against legacy/forbidden database hosts.

Single authority for the rule: the CRM runtime must never open a PostgreSQL
connection to a legacy VPN address.  ``10.0.0.7`` (nyx / tender_monitor) and
``10.0.0.13`` (sergey / S13) are LEGACY / FORBIDDEN for every current CRM
runtime; the approved routes are the Tailscale ones (see
``docs/PROJECT_OPERATING_RULES.md``).

The guard raises instead of silently timing out or falling back, so a stale
.env / inherited variable is reported by name at the first connection attempt.
It never prints passwords or any other secret.
"""
from __future__ import annotations

from typing import Any, Dict

LEGACY_DB_HOSTS = frozenset({"10.0.0.7", "10.0.0.13"})


class LegacyDbHostBlocked(RuntimeError):
    """Raised when a connection would target a legacy/forbidden DB host."""


def assert_host_allowed(host: Any, source: str) -> str:
    """Return ``host`` unchanged unless it is a blocked legacy address."""
    value = str(host or "").strip()
    if value in LEGACY_DB_HOSTS:
        raise LegacyDbHostBlocked(
            f"LEGACY_DB_HOST_BLOCKED: {source} resolved to legacy host {value!r}. "
            "10.0.0.7 / 10.0.0.13 are forbidden for the CRM runtime; use the "
            "approved Tailscale route (see docs/PROJECT_OPERATING_RULES.md)."
        )
    return value


def guard_connect_kwargs(kwargs: Dict[str, Any], source: str = "connection kwargs") -> Dict[str, Any]:
    """Validate ``host`` in a psycopg2 kwargs mapping. Returns it unchanged."""
    if "host" in kwargs:
        kwargs["host"] = assert_host_allowed(kwargs.get("host"), source)
    return kwargs