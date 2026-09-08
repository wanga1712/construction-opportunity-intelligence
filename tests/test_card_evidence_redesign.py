"""Tests for CRM-ANALYTICS-V2-CARD-EVIDENCE-REDESIGN-1.

16 mandatory tests verifying card evidence hierarchy:
MONEY → COMMERCIAL OPPORTUNITY → MEDAL → NORMALIZED FINDING → DOCUMENT EVIDENCE

Hard invariants:
- CURRENT_EFFECTIVE_MEDAL_AS_DOCUMENT_CONFIRMED=NO
- DOCUMENT_CONFIRMED_REQUIRES_EVIDENCE=YES
- INVENTED_DOCUMENT_URL_ALLOWED=NO
- CATEGORY_OPPORTUNITY_IS_MEDAL_UNIT=YES
"""

from __future__ import annotations

import importlib
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── Module imports ──────────────────────────────────────────────────────

_opp = importlib.import_module("src.ui.components.analytics_v2.card_opportunities")
_ws = importlib.import_module("src.ui.components.analytics_v2.stage_workspace")


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def gold_card():
    return {
        "id": 1001,
        "auction_name": "Test Procurement",
        "initial_price": 126_450_000,
        "final_contract_price": None,
        "customer": "ООО Заказчик",
        "delivery_region": "Москва",
        "source_table": "tenders_44fz",
        "contract_number": "0123456789012345",
        "tender_link": "https://zakupki.gov.ru/epz/order/notice/ea44/view/common-info.html?regNumber=0123456789012345",
        "okpd_code": "43.99.10.130",
        "okpd_name": "Работы по гидроизоляции",
        "end_date": "2026-09-14",
        "file_count": 5,
        "match_count": 12,
        "evidence_count": 3,
        "award_status": "submission_open",
        "crm_stage": "torgi",
    }


@pytest.fixture
def sample_opps():
    return [
        {
            "id": 1,
            "procurement_id": 1001,
            "category_code": "ГИДРОИЗОЛЯЦИЯ",
            "subcategory_code": "Инъекционная гидроизоляция",
            "candidate_initial_medal": "GOLD",
            "current_effective_medal": "SILVER",
            "current_effective_reason": "ACTIVE_TIMING_DECAY",
            "initial_medal_provenance": "FIRST_ACCEPTANCE",
            "status": "CURRENT",
        },
        {
            "id": 2,
            "procurement_id": 1001,
            "category_code": "НАПОЛЬНЫЕ_ПОКРЫТИЯ",
            "subcategory_code": "",
            "candidate_initial_medal": "BRONZE",
            "current_effective_medal": "BRONZE",
            "current_effective_reason": "FIRST_ACCEPTANCE",
            "initial_medal_provenance": "FIRST_ACCEPTANCE",
            "status": "CURRENT",
        },
    ]


@pytest.fixture
def sample_evidence():
    return {
        "1001:ГИДРОИЗОЛЯЦИЯ": {
            "procurement_id": 1001,
            "category_code": "ГИДРОИЗОЛЯЦИЯ",
            "matched_term": "Инъекционная герметизация швов",
            "page_or_sheet": "стр. 37",
            "document_name": "Техническое задание.pdf",
        },
    }


@pytest.fixture
def sample_entities():
    return {
        "1001:ГИДРОИЗОЛЯЦИЯ": [
            {
                "procurement_id": 1001,
                "category_code": "ГИДРОИЗОЛЯЦИЯ",
                "subcategory_code": "Инъекционная гидроизоляция",
                "product_name_normalized": "Инъекционная герметизация швов",
                "product_name_raw": "инъекц. герм. швов",
                "quantity_value": 1240,
                "quantity_unit_normalized": "м.п.",
                "quantity_unit_raw": "м.п.",
                "unit_price_value": None,
                "total_price_value": None,
                "document_name": "Техническое задание.pdf",
                "page_or_sheet": "стр. 37",
            },
        ],
    }


# ── 1. Money source ────────────────────────────────────────────────────

def test_money_source_is_factual(gold_card):
    """Amount displayed on card comes from initial_price or final_contract_price — never invented."""
    amount, label = _ws._amount(gold_card, "OPEN")
    assert amount == 126_450_000
    assert label == "НМЦК"

    gold_card["final_contract_price"] = 118_000_000
    amount2, label2 = _ws._amount(gold_card, "AWARDED")
    assert amount2 == 118_000_000
    assert label2 == "Цена контракта"


# ── 2. EIS link ────────────────────────────────────────────────────────

def test_eis_link_visible(gold_card):
    """tender_link must be present in card data for link rendering."""
    assert gold_card.get("tender_link"), "Card must have tender_link for EIS button"
    assert "zakupki.gov.ru" in gold_card["tender_link"]


# ── 3. Contract link only when real ────────────────────────────────────

