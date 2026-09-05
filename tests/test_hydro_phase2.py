from datetime import datetime, timezone
from pathlib import Path
import ast

from src.services.hydro.card_projection import lead_card, missing_facts
from src.services.hydro.lead_repository import HydroLeadRepository, _schema_error

def _obj(i, **kw):
    return {"object_id": i, "address": "Москва", "cadastral_number": f"77:{i}", "area_total": 1200, "floors_underground": 2, "parking_type": "UNDERGROUND", "object_potential": {"score": 90, "grade": "A", "reasons": ["area"], "version": "v1"}, **kw}

def test_both_kinds_and_score_separation():
    for kind in ("COMPANY_CONTOUR", "STANDALONE_OBJECT"):
        card = lead_card({"lead_id": 1, "lead_kind": kind, "company_name": "УК" if kind == "COMPANY_CONTOUR" else None, "object_potential": {"score": 90, "grade": "A"}, "lead_readiness": {"score": 10, "grade": "D"}}, [_obj(1)])
        assert card.potential.grade == "A" and card.readiness.grade == "D"
        if kind == "STANDALONE_OBJECT": assert card.next_task_label

def test_known_missing_and_stale_source_timestamp():
    card = lead_card({"lead_id": 2, "lead_kind": "STANDALONE_OBJECT", "source_health": "FAILED", "source_last_success_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, [_obj(2, area_total=None, parking_type=None)])
    assert missing_facts({"address": "x", "area_total": None}) == ("площадь", "подземные этажи", "тип паркинга")
    assert card.source_health == "FAILED" and card.source_last_success_at.year == 2026

class FakeDB:
    def __init__(self, rows=None, error=None): self.rows, self.error, self.sql = rows or [], error, []
    def execute_query(self, sql, params=()):
        self.sql.append((sql, params))
        if self.error: raise self.error
        return self.rows

def test_repository_filters_sort_and_no_source_dependency():
    db = FakeDB([{"lead_id": 1, "lead_kind": "COMPANY_CONTOUR", "state": "NEW", "company_name": "X", "object_potential": {"score": 80}, "lead_readiness": {"score": 20}}])
    cards = HydroLeadRepository(db).list_leads({"lead_kind": "COMPANY_CONTOUR", "company_resolved": True, "text": "X"})
    assert cards[0].lead_id == 1 and "parking_db" not in db.sql[0][0].lower()

def test_schema_fallback_and_non_schema_error():
    repo = HydroLeadRepository(FakeDB(error=Exception('relation crm_hydro_lead_extensions does not exist')))
    assert repo.list_leads() == [] and not repo.schema_available
    try: HydroLeadRepository(FakeDB(error=ValueError("network down"))).list_leads()
    except ValueError: pass
    else: assert False

def test_live_management_company_shape_has_optional_nulls():
    db = FakeDB([{"lead_id": 8, "lead_kind": "COMPANY_CONTOUR", "state": "NEW", "company_name": "УК", "company_inn": "7700000000", "object_count": 1}])
    repo = HydroLeadRepository(db)
    card = repo.get_lead(8)
    assert card.company_name == "УК" and card.company_inn == "7700000000"
    assert card.company_ogrn is None and card.company_phone is None
    assert ".ogrn" not in db.sql[0][0] and ".phone" not in db.sql[0][0]

def test_text_search_uses_only_canonical_management_company_fields():
    db = FakeDB([{"lead_id": 9, "lead_kind": "COMPANY_CONTOUR", "state": "NEW", "company_name": "УК", "company_inn": "7700000000", "object_count": 1}])
    repo = HydroLeadRepository(db)
    cards = repo.list_leads({"text": "Москва"})
    sql = db.sql[0][0]
    assert cards[0].company_name == "УК"
    assert "mc.name" in sql and "mc.inn" in sql
    assert "po.address" in sql and "po.cadastral_number" in sql
    assert "mc.ogrn" not in sql and "mc.phone" not in sql

def test_wrapped_schema_error_is_detected_without_swallowing_generic_error():
    class DatabaseQueryError(Exception):
        def __init__(self): self.original_exception = ValueError("column mc.ogrn does not exist")
    assert _schema_error(DatabaseQueryError())
    assert not _schema_error(ValueError("network timeout"))

def test_detail_all_objects_and_import_guard():
    db = FakeDB([{"lead_id": 4, "lead_kind": "COMPANY_CONTOUR", "state": "NEW", "object_count": 2}])
    repo = HydroLeadRepository(db)
    assert repo.get_lead(4).object_count == 2
    for path in (Path("src/ui/hydro_leads_tab.py"),):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any("parking_db" in item or "source_repository" in item for item in imports)
