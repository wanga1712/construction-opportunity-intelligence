"""Read-only JSON API over :class:`CommercialPortalService`.

WIP=COMMERCIAL_SITE_CRM_LINK_V1, phase 4.

Endpoints (all GET, JSON, never write anything):
    /api/v1/health
    /api/v1/market/summary
    /api/v1/categories
    /api/v1/opportunities
    /api/v1/procurements/{id}/preview
    /api/v1/procurements/{id}

The client contract already carries the tenant fields the tariff layer will
need later - ``organization_id``, ``user_id``, ``selected_categories``,
``entitlements``, ``card_open_limit`` - but no billing rule is enforced in this
WIP (``entitlement_enforced = false``).

The frontend never receives database credentials: the site backend calls this
service over loopback (default bind 127.0.0.1) and the database credentials
stay in the API process environment.

Run:
    COMMERCIAL_PORTAL_HOST=127.0.0.1 COMMERCIAL_PORTAL_PORT=8787 \
        python -m src.api.commercial_portal_api
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from src.services.commercial_portal_service import CommercialPortalService

DEFAULT_HOST = os.getenv("COMMERCIAL_PORTAL_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("COMMERCIAL_PORTAL_PORT", "8787"))
API_TOKEN = os.getenv("COMMERCIAL_PORTAL_API_TOKEN", "").strip()
MAX_BODY = 1 << 16

_PROCUREMENT_RE = re.compile(r"^/api/v1/procurements/(\d+)(/preview)?/?$")


class _Handler(BaseHTTPRequestHandler):
    server_version = "CRMCommercialPortal/1.0"
    service = CommercialPortalService()

    def do_GET(self) -> None:  # noqa: N802 (http.server contract)
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            status, payload = self._dispatch(path, query)
        except Exception as exc:  # noqa: BLE001 - fail closed, never leak secrets
            status, payload = 500, {"error": "INTERNAL_ERROR", "detail": type(exc).__name__}
        self._send(status, payload)

    def do_POST(self) -> None:  # noqa: N802
        self._send(405, {"error": "METHOD_NOT_ALLOWED", "detail": "This API is read-only."})

    # ── routing ──────────────────────────────────────────────────────────────

    def _dispatch(self, path: str, query: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if not self._authorized():
            return 401, {"error": "UNAUTHORIZED"}
        if path in ("/api/v1/health", "/health"):
            return 200, {"status": "ok", "unit": "DISTINCT_PROCUREMENT_ID"}
        if path == "/api/v1/market/summary":
            return 200, self._envelope(query, self.service.get_market_summary())
        if path == "/api/v1/categories":
            return 200, self._envelope(query, {"items": self.service.get_categories()})
        if path == "/api/v1/opportunities":
            return 200, self._envelope(query, self.service.list_ranked_procurements(
                self._filters(query)))
        match = _PROCUREMENT_RE.match(path)
        if match:
            procurement_id = int(match.group(1))
            if match.group(2):
                data = self.service.get_procurement_preview(procurement_id)
            else:
                data = self.service.get_procurement_commercial_card(procurement_id)
            if data is None:
                return 404, {"error": "NOT_FOUND", "procurement_id": procurement_id}
            return 200, self._envelope(query, data)
        return 404, {"error": "NOT_FOUND", "path": path}

    @staticmethod
    def _filters(query: Dict[str, Any]) -> Dict[str, Any]:
        def one(name: str) -> Optional[str]:
            values = query.get(name) or []
            return values[0] if values else None

        return {
            "segment": one("segment"),
            "scope_type": one("scope_type"),
            "category_code": one("category_code"),
            "medal": one("medal"),
            "region": one("region"),
            "query": one("q"),
            "limit": one("limit"),
            "offset": one("offset"),
            "confirmed_only": (one("confirmed_only") or "").lower() in ("1", "true", "yes"),
            "with_commerce": (one("with_commerce") or "").lower() in ("1", "true", "yes"),
        }

    # ── tenant contract (no billing in this WIP) ─────────────────────────────

    def _context(self, query: Dict[str, Any]) -> Dict[str, Any]:
        def one(name: str) -> Optional[str]:
            values = query.get(name) or []
            return values[0] if values else None

        limit = one("card_open_limit")
        try:
            card_open_limit = int(limit) if limit not in (None, "") else None
        except ValueError:
            card_open_limit = None
        return {
            "organization_id": one("organization_id") or self._header("X-Organization-Id"),
            "user_id": one("user_id") or self._header("X-User-Id"),
            "selected_categories": query.get("category") or [],
            "entitlements": (one("entitlements") or "").split(",") if one("entitlements") else [],
            "card_open_limit": card_open_limit,
            "entitlement_enforced": False,
        }

    def _envelope(self, query: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        return {"context": self._context(query), "data": data}

    def _header(self, name: str) -> Optional[str]:
        value = self.headers.get(name)
        return value if value else None

    def _authorized(self) -> bool:
        if not API_TOKEN:
            return True
        provided = self.headers.get("Authorization") or ""
        provided = provided[7:] if provided.lower().startswith("bearer ") else provided
        return provided.strip() == API_TOKEN

    # ── transport ────────────────────────────────────────────────────────────

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # keep logs quiet/filterable
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    host = argv[0] if argv else DEFAULT_HOST
    port = int(argv[1]) if len(argv) > 1 else DEFAULT_PORT
    with ThreadingHTTPServer((host, port), _Handler) as httpd:
        sys.stderr.write("commercial portal API on http://%s:%d (read-only)\n" % (host, port))
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
