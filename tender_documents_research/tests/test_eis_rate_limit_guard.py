from __future__ import annotations

import logging
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from document_processor.eis_rate_limit_guard import (  # noqa: E402
    EisRateLimitBlocked,
    EisRateLimited,
    EisRateLimitGuard,
    utcnow,
)
from document_processor.eis_rate_limit_store import (  # noqa: E402
    EIS_HOST,
    MemoryEisStateStore,
)
from document_processor.http_client import HttpFileClient  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, headers=None, text="", content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self._content = content
        self.closed = False

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def iter_content(self, chunk_size=8192):
        if self._content:
            yield self._content

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def make_guard():
    store = MemoryEisStateStore()
    return EisRateLimitGuard(store=store), store


def make_due(store):
    with store._lock:
        store._state(EIS_HOST)["blocked_until"] = utcnow() - timedelta(seconds=1)


def test_429_blocks_all_new_requests_immediately():
    guard_one, store = make_guard()
    guard_two = EisRateLimitGuard(store=store)

    guard_one.record_429("https://zakupki.gov.ru/x", retry_after=5, xid="123")

    assert guard_two.is_blocked() is True
    with pytest.raises(EisRateLimitBlocked):
        guard_two.ensure_request_allowed("DOWNLOAD")
    assert guard_two.state()["consecutive_blocks"] == 1


def test_retry_after_over_5_minutes_extends_cooldown():
    guard, _ = make_guard()
    before = utcnow()
    state = guard.record_429(
        "https://zakupki.gov.ru/x", retry_after=7200, xid="123"
    )
    blocked_until = state["blocked_until"]
    assert blocked_until >= before + timedelta(minutes=119)


def test_cascade_escalates_to_three_hours_and_resets_after_recovery():
    guard, store = make_guard()
    expected_minutes = [5, 15, 30, 60, 120, 180, 180]
    for expected in expected_minutes:
        before = utcnow()
        state = guard.record_429("https://zakupki.gov.ru/x")
        actual = (state["blocked_until"] - before).total_seconds() / 60.0
        assert expected <= actual <= expected + 1

    make_due(store)
    result = guard.maybe_run_probe(lambda: {"ok": True, "status": "SUCCESS"})
    assert result["status"] == "RECOVERED"
    assert guard.state()["consecutive_blocks"] == 0

    before = utcnow()
    state = guard.record_429("https://zakupki.gov.ru/x")
    actual = (state["blocked_until"] - before).total_seconds() / 60.0
    assert 5 <= actual <= 6


def test_only_one_process_can_probe():
    guard_one, store = make_guard()
    guard_two = EisRateLimitGuard(store=store)
    guard_one.record_429("https://zakupki.gov.ru/x", retry_after=1)
    make_due(store)

    entered = threading.Event()
    release = threading.Event()
    results = []

    def slow_probe():
        entered.set()
        release.wait(timeout=2)
        return {"ok": True, "status": "SUCCESS"}

    thread = threading.Thread(
        target=lambda: results.append(guard_one.maybe_run_probe(slow_probe))
    )
    thread.start()
    assert entered.wait(timeout=2)
    second = guard_two.maybe_run_probe(lambda: {"ok": True})
    assert second["status"] == "LOCK_BUSY"
    release.set()
    thread.join(timeout=2)
    assert results[0]["status"] == "RECOVERED"


def test_probe_429_extends_block_without_new_incident():
    guard, store = make_guard()
    guard.record_429("https://zakupki.gov.ru/x", retry_after=1, xid="first")
    make_due(store)

    def probe_429():
        guard.record_429(
            "https://zakupki.gov.ru/probe",
            retry_after=5,
            xid="probe-xid",
        )
        raise EisRateLimited(
            "https://zakupki.gov.ru/probe", retry_after=5, xid="probe-xid"
        )

    result = guard.maybe_run_probe(probe_429)
    state = guard.state()
    assert result["status"] == "HTTP_429"
    assert guard.is_blocked() is True
    assert state["consecutive_blocks"] == 2
    assert state["last_probe_status"] == "HTTP_429"
    assert len(store._incidents) == 1


def test_probe_success_and_canary_success_unblock():
    guard, store = make_guard()
    guard.record_429("https://zakupki.gov.ru/x", retry_after=1)
    make_due(store)

    result = guard.maybe_run_probe(
        lambda: {"ok": True, "status": "SUCCESS", "detail": "head+canary"}
    )

    assert result["status"] == "RECOVERED"
    assert guard.is_blocked() is False
    assert guard.state()["last_probe_status"] == "SUCCESS"


def test_http_client_blocks_head_proxy_and_html_without_network():
    guard, _ = make_guard()
    guard.record_429("https://zakupki.gov.ru/seed", retry_after=60)
    client = HttpFileClient(None, None, logging.getLogger("test"), guard=guard)
    fake = FakeSession(FakeResponse(status_code=200))
    client.session = fake
    client.proxy_url = "http://proxy.local"
    client.proxy_mode = "http"

    urls = [
        "https://zakupki.gov.ru/file",
        "https://zakupki.gov.ru/file.html",
    ]
    for url in urls:
        with pytest.raises(EisRateLimitBlocked):
            client.request_head(url, request_type="HEAD")
        with pytest.raises(EisRateLimitBlocked):
            client.try_download_with_proxy(Path("."), url)
        with pytest.raises(EisRateLimitBlocked):
            client.download_html_and_follow(Path("."), url)
    assert fake.calls == []


def test_429_status_retry_after_and_xid_are_preserved_without_retry():
    guard, _ = make_guard()
    client = HttpFileClient(None, None, logging.getLogger("test"), guard=guard)
    response = FakeResponse(
        status_code=429,
        headers={"Retry-After": "5", "X-Cache": "Varnish"},
        text="Guru Meditation\nXID: 2828711056",
    )
    client.session = FakeSession(response)

    with pytest.raises(EisRateLimited) as exc_info:
        client.request_head("https://zakupki.gov.ru/x", request_type="HEAD")

    exc = exc_info.value
    assert exc.http_status == 429
    assert exc.retry_after == 5
    assert exc.xid == "2828711056"
    assert exc.response_headers["X-Cache"] == "Varnish"
    assert len(client.session.calls) == 1
    assert guard.is_blocked() is True


def test_429_does_not_fall_back_to_another_request_path():
    guard, _ = make_guard()
    client = HttpFileClient(None, "http", logging.getLogger("test"), guard=guard)
    client.session = FakeSession(
        FakeResponse(status_code=429, headers={"Retry-After": "5"})
    )

    with pytest.raises(EisRateLimited):
        client.try_download_direct(Path("."), "https://zakupki.gov.ru/file")
    assert len(client.session.calls) == 1


def test_successful_non_eis_request_is_unaffected():
    guard, _ = make_guard()
    client = HttpFileClient(None, None, logging.getLogger("test"), guard=guard)
    response = FakeResponse(status_code=200, content=b"ok")
    client.session = FakeSession(response)
    result = client._request("GET", "https://example.org/file")
    assert result.status_code == 200
    assert not guard.is_blocked()


def test_download_failure_preserves_http_fields():
    from document_processor.downloader import DownloadFailure

    failure = DownloadFailure(
        source_link_id=None,
        source_url="https://zakupki.gov.ru/x",
        url_hash="abc",
        error_class="EIS_RATE_LIMITED",
        http_status=429,
        error_message="EIS_RATE_LIMITED",
        latency_ms=12,
        response_headers={"Retry-After": "5"},
        retry_after=5,
        xid="2828711056",
    )
    assert failure.http_status == 429
    assert failure.retry_after == 5
    assert failure.xid == "2828711056"
