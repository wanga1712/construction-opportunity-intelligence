from pathlib import Path

from src.services.annotation_state_service import classify_annotation_payload


def test_torgi_expert_workset_does_not_use_manager_publication_as_admission_gate():
    source = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
    loader = source.split("def _load_torgi", 1)[1].split("def _load_queue_statuses_batch", 1)[0]
    assert "factual_open_torgi_sql" in loader
    assert "torgi_publication_sql_filters" not in loader
    assert "publication_schema_ready" not in loader
    # Effective open SQL itself still encodes factual torgi/open predicates.
    from src.services.effective_lifecycle import factual_open_torgi_sql

    open_sql = factual_open_torgi_sql("cp")
    assert "cp.crm_stage = 'torgi'" in open_sql
    assert "cp.award_status = 'submission_open'" in open_sql
    assert "cp.end_date IS NOT NULL" in open_sql


def test_large_stages_use_true_id_counts_and_bounded_pages():
    source = Path("src/ui/components/analytics_v2/tabs.py").read_text(encoding="utf-8")
    assert "_PAGE_SIZE = 25" in source
    assert "_stage_workset_ids" in source
    assert "LIMIT 500" not in source
    assert "Показано" in source or "показано" in source


def test_ai_out_of_profile_does_not_define_human_not_interesting():
    assert classify_annotation_payload(None) == "UNANNOTATED"
    assert classify_annotation_payload({"ai_status": "OUT_OF_PROFILE"}) == "ANNOTATED"
    assert classify_annotation_payload({"expert_scope_verdict": "OUT_OF_PROFILE"}) == "NOT_INTERESTING"


def test_compact_card_contract_and_source_action_order():
    source = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert "font-size:24px" in source
    assert "💰" in source and "📅" in source and "📜" in source
    assert "st.metric" not in source
    assert "route:" not in source and "files/matches/evidence" not in source
    assert "_source_actions(card)" in source
    assert "st.pills" in source
    assert source.index("_source_actions(card)") < source.index("st.pills")
    assert "label_visibility=\"collapsed\"" in source
    assert "text-overflow" not in source and "ellipsis" not in source


def test_empty_commercial_values_are_omitted_and_product_is_not_inferred():
    source = Path("src/ui/components/analytics_v2/stage_workspace.py").read_text(encoding="utf-8")
    assert "def _clean(value" in source
    # Product category is never invented from title/OKPD text on the card surface.
    assert "infer_product" not in source.lower()
    assert "product_from_okpd" not in source.lower()