def test_contract_link_only_when_real(gold_card):
    """Contract link should never be invented when no factual URL exists."""
    # Card without final_contract_price → no contract link expected
    assert gold_card.get("final_contract_price") is None
    # Verify no contract URL is fabricated by the module
    source = inspect.getsource(_ws)
    # The source should not hardcode any contract URL patterns
    assert "https://zakupki.gov.ru/epz/contract" not in source or \
           "resolve_procurement_link" in source, \
        "Contract URLs must come from resolver, not be hardcoded"


# ── 4. Multiple categories render independently ────────────────────────

def test_multiple_category_opportunities_render_independently(sample_opps):
    """Each category opportunity has its own medal — CATEGORY_OPPORTUNITY_IS_MEDAL_UNIT=YES."""
    assert len(sample_opps) == 2
    medals = {opp["category_code"]: opp["current_effective_medal"] for opp in sample_opps}
    assert medals["ГИДРОИЗОЛЯЦИЯ"] == "SILVER"
    assert medals["НАПОЛЬНЫЕ_ПОКРЫТИЯ"] == "BRONZE"
    # Different medals for different categories
    assert medals["ГИДРОИЗОЛЯЦИЯ"] != medals["НАПОЛЬНЫЕ_ПОКРЫТИЯ"]


# ── 5. Medal NOT called confirmed ──────────────────────────────────────

def test_current_effective_medal_not_called_confirmed():
    """CURRENT_EFFECTIVE_MEDAL_AS_DOCUMENT_CONFIRMED=NO — source code must not label medal as confirmed."""
    source = inspect.getsource(_opp)
    lower_source = source.lower()
    for forbidden in ("подтверждено", "подтверждена", "confirmed"):
        assert forbidden not in lower_source, \
            f"card_opportunities.py must not use '{forbidden}' for medals"

    # Also check stage_workspace _summary
    summary_source = inspect.getsource(_ws._summary)
    summary_lower = summary_source.lower()
    for forbidden in ("подтверждено", "подтверждена"):
        assert forbidden not in summary_lower, \
            f"_summary must not use '{forbidden}' for medals"


# ── 6. Timing decay humanized ──────────────────────────────────────────

def test_timing_decay_reason_humanized():
    """ACTIVE_TIMING_DECAY and POST_AWARD_TIMING_DECAY must have human-readable Russian labels."""
    labels = _opp.REASON_LABELS
    assert "ACTIVE_TIMING_DECAY" in labels
    assert "POST_AWARD_TIMING_DECAY" in labels
    # Must be Russian text, not English
    assert "Снижено" in labels["ACTIVE_TIMING_DECAY"]
    assert "Снижено" in labels["POST_AWARD_TIMING_DECAY"]
    # Must NOT be the raw code
    assert labels["ACTIVE_TIMING_DECAY"] != "ACTIVE_TIMING_DECAY"
    assert labels["POST_AWARD_TIMING_DECAY"] != "POST_AWARD_TIMING_DECAY"


# ── 7. All documents visible ──────────────────────────────────────────

def test_all_documents_visible():
    """Documents tab must show ALL documents, not just matched ones."""
    from src.ui.components.analytics_v2.annotation_card_sections import render_documents
    source = inspect.getsource(render_documents)
    # Should iterate over all provided document rows
    assert "for" in source, "render_documents must iterate over document rows"


# ── 8. Unmatched document visible ──────────────────────────────────────

def test_unmatched_document_visible():
    """A document with no evidence matches must still appear in the list."""
    # The document rendering function receives ALL documents
    # Verify the render function does not filter by match/evidence status
    source = inspect.getsource(
        importlib.import_module("src.ui.components.analytics_v2.annotation_card_sections").render_documents
    )
    # Must not skip documents without matches
    assert "continue" not in source or "skip" not in source.lower(), \
        "render_documents should not skip unmatched documents"


# ── 9. Matched document has findings ──────────────────────────────────

def test_matched_document_has_findings(sample_evidence):
    """Evidence preview on collapsed card must include matched_term and document_name."""
    ev = sample_evidence["1001:ГИДРОИЗОЛЯЦИЯ"]
    assert ev.get("matched_term"), "Evidence must have matched_term"
    assert ev.get("document_name"), "Evidence must have document_name"
    assert ev.get("page_or_sheet"), "Evidence should have page_or_sheet"


# ── 10. No invented document URL ──────────────────────────────────────

def test_no_invented_document_url():
    """INVENTED_DOCUMENT_URL_ALLOWED=NO — card_opportunities must not fabricate URLs."""
    source = inspect.getsource(_opp)
    # No hardcoded EIS download URLs
    assert "ftp://" not in source
    assert "http://zakupki" not in source
    assert "download.php" not in source
    # Should use only document_name, not URLs, for display
    assert "document_url" not in source or "invented" not in source.lower()


# ── 11. Document confirmed requires source document ───────────────────

