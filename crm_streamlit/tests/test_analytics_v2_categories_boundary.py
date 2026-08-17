from __future__ import annotations

from src.repositories.analytics_category_repository import AnalyticsCategoryRepository
from src.services.analytics_categories import list_available_categories
from src.services import analytics_contour_v2_page as service_page
from src.services import crm_profile_service
from src.ui import analytics_contour_v2_page as ui_page


class FakeCursor:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows or []
        self.error = error
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql):
        self.sql = " ".join(sql.split())
        if self.error:
            raise self.error

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor
        self.closed = False

    def cursor(self, **_kwargs):
        return self.fake_cursor

    def close(self):
        self.closed = True


def test_repository_preserves_sql_row_order_and_mapping():
    rows = [
        {"crm_category": "Б"},
        {"crm_category": "А"},
        {"crm_category": "Б"},
        {"crm_category": None},
        {"crm_category": ""},
    ]
    cursor = FakeCursor(rows)
    connection = FakeConnection(cursor)
    repository = AnalyticsCategoryRepository(lambda: connection)

    assert repository.list_available_categories() == ["Б", "А", "Б", None, ""]
    assert cursor.sql == (
        "SELECT DISTINCT crm_category FROM crm_procurements "
        "WHERE crm_category IS NOT NULL AND crm_category != '' ORDER BY crm_category"
    )
    assert connection.closed is True


def test_repository_preserves_empty_result():
    connection = FakeConnection(FakeCursor([]))
    repository = AnalyticsCategoryRepository(lambda: connection)

    assert repository.list_available_categories() == []
    assert connection.closed is True


def test_application_returns_fallback_on_connection_error():
    def fail_connect():
        raise RuntimeError("connection unavailable")

    repository = AnalyticsCategoryRepository(fail_connect)
    assert list_available_categories(repository) == []


def test_application_returns_fallback_on_sql_error():
    connection = FakeConnection(FakeCursor(error=RuntimeError("bad sql")))
    repository = AnalyticsCategoryRepository(lambda: connection)

    assert list_available_categories(repository) == []
    assert connection.closed is True


def test_ui_wrapper_uses_injected_repository_without_postgresql():
    class FakeRepository:
        def list_available_categories(self):
            return ["Категория Б", "Категория А"]

    assert ui_page._load_categories_from_db(FakeRepository()) == [
        "Категория Б",
        "Категория А",
    ]


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.selectboxes = []

    def markdown(self, *_args, **_kwargs):
        return None

    def selectbox(self, label, options, **_kwargs):
        self.selectboxes.append((label, options))
        return None

    def segmented_control(self, *_args, **_kwargs):
        return None

    def radio(self, *_args, **_kwargs):
        return None

    def button(self, *_args, **_kwargs):
        return False


def test_service_fallback_uses_injected_repository(monkeypatch):
    fake_st = FakeStreamlit()
    calls = []
    monkeypatch.setattr(service_page, "st", fake_st)
    monkeypatch.setattr(crm_profile_service, "load_profiles", lambda: [])
    monkeypatch.setattr(crm_profile_service, "load_subcategories", lambda *_args: [])
    class FakeRepository:
        def list_available_categories(self):
            calls.append("repository")
            return ["Категория Б", "Категория А"]

    service_page._render_filters(FakeRepository())

    assert calls == ["repository"]
    assert ("Категория", ["Все", "Категория Б", "Категория А"]) in fake_st.selectboxes
