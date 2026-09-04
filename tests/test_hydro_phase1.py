from datetime import datetime, timezone

from src.services.hydro.lead_builder import build_candidates, logical_lead_key, merge_standalone
from src.services.hydro.models import HydroLeadKind, source_row_to_object
from src.services.hydro.projection import project
from src.services.hydro.scoring import lead_readiness, object_potential
from src.services.hydro.source_sync import CanonicalHydroStore


def row(**extra):
    base = {"id": 7, "cadastral_number": "77:01:0000000:7", "name": "Parking",
            "address_text": "Moscow", "floors_underground": 2, "area_total": 2000,
            "commissioning_year": 1990,
            "parking_type": "UNDERGROUND", "confidence_score": 1.0,
            "candidate_reason": "fact", "uk_id": 11, "uk_name": "UK",
            "uk_inn": "7700000000", "uk_ogrn": "1027700000000", "uk_phone": None}
    base.update(extra)
    return base


def obj(**extra):
    return source_row_to_object(row(**extra), now=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_source_mapping_preserves_native_identity_and_missing_facts():
    value = obj()
    assert value.identity_key == "NSPD_PARKING:7"
    assert value.cadastral_number == "77:01:0000000:7"
    assert value.management_company_ogrn == "1027700000000"
    assert value.construction_finish_year is None


def test_sync_is_idempotent_and_health_counts_unchanged():
    store = CanonicalHydroStore()
    assert store.sync([obj()]).rows_inserted == 1
    health = store.sync([obj()])
    assert health.rows_unchanged == 1 and health.rows_inserted == 0


def test_source_failure_preserves_snapshot_and_marks_health():
    store = CanonicalHydroStore()
    store.sync([obj()])
    health = store.source_failed(ConnectionError("unavailable"))
    assert health.status == "FAILED" and len(store.objects) == 1
    assert health.last_success_at is not None


def test_company_contour_groups_many_objects():
    leads = build_candidates([obj(id=1), obj(id=2, cadastral_number="77:01:2")])
    assert len(leads) == 1 and leads[0].kind is HydroLeadKind.COMPANY_CONTOUR
    assert len(leads[0].object_keys) == 2


def test_standalone_is_one_object_and_has_no_fake_company():
    value = obj(uk_id=None, uk_name=None, uk_inn=None, uk_ogrn=None)
    leads = build_candidates([value])
    assert leads[0].kind is HydroLeadKind.STANDALONE_OBJECT
    assert leads[0].company_key is None and len(leads[0].object_keys) == 1


def test_repeated_build_has_same_logical_key():
    value = obj()
    assert logical_lead_key(value) == logical_lead_key(value)
    assert len(build_candidates([value, value])) == 1


def test_merge_preserves_old_lead_and_moves_object():
    standalone = build_candidates([obj(uk_id=None, uk_name=None, uk_inn=None, uk_ogrn=None)])[0]
    company = build_candidates([obj()])[0]
    old_key = standalone.object_keys[0]
    merge_standalone(standalone, company)
    assert standalone.state == "MERGED" and standalone.merged_into == company.logical_key
    assert old_key in company.object_keys


def test_scores_are_independent_and_unknowns_stay_missing():
    physical = object_potential(obj())
    readiness = lead_readiness({"company_resolved": True})
    assert physical.grade == "A" and physical.score >= 90
    assert readiness.grade == "D"
    assert "technical_contact" in readiness.missing_signals
    assert physical.version != readiness.version


def test_projection_works_from_canonical_store_without_source():
    value = obj()
    lead = build_candidates([value])[0]
    projection = project(lead, {value.identity_key: value}, health="FAILED", freshness=value.synced_at)
    assert projection.object_count == 1
    assert projection.management_company["ogrn"] == "1027700000000"
    assert projection.source_health == "FAILED"


def test_standalone_projection_company_is_null():
    value = obj(uk_id=None, uk_name=None, uk_inn=None, uk_ogrn=None)
    lead = build_candidates([value])[0]
    projection = project(lead, {value.identity_key: value})
    assert projection.management_company is None


def test_migration_contains_required_safety_constraints():
    sql = open("src/migrations/crm_hydro_canonical_data_1.sql", encoding="utf-8").read()
    assert "crm_hydro_lead_extensions" in sql
    assert "crm_hydro_lead_objects" in sql
    assert "COMPANY_CONTOUR" in sql and "STANDALONE_OBJECT" in sql
    assert "UNIQUE (parking_object_id)" in sql
    assert "SOURCE_ID" in sql and "HEURISTIC_REVIEW" in sql
