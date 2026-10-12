"""Canonical OBJECT_STAGE / SERVICE_TYPE axes.

WIP OBJECT-STAGE-SERVICE-TYPE-IMPLEMENTATION-V1.

Covers only what this WIP added or changed:
  * canonical OBJECT_STAGE / SERVICE_TYPE enums and their classifiers;
  * «Стадия объекта» never resolves to the legacy tender column
    ``crm_object_ai_classifications.project_stage``;
  * WORK_STAGE stays a separate axis;
  * price never participates in any axis;
  * additive storage for the two axes.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from src.domain.commercial_routing_v3 import (
    LEGACY_PROJECT_STAGE_IS_NOT_OBJECT_STAGE,
    OBJECT_STAGE_VALUES,
    SERVICE_TYPE_VALUES,
    WORK_STAGE_VALUES,
    ObjectStage,
    ProcurementForm,
    ServiceType,
)
from src.services.commercial_routing_v3.model_ui_projection import (
    format_object_stage,
    routing_axes_view_from_assessment,
)
from src.services.commercial_routing_v3.object_mode_routing import (
    classify_object_stage,
    classify_service_type,
    classify_work_stage,
    is_object_stage_applicable,
)
from src.services.object_models import ObjectViewItem

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The WIP section 7 example table: title -> form -> (object_stage, service_type).
WIP_EXAMPLES = [
    ("Выполнение инженерно-геодезических изысканий", "SERVICES_OTHER",
     "SURVEY", "ENGINEERING_SURVEY"),
    ("Изыскания и разработка проектной документации", "SURVEY_AND_DESIGN",
     "DESIGN", "NONE"),
    ("Разработка проектной документации", "DESIGN_ONLY",
     "DESIGN", "NONE"),
    ("Разработка проектной документации и рабочей документации", "DESIGN_ONLY",
     "WORKING_DOCUMENTATION", "NONE"),
    ("Разработка проектной документации и прохождение экспертизы", "DESIGN_ONLY",
     "EXPERTISE", "NONE"),
    ("Разработка проектной документации, экспертиза и выполнение строительно-монтажных работ",
     "DESIGN_EXPERTISE_AND_BUILD", "CONSTRUCTION", "NONE"),
    ("Строительный контроль при капитальном ремонте", "SERVICES_OTHER",
     "CONSTRUCTION", "CONSTRUCTION_CONTROL"),
    ("Авторский надзор за строительством", "SERVICES_OTHER",
     "CONSTRUCTION", "AUTHOR_SUPERVISION"),
    ("Обследование технического состояния здания", "SERVICES_OTHER",
     "SURVEY", "TECHNICAL_SURVEY"),
    ("Техническое обслуживание инженерных систем здания", "SERVICES_OTHER",
     "OPERATION", "MAINTENANCE_SERVICE"),
    ("Поставка светильников", "DIRECT_GOODS_PURCHASE",
     "UNKNOWN", "NONE"),
]


def test_axes_are_canonical_and_frozen():
    assert OBJECT_STAGE_VALUES == (
        "SURVEY",
        "DESIGN",
        "WORKING_DOCUMENTATION",
        "EXPERTISE",
        "CONSTRUCTION",
        "OPERATION",
        "UNKNOWN",
    )
    assert SERVICE_TYPE_VALUES == (
        "CONSTRUCTION_CONTROL",
        "AUTHOR_SUPERVISION",
        "TECHNICAL_SURVEY",
        "ENGINEERING_SURVEY",
        "LAB_TESTING",
        "MAINTENANCE_SERVICE",
        "OTHER_SERVICE",
        "NONE",
        "UNKNOWN",
    )
    # WORK_STAGE stays a distinct axis and keeps the values production emits,
    # including SUPPLY.
    assert "SUPPLY" in WORK_STAGE_VALUES
    for value in ("CAPITAL_REPAIR", "REPAIR", "RECONSTRUCTION", "DESIGN"):
        assert value in WORK_STAGE_VALUES
    assert set(WORK_STAGE_VALUES) != set(OBJECT_STAGE_VALUES)
    # The legacy tender stage value must never appear on the object-stage axis.
    assert "SUPPLY" not in OBJECT_STAGE_VALUES
    assert "CAPITAL_REPAIR" not in OBJECT_STAGE_VALUES
    assert LEGACY_PROJECT_STAGE_IS_NOT_OBJECT_STAGE is True


@pytest.mark.parametrize("title,form,object_stage,service_type", WIP_EXAMPLES)
def test_wip_example_table(title, form, object_stage, service_type):
    assert classify_object_stage(title=title, form=form) == object_stage
    assert classify_service_type(title=title, form=form) == service_type
    assert object_stage in OBJECT_STAGE_VALUES
    assert service_type in SERVICE_TYPE_VALUES


def test_direct_supply_has_no_object_stage():
    form = ProcurementForm.DIRECT_GOODS_PURCHASE.value
    assert is_object_stage_applicable(form=form) is False
    for title in (
        "Поставка картриджей для принтеров",
        "Поставка геодезического тахеометра",
        "Поставка и монтаж мебели для строящейся школы",
    ):
        assert classify_object_stage(title=title, form=form) == ObjectStage.UNKNOWN.value
        assert classify_service_type(title=title, form=form) == ServiceType.NONE.value

    axes = routing_axes_view_from_assessment(
        {"normalized_result": {"procurement_form": form}}
    )
    assert axes["object_stage_applicable"] is False
    assert format_object_stage(axes) == "не применимо"


def test_object_stage_applicable_for_every_other_form():
    for form in ProcurementForm:
        if form is ProcurementForm.DIRECT_GOODS_PURCHASE:
            continue
        if form is ProcurementForm.UNKNOWN:
            continue
        assert is_object_stage_applicable(form=form.value) is True


def test_work_stage_is_a_separate_axis():
    form = ProcurementForm.CONSTRUCTION_WORKS.value
    title = "Капитальный ремонт здания школы"
    assert classify_object_stage(title=title, form=form) == ObjectStage.CONSTRUCTION.value
    assert classify_work_stage(title=title, form=form) == "CAPITAL_REPAIR"

    # Reconstruction happens while the object is still in the documentation stage.
    rec = "Разработка проектной документации по реконструкции корпуса"
    assert classify_object_stage(title=rec, form="DESIGN_ONLY") == ObjectStage.DESIGN.value
    assert classify_work_stage(title=rec, form="DESIGN_ONLY") == "DESIGN"

    # Direct supply: nature-of-works axis is SUPPLY-ish, lifecycle stage absent.
    assert is_object_stage_applicable(
        form=ProcurementForm.DIRECT_GOODS_PURCHASE.value
    ) is False


def test_service_type_only_exists_for_service_form():
    for form in ProcurementForm:
        if form is ProcurementForm.SERVICES_OTHER:
            continue
        assert classify_service_type(
            title="Строительный контроль при капитальном ремонте", form=form.value
        ) == ServiceType.NONE.value


def test_axes_never_read_price():
    for fn in (
        classify_object_stage,
        classify_service_type,
        classify_work_stage,
        is_object_stage_applicable,
    ):
        params = set(inspect.signature(fn).parameters)
        assert not params & {
            "price",
            "initial_price",
            "nmck",
            "nmck_price",
            "amount",
            "budget",
            "volume",
            "contract_value",
        }, fn.__name__

    base = {
        "normalized_result": {
            "procurement_form": "SERVICES_OTHER",
            "object_stage": "SURVEY",
            "service_type": "ENGINEERING_SURVEY",
        }
    }
    cheap = dict(base, initial_price=1_000, display_amount=1_000)
    expensive = dict(base, initial_price=1_000_000_000, display_amount=1_000_000_000)
    assert routing_axes_view_from_assessment(cheap) == routing_axes_view_from_assessment(expensive)
    assert format_object_stage(routing_axes_view_from_assessment(cheap)) == ObjectStage.SURVEY.value


def test_legacy_tender_stage_is_exposed_but_never_used_as_object_stage():
    assessment = {
        "normalized_result": {
            "procurement_form": "DIRECT_GOODS_PURCHASE",
            "project_stage": "SUPPLY",
        }
    }
    axes = routing_axes_view_from_assessment(assessment)
    assert axes["legacy_tender_stage"] == "SUPPLY"
    assert axes["object_stage"] in (None, ObjectStage.UNKNOWN.value)
    assert axes["object_stage"] != "SUPPLY"
    assert axes["provenance"] == "BUSINESS_RULE"


def test_legacy_assessment_with_object_form_does_not_leak_tender_stage():
    assessment = {
        "normalized_result": {
            "procurement_form": "CONSTRUCTION_WORKS",
            "project_stage": "CAPITAL_REPAIR",
        }
    }
    axes = routing_axes_view_from_assessment(assessment)
    assert axes["object_stage"] != "CAPITAL_REPAIR"
    assert format_object_stage(axes) == "не определено"


def test_object_view_item_exposes_axis_fields():
    item = ObjectViewItem(key="k", name="n", address=None, segment="s", status=None)
    assert item.ai_object_stage is None
    assert item.ai_service_type is None
    # The legacy field is untouched and stays available for the legacy object UI.
    assert item.ai_project_stage is None


def test_store_schema_is_additive_and_keeps_legacy_project_stage():
    src = (REPO_ROOT / "src/services/object_ai_classification_store.py").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS project_stage TEXT," in src
    assert "ADD COLUMN IF NOT EXISTS object_stage TEXT," in src
    assert "ADD COLUMN IF NOT EXISTS service_type TEXT," in src
    assert 'item.ai_project_stage = row.get("project_stage")' in src
    assert 'item.ai_object_stage = row.get("object_stage")' in src
    assert 'item.ai_service_type = row.get("service_type")' in src


def test_migration_is_additive_only():
    sql = (
        REPO_ROOT
        / "src/migrations/crm_object_ai_classifications_object_stage_service_type_1.sql"
    ).read_text(encoding="utf-8")
    # Comments may explain the legacy column; the executed statements must not
    # touch it. Only ADDs are allowed.
    statements = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    ).lower()
    assert "add column if not exists object_stage" in statements
    assert "add column if not exists service_type" in statements
    assert "project_stage" not in statements
    assert "drop column" not in statements
    assert "rename" not in statements
    assert "alter column" not in statements
    assert "delete from" not in statements


class _StubDb:
    def __init__(self, columns):
        self._columns = list(columns)
        self.queries: list[str] = []
        self.updates: list[tuple] = []

    def execute_query(self, sql, *args, **kwargs):
        self.queries.append(sql)
        return [{"column_name": c} for c in self._columns]

    def execute_update(self, sql, params=None):
        self.updates.append((sql, params))
        return 1


@pytest.fixture()
def store():
    from src.bootstrap import setup_source_path

    try:
        setup_source_path()
        from src.services import object_ai_classification_store as module
    except Exception as exc:  # CRM source tree unavailable
        pytest.skip(f"object_ai_classification_store unavailable: {exc}")
    return module


def test_optional_axis_write_is_guarded_by_column_presence(store):
    store._COLUMN_CACHE.clear()
    without_columns = _StubDb(["object_key", "project_stage"])
    store._persist_optional_axes(
        without_columns,
        "object:1",
        {"object_stage": "SURVEY", "service_type": "ENGINEERING_SURVEY"},
    )
    assert without_columns.updates == []

    store._COLUMN_CACHE.clear()
    with_columns = _StubDb(["object_key", "object_stage", "service_type"])
    store._persist_optional_axes(
        with_columns,
        "object:1",
        {"object_stage": "SURVEY", "service_type": "ENGINEERING_SURVEY"},
    )
    assert len(with_columns.updates) == 1
    sql, params = with_columns.updates[0]
    assert "UPDATE crm_object_ai_classifications" in sql
    assert "object_stage = %(object_stage)s" in sql
    assert "service_type = %(service_type)s" in sql
    assert params["object_key"] == "object:1"
    assert params["object_stage"] == "SURVEY"
    store._COLUMN_CACHE.clear()


def test_optional_axis_write_is_skipped_when_producer_supplies_nothing(store):
    store._COLUMN_CACHE.clear()
    db = _StubDb(["object_key", "object_stage", "service_type"])
    store._persist_optional_axes(db, "object:1", {})
    assert db.updates == []
    store._COLUMN_CACHE.clear()


@pytest.mark.parametrize(
    "rel",
    [
        "src/ui/components/analytics_v2/annotation_card.py",
        "src/ui/components/analytics_v2/annotation_card_sections.py",
        "src/ui/components/analytics_v2/card_tabs_ai_readonly.py",
        "src/ui/components/analytics_v2/card_tabs_ai_expert_form.py",
    ],
)
def test_ui_resolves_canonical_axes(rel):
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "routing_axes_view_from_assessment" in text
    assert "format_object_stage" in text


def test_ui_expert_form_labels_legacy_stage_as_legacy():
    text = (
        REPO_ROOT / "src/ui/components/analytics_v2/card_tabs_ai_expert_form.py"
    ).read_text(encoding="utf-8")
    assert "стадия закупки (legacy `project_stage`)" in text
    assert "OBJECT_STAGE / WORK_STAGE / SERVICE_TYPE" in text


def test_ui_card_shows_axes_separately():
    text = (
        REPO_ROOT / "src/ui/components/analytics_v2/annotation_card.py"
    ).read_text(encoding="utf-8")
    for label in ("Форма закупки", "Стадия объекта", "Характер работ", "Тип услуги"):
        assert label in text
    # The legacy column is still shown, but explicitly marked as a different axis.
    assert "не стадия объекта" in text
