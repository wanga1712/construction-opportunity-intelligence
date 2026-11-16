from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

from src.services.hydro.company_repository import HydroCompanyRepository
from src.ui import hydro_inline_sidecar as sidecar
from src.ui import hydro_inline_workspace_tabs as tabs


ROOT = Path(__file__).resolve().parents[1]


class FakeDB:
    def __init__(self):
        self.calls = []

    def execute_query(self, sql, params=()):
        self.calls.append((sql, params))
        if "RETURNING id" in sql:
            return [{"id": 42}]
        if "RETURNING id" in sql or "RETURNING id" in str(sql):
            return [{"id": 42}]
        if sql.lstrip().startswith("UPDATE company_contacts"):
            return [{"id": 42}]
        return []


def test_live_schema_audit_has_no_writes():
    source = (ROOT / "scripts" / "audit_hydro_uk_live_schema.py").read_text(encoding="utf-8")
    assert 'cursor.execute("BEGIN READ ONLY")' in source
    assert "INSERT INTO" not in source.upper()
    assert "UPDATE " not in source.upper()
    assert "DELETE FROM" not in source.upper()
    assert "ALTER TABLE" not in source.upper()
    assert "CREATE TABLE" not in source.upper()


def test_contact_role_is_not_hardcoded():
    source = (ROOT / "src" / "ui" / "hydro_inline_workspace_tabs.py").read_text(encoding="utf-8")
    assert '"Должность / роль"' in source
    assert "ROLE_OPTIONS" not in source
    assert "role in" not in source


def test_contact_reception_roundtrip():
    db = FakeDB()
    repo = HydroCompanyRepository(db)
    saved = repo.update_contact(42, {
        "company_id": 7, "full_name": "Иванов И.И.", "role": "Главный инженер",
        "phone": "+7 900 000-00-00", "reception_type": "scheduled",
        "reception_schedule": "mon=09:00-18:00; wed=10:00-17:00",
        "reception_note": "Вход со двора",
    })
    assert saved
    sql, params = db.calls[-1]
    assert "reception_type" in sql and "reception_schedule" in sql and "reception_note" in sql
    assert any('"mon": "09:00-18:00"' in value for value in params if isinstance(value, str))
    assert params[7] == "scheduled"
    assert params[-1] == 7


def test_multiple_contact_phones():
    db = FakeDB()
    phone_id = HydroCompanyRepository(db).add_contact_phone(7, 42, {
        "phone": "+7 900 000-00-01", "phone_type": "mobile",
        "extension": "123", "label": "Секретарь", "is_primary": False,
    })
    assert phone_id == 42
    sql, params = db.calls[-1]
    assert "company_contact_phones" in sql
    assert params[0:3] == (7, 42, "+7 900 000-00-01")


def test_overlay_has_no_full_card_navigation():
    overlay = (ROOT / "src" / "ui" / "hydro_inline_sidecar.py").read_text(encoding="utf-8")
    page = (ROOT / "src" / "ui" / "waterproofing_page.py").read_text(encoding="utf-8")
    assert "Полная карточка" not in overlay
    assert "hydro_open_uk" not in page
    assert "render_uk_card" not in page


def test_all_company_objects_visible(monkeypatch):
    rendered = []

    class Repo:
        def list_objects(self, company_id):
            return [{"address": f"ул. Арбат, д. {n}"} for n in range(1, 9)]

    monkeypatch.setattr(tabs.st, "markdown", lambda text, **kwargs: rendered.append(text))
    monkeypatch.setattr(tabs.st, "caption", lambda text, **kwargs: None)
    monkeypatch.setattr(tabs.st, "divider", lambda: None)
    tabs.render_objects(Repo(), {"id": 1})
    assert len([line for line in rendered if line.startswith("**")]) == 8


def test_per_object_615_indicator_uses_one_batched_snapshot(monkeypatch):
    rendered = []

    class Repo:
        db = object()

        def list_objects(self, company_id):
            return [
                {"address": "ул. Арбат, д. 35", "floors_underground": 2},
                {"address": "ул. Тверская, д. 10", "floors_underground": 1},
            ]

    calls = []
    store = ModuleType("src.services.waterproofing_615_store")
    store.read_uk_contract_rows = lambda db, key: calls.append((db, key)) or {
            "available": True, "status": "fresh", "rows": [
                {"address_key": "арбат 35", "contract_id": "c-1"},
            ],
        }
    matcher = ModuleType("src.services.waterproofing_615")
    matcher.address_key = lambda value: {
        "ул. Арбат, д. 35": ("арбат", "35"), "ул. Тверская, д. 10": ("тверская", "10"),
    }.get(value)
    monkeypatch.setitem(__import__("sys").modules, "src.services.waterproofing_615_store", store)
    monkeypatch.setitem(__import__("sys").modules, "src.services.waterproofing_615", matcher)
    monkeypatch.setattr(tabs.st, "markdown", lambda text, **kwargs: rendered.append(text))
    monkeypatch.setattr(tabs.st, "caption", lambda text: rendered.append(text))
    monkeypatch.setattr(tabs.st, "divider", lambda: None)

    tabs.render_objects(Repo(), {"id": 8}, "uk-8")

    assert calls == [(Repo.db, "uk-8")]
    assert any("615-ПП: найдено 1" in line for line in rendered)
    assert any("615-ПП: не найдено" in line for line in rendered)