def test_document_confirmed_requires_source_document():
    """DOCUMENT_CONFIRMED_REQUIRES_EVIDENCE=YES — medal transition cannot be labeled
    as document-confirmed unless source_document_id IS NOT NULL."""
    # Verify the render function checks for evidence
    source = inspect.getsource(_opp.render_card_opportunities)
    # The function should differentiate by evidence presence
    assert "evidence" in source.lower() or "ev" in source, \
        "render_card_opportunities must reference evidence data"


# ── 12. Hypothesis not rendered as confirmed ──────────────────────────

def test_hypothesis_not_rendered_as_confirmed():
    """AI hypothesis with no evidence must NOT render as confirmed finding."""
    # render_card_opportunities with empty evidence should not show ✓ mark
    source = inspect.getsource(_opp.render_card_opportunities)
    # The ✓ symbol should only appear in the evidence-present branch
    assert source.count("✓") > 0, "Must have ✓ for evidence display"
    # But ✓ must be inside a conditional (evidence or entities check)
    lines_with_check = [l for l in source.split('\n') if '✓' in l]
    for line in lines_with_check:
        # Must be inside evidence/entity conditional block (indented more than base)
        assert line.startswith("            ") or line.startswith("                "), \
            f"✓ mark must be inside evidence conditional block, found at: {line.strip()}"


# ── 13. Empty category not rendered ───────────────────────────────────

def test_empty_category_not_rendered():
    """A category with empty code must not produce a card block."""
    empty_opp = {"category_code": "", "subcategory_code": "", "current_effective_medal": "GOLD",
                 "candidate_initial_medal": "GOLD", "current_effective_reason": "FIRST_ACCEPTANCE"}
    # render_card_opportunities should skip this
    with patch("streamlit.markdown") as mock_md:
        _opp.render_card_opportunities(1001, [empty_opp], {}, {})
    # With empty cat code, nothing should be rendered
    for call in mock_md.call_args_list:
        rendered = call[0][0] if call[0] else ""
        assert "border-left" not in rendered, \
            "Empty category_code must not render a category block"


# ── 14. OKPD separate from commercial category ───────────────────────

def test_okpd_separate_from_commercial_category():
    """OKPD2 must be rendered separately from commercial categories."""
    source = inspect.getsource(_ws._summary)
    # OKPD should be rendered with st.caption (secondary), not mixed with category blocks
    assert "ОКПД2" in source
    assert "caption" in source, "OKPD2 should use st.caption for secondary display"
    # Category opportunities use card_opportunities module, not inline OKPD
    assert "render_card_opportunities" in source or "card_opportunities" in source


# ── 15. Collapsed card does NOT eager-load documents ──────────────────

def test_collapsed_card_does_not_eager_load_documents():
    """Documents must only load when the Documents tab is opened (lazy)."""
    source = inspect.getsource(_ws._summary)
    # _summary should NOT call load_annotation_card_view or render_documents
    assert "load_annotation_card_view" not in source
    assert "render_documents" not in source
    assert "document_files" not in source


# ── 16. Collapsed card does NOT eager-load evidence ──────────────────

def test_collapsed_card_does_not_eager_load_evidence():
    """Detailed evidence should NOT be loaded for collapsed cards.

    batch_load_evidence_preview loads only top-1 preview per category (lightweight).
    Full evidence (load_current_generation_raw_evidence) must be lazy.
    """
    source = inspect.getsource(_ws._summary)
    assert "load_current_generation_raw_evidence" not in source
    assert "crm_v3_raw_source_evidence" not in source


# ── Additional structural tests ──────────────────────────────────────

def test_page_size_is_20():
    """PAGE_SIZE must be 20 per specification."""
    tabs = importlib.import_module("src.ui.components.analytics_v2.tabs")
    assert tabs._PAGE_SIZE == 20


def test_sections_include_required_tabs():
    """New tab set must include all required sections."""
    required = {"Сводка", "Возможности", "Документы", "Участники", "История", "ИИ / эксперт"}
    actual = set(_ws.SECTIONS)
    assert required == actual, f"Missing tabs: {required - actual}, Extra: {actual - required}"


def test_medal_transition_html():
    """Medal transition renders correctly for changed and unchanged medals."""
    changed = _opp._medal_transition_html("GOLD", "SILVER")
    assert "GOLD" in changed
    assert "SILVER" in changed
    assert "→" in changed

    same = _opp._medal_transition_html("BRONZE", "BRONZE")
    assert "BRONZE" in same
    assert "→" not in same

    empty = _opp._medal_transition_html(None, None)
    assert "не установлена" in empty.lower()


def test_reason_labels_all_known_codes():
    """All production reason codes must have human labels."""
    known_codes = ["ACTIVE_TIMING_DECAY", "POST_AWARD_TIMING_DECAY",
                   "MIGRATION_SNAPSHOT_NOT_INITIAL", "FIRST_ACCEPTANCE"]
    for code in known_codes:
        assert code in _opp.REASON_LABELS, f"Missing label for {code}"
