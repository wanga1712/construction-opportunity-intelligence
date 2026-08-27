"""Static acceptance for fast category triage UX contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gate_rendered_first_in_primary_decision():
    card = (ROOT / "src/ui/components/analytics_v2/annotation_card.py").read_text(encoding="utf-8")
    fn = card.split("def _render_primary_scope_decision", 1)[1].split("def render_annotation_card", 1)[0]
    # Deep path starts after YES success message.
    yes_branch = fn.split('decision != "YES"', 1)[-1]
    gate_pos = fn.find("FIRST_GATE_QUESTION")
    product_pos = yes_branch.find("render_product_category_controls")
    object_pos = yes_branch.find("render_object_stage_controls")
    mode_pos = yes_branch.find("render_procurement_mode_controls")
    commercial_pos = yes_branch.find("render_commercial_and_medal_controls")
    assert gate_pos > 0
    assert 0 <= product_pos < object_pos < mode_pos < commercial_pos
    assert "build_out_of_category_payload" in fn
    assert "save_and_next=True" in fn
    assert "category_gate_comment" not in fn
    # One-action Нет: persist immediately on button click, not only via second Save.
    no_block = fn.split('scope_no_inner', 1)[1].split("scope_unc_inner", 1)[0]
    assert "build_out_of_category_payload" in no_block
    assert "save_and_next=True" in no_block


def test_surface_fast_triage_one_action():
    ws = (ROOT / "src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert "def _persist_fast_triage" in ws
    assert "_persist_fast_triage(procurement_id, out_of_category=True)" in ws
    assert "FIRST_GATE_QUESTION" in ws
    assert "Вне товарных категорий" in ws
    assert "is_deep_annotation_complete" in ws
    assert "is_category_reviewed" in ws
    assert "components.html" not in ws
    assert "addEventListener" not in ws
    assert "KeyboardEvent" not in ws


def test_validate_out_requires_nothing():
    from src.ui.components.analytics_v2.staged_annotation_ui import validate_staged_minimum

    assert validate_staged_minimum({}, require_in_category_extras=False) == []
    missing = validate_staged_minimum({}, require_in_category_extras=True)
    assert "товарную категорию" in missing
    assert "объект (сектор и тип)" in missing
    assert "тип закупки" in missing