def test_stale_615_object_indicator_is_unknown_not_zero(monkeypatch):
    rendered = []

    class Repo:
        db = object()

        def list_objects(self, company_id):
            return [{"address": "ул. Арбат, д. 35"}]

    store = ModuleType("src.services.waterproofing_615_store")
    store.read_uk_contract_rows = lambda db, key: {"available": True, "status": "stale", "rows": []}
    matcher = ModuleType("src.services.waterproofing_615")
    matcher.address_key = lambda value: ("арбат", "35")
    monkeypatch.setitem(__import__("sys").modules, "src.services.waterproofing_615_store", store)
    monkeypatch.setitem(__import__("sys").modules, "src.services.waterproofing_615", matcher)
    monkeypatch.setattr(tabs.st, "markdown", lambda text, **kwargs: rendered.append(text))
    monkeypatch.setattr(tabs.st, "caption", lambda text: rendered.append(text))
    monkeypatch.setattr(tabs.st, "divider", lambda: None)

    tabs.render_objects(Repo(), {"id": 8}, "uk-8")

    assert any("неизвестно" in line for line in rendered)
    assert not any("не найдено" in line for line in rendered)


def test_615_detail_read_batches_freshness_and_contracts():
    import sys

    for name in ("modules", "modules.crm", "modules.crm.analytics"):
        package = ModuleType(name)
        package.__path__ = []
        sys.modules.setdefault(name, package)
    tender_utils = ModuleType("modules.crm.analytics.tender_row_utils")
    tender_utils.query_dicts = lambda *args, **kwargs: []
    sys.modules.setdefault("modules.crm.analytics.tender_row_utils", tender_utils)
    from src.services.waterproofing_615_store import read_uk_contract_rows

    class DB:
        def __init__(self):
            self.calls = []

        def execute_query(self, sql, params):
            self.calls.append((sql, params))
            return [{"sync_state": {
                "status": "SUCCESS",
                "last_success_at": datetime.now(timezone.utc) - timedelta(hours=40),
            }, "address_key": None, "contract_id": None}]

    db = DB()
    payload = read_uk_contract_rows(db, "uk-1")
    assert len(db.calls) == 1
    assert "crm_waterproofing_615_sync_state" in db.calls[0][0]
    assert "crm_waterproofing_615_uk_address" in db.calls[0][0]
    assert "crm_waterproofing_615_uk_link" in db.calls[0][0]
    assert payload["status"] == "stale"
    assert payload["rows"] == []


def test_general_phone_falls_back_to_card_without_contact_rows():
    overlay = (ROOT / "src" / "ui" / "hydro_inline_sidecar.py").read_text(encoding="utf-8")
    assert "(company or {}).get(\"phone\") or card.get(\"phone\")" in overlay
    assert "list_contacts" not in overlay


def test_unknown_615_count_is_not_rendered_as_zero():
    assert sidecar._six_fifteen_count({"tenders_615_count": 0}) is None
    assert sidecar._six_fifteen_count({"tenders_615_count": 3}) == 3


def test_company_phone_can_have_no_person_contact():
    source = (ROOT / "src" / "services" / "hydro" / "company_repository.py").read_text(encoding="utf-8")
    assert "add_contact_phone" in source
    assert "contact_id" in source
    assert "contact_id IS NULL" in source


def test_short_object_address_rendering():
    assert tabs.short_address("г. Москва, ул. Арбат, д. 35, корп. 2, подъезд 1") == "ул. Арбат, д. 35, корп. 2"
    assert len(tabs.short_address("Москва " + "очень длинный адрес " * 10)) <= 74


def test_615_grouped_by_address():
    parts = ("арбат", "35")
    key = f"{parts[0]} {parts[1]}"
    payload = {"rows": [{"address_key": key, "contract_id": "contract-1"}]}
    grouped, matched = tabs._contract_groups(
        payload, [{"address": "ул. Арбат, д. 35"}],
        address_key_fn=lambda _: parts,
    )
    assert matched == 1
    assert len(grouped["ул. Арбат, д. 35"]) == 1


def test_615_contract_amount_visible():
    line = tabs.contract_detail_line({
        "contract_id": "id-1", "contract_number": "123/615", "contract_date": date(2025, 4, 1),
        "amount": 18_400_000, "is_waterproofing": True, "match_method": "exact", "match_score": 1.0,
    })
    assert "18 400 000 ₽" in line
    assert "123/615" in line
    assert "гидроизоляция: да" in line


def test_615_stale_state_not_rendered_as_zero():
    summary = tabs.contract_summary({"available": True, "status": "stale", "rows": [
        {"address_key": "key", "contract_id": None, "amount": 0},
    ]}, object_count=5, matched_objects=0)
    assert summary is None


def test_stage_moves_inside_overlay():
    kanban = (ROOT / "src" / "ui" / "waterproofing_kanban_tab.py").read_text(encoding="utf-8")
    assert "move_stage=lambda target: _move_overlay_stage(selected_card, target)" in kanban
    move_helper = kanban.split("def _move_overlay_stage(", 1)[1].split("\ndef ", 1)[0]
    assert "merge_contour_state(key" in move_helper
    assert '"stage": target' in move_helper
    assert '"next_action": STAGE_DEFAULT_ACTIONS.get(target, "")' in move_helper
    assert "result = move_stage(selected_stage)" in (ROOT / "src" / "ui" / "hydro_inline_workspace_tabs.py").read_text(encoding="utf-8")


def test_tabs_lazy_load_heavy_data():
    labels = ["Контакты", "Объекты · 5", "615-ПП · 3", "Действия"]
    calls = []
    handlers = {label: (lambda value=label: calls.append(value)) for label in labels}
    tabs.dispatch_workspace_tab(labels[2], labels, handlers)
    assert calls == [labels[2]]
