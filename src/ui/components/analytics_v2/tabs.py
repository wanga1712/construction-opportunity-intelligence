"""Вкладки рабочей области аналитического контура v2.

Lifecycle feeds render shared lazy inline procurement cards.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from src.ui.components.analytics_v2.annotation_queue import bind_and_advance
from src.ui.components.analytics_v2.card_feed import render_card_feed
from src.ui.components.analytics_v2.stage_workspace import (
    filtered_review_ids,
    render_review_filter,
    render_stage_workspace,
)

_SESSION_TORGI    = "selected_torgi_id"
_SESSION_KOMISSIA = "selected_komissia_id"
_SESSION_RAZYGR   = "selected_razygr_id"
_PAGE_SIZE = 25
FARTHEST_DEADLINE_FIRST = "FARTHEST_DEADLINE_FIRST"
NEAREST_DEADLINE_FIRST = "NEAREST_DEADLINE_FIRST"
DEADLINE_SORT_LABELS = {
    FARTHEST_DEADLINE_FIRST: "Сначала дальние",
    NEAREST_DEADLINE_FIRST: "Сначала ближайшие",
}


def _render_first_stage_dataset_panel(crm_db, annotation_states: dict) -> None:
    """Read-only staged dataset: object / mode / category / commercial / medal."""
    from src.services.annotation_category_gate import (
        IN_CATEGORY,
        OUT_OF_CATEGORY,
        UNCERTAIN,
        first_stage_dataset_rows,
    )
    from src.services.annotation_state_service import REVIEWED, UNREVIEWED, annotation_state_counts
    from src.services.expert_commercial_entry import COMMERCIAL, NON_COMMERCIAL
    from src.services.expert_medal_stage import MEDAL_VALUES
    from src.services.expert_object_taxonomy import OBJECT_SECTOR_VALUES
    from src.services.expert_procurement_mode import PROCUREMENT_MODE_OPTIONS

    counts = annotation_state_counts(annotation_states)
    with st.expander(
        "Staged датасет (объект → тип → категории → коммерция → медаль)",
        expanded=False,
    ):
        st.caption(
            f"Проверено: {counts.get(REVIEWED, 0)} · "
            f"Не проверено: {counts.get(UNREVIEWED, 0)} · "
            f"В категории: {counts.get(IN_CATEGORY, 0)} · "
            f"Вне категорий: {counts.get(OUT_OF_CATEGORY, 0)} · "
            f"Коммерчески: {counts.get(COMMERCIAL, 0)} · "
            f"Не коммерчески: {counts.get(NON_COMMERCIAL, 0)}"
        )
        rows = first_stage_dataset_rows(crm_db, limit=120)
        if not rows:
            st.info("Пока нет staged-разметок. Цель smoke-batch: 30–40.")
            return
        f1, f2, f3, f4, f5 = st.columns(5)
        reviewed_only = f1.selectbox(
            "Статус",
            ["Все", "Проверено", "Не проверено / частично"],
            key="staged_ds_reviewed",
        )
        sector_f = f2.selectbox(
            "Сектор",
            ["Все"] + list(OBJECT_SECTOR_VALUES),
            key="staged_ds_sector",
        )
        mode_f = f3.selectbox(
            "Тип закупки",
            ["Все"] + list(PROCUREMENT_MODE_OPTIONS),
            key="staged_ds_mode",
        )
        scope_f = f4.selectbox(
            "Категории",
            ["Все", IN_CATEGORY, OUT_OF_CATEGORY, UNCERTAIN],
            key="staged_ds_scope",
        )
        entry_f = f5.selectbox(
            "Коммерция / медаль",
            ["Все", COMMERCIAL, NON_COMMERCIAL, UNCERTAIN, *MEDAL_VALUES],
            key="staged_ds_entry",
        )
        filtered = []
        for row in rows:
            if reviewed_only == "Проверено" and not row.get("staged_complete"):
                continue
            if reviewed_only.startswith("Не проверено") and row.get("staged_complete"):
                continue
            if sector_f != "Все" and row.get("expert_object_sector") != sector_f:
                continue
            if mode_f != "Все" and row.get("expert_procurement_mode") != mode_f:
                continue
            if scope_f != "Все" and row.get("expert_category_scope") != scope_f:
                continue
            if entry_f != "Все":
                if entry_f in MEDAL_VALUES and row.get("expert_medal") != entry_f:
                    continue
                if entry_f not in MEDAL_VALUES and row.get("expert_commercial_entry") != entry_f:
                    continue
            filtered.append(row)
        st.dataframe(filtered, use_container_width=True, hide_index=True)


def torgi_deadline_order_by(sort_mode: str) -> str:
    """Trusted deterministic SQL ordering, applied before LIMIT/OFFSET."""
    direction = "ASC" if sort_mode == NEAREST_DEADLINE_FIRST else "DESC"
    return (
        f"cp.end_date {direction} NULLS LAST, "
        "cp.initial_price DESC NULLS LAST, cp.id DESC"
    )


def _reset_torgi_page() -> None:
    st.session_state.pop("torgi_workset_page", None)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _pg():
    from src.services.crm_db_runtime import require_crm_db_connect_kwargs
    return require_crm_db_connect_kwargs()


def _get_category_filter(stage: str) -> tuple[str, dict]:
    """
    Читает session_state фильтр категорий для стадии.
    Возвращает (sql_fragment, params) для подстановки в AND.
    Пустой/полный выбор → 'TRUE', {}.
    """
    from src.services.crm_profile_service import build_category_sql_filter

    cats_key = f"_catf_{stage}_cats"
    selected_cats: set = st.session_state.get(cats_key, set())
    # Если ключ отсутствует (фильтр ещё не инициализирован) — не фильтруем
    if cats_key not in st.session_state:
        return "TRUE", {}
    if not st.session_state.get(f"_catf_{stage}_explicit", False):
        return "TRUE", {}
    return build_category_sql_filter(selected_cats, set())


def _stage_workset_ids(stage: str) -> list[int]:
    """Return factual filtered workset IDs for true counts (one bounded-column query)."""
    import psycopg2
    if stage == "torgi":
        from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
        where = "cp.crm_stage='torgi' AND cp.award_status='submission_open' AND " + actionable_submission_sql("cp")
        cat_stage = "torgi"
    elif stage == "commission":
        where = "cp.crm_stage='torgi' AND cp.award_status IN ('submission_closed_waiting_award','award_not_found')"
        cat_stage = "commission"
    else:
        where = "cp.crm_stage='razygranye'"
        cat_stage = "razygranye"
    cat_sql, params = _get_category_filter(cat_stage)
    conn = psycopg2.connect(**_pg())
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT cp.id
                    FROM crm_procurements cp
                    LEFT JOIN crm_category_candidates cc ON cc.procurement_id = cp.id
                    WHERE {where} AND ({cat_sql}) ORDER BY cp.id""",
                params,
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def _page_offset(stage: str, total: int) -> tuple[int, int]:
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = st.number_input("Страница", 1, pages, 1, key=f"{stage}_workset_page")
    return int(page), (int(page) - 1) * _PAGE_SIZE


def _load_torgi(limit: int = 25, offset: int = 0,
                sort_mode: str = FARTHEST_DEADLINE_FIRST,
                allowed_ids: list[int] | None = None) -> list[dict]:
    """Lifecycle-valid expert workset; manager publication is not an admission gate."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        from src.services.db_bootstrap import connect_databases
        from src.services.commercial_routing_v3.submission_window import actionable_submission_sql
        cat_sql, cat_params = _get_category_filter("torgi")
        params = dict(cat_params); params.update({"limit": limit, "offset": offset})
        review_sql = "TRUE"
        if allowed_ids is not None:
            review_sql = "cp.id = ANY(%(allowed_ids)s)"
            params["allowed_ids"] = allowed_ids or [-1]

        order_by = torgi_deadline_order_by(sort_mode)
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT DISTINCT cp.id, cp.contract_number, cp.auction_name,
                       cp.initial_price, cp.customer, cp.delivery_region,
                       cp.okpd_code, cp.okpd_name, cp.crm_category,
                       cp.contractor_name, cp.contractor_inn,
                       cp.match_score, cp.signal_score, cp.commercial_score,
                       cp.processing_stage, cp.matched_keywords,
                       cp.file_count, cp.match_count, cp.evidence_count,
                       cp.start_date, cp.end_date, cp.delivery_end_date,
                       cp.tender_link, cp.award_status,
                       cp.crm_stage, cp.crm_profile_id,
                       cp.source_table, cp.source_id,
                       cp.crm_created_at, cp.crm_updated_at, cp.source_updated_at,
                       cp.ai_assessment_status, cp.ai_assessment_version,
                       cp.ai_assessment_stability, cp.ai_stability_count,
                       ai.proposed_route_profile, ai.proposed_object_type,
                       ai.proposed_procurement_type, ai.confidence,
                       ai.reasons, ai.normalized_result,
                       EXISTS (
                           SELECT 1 FROM crm_procurement_category_opportunities o
                           WHERE o.procurement_id = cp.id
                             AND o.status = 'CURRENT'
                             AND o.confirmed_base_medal IS NOT NULL
                       ) AS is_confirmed
                FROM crm_procurements cp
                LEFT JOIN crm_category_candidates cc ON cc.procurement_id = cp.id
                LEFT JOIN procurement_ai_assessments ai ON ai.procurement_id = cp.id AND ai.is_current = TRUE
                WHERE cp.crm_stage = 'torgi'
                  AND cp.award_status = 'submission_open'
                  AND {actionable_submission_sql("cp")}
                  AND ({cat_sql})
                  AND ({review_sql})
                ORDER BY {order_by}
                LIMIT %(limit)s OFFSET %(offset)s
            """, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        st.warning(f"Ошибка загрузки торгов: {e}")
        return []


def _load_queue_statuses_batch(contract_numbers: list) -> dict:
    """Batch queue status lookup. Returns {contract_number: status}. One query total."""
    if not contract_numbers:
        return {}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from src.services.crm_db_runtime import require_crm_db_connect_kwargs
        tm_pg = dict(require_crm_db_connect_kwargs())
        tm_pg["dbname"] = "tender_monitor"
        tm_pg["connect_timeout"] = 5
        conn = psycopg2.connect(**tm_pg)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT ON (contract_reg_number)
                    contract_reg_number, status
                FROM document_processing_queue
                WHERE contract_reg_number = ANY(%s)
                ORDER BY contract_reg_number, id DESC
            """, (list(contract_numbers),))
            result = {r["contract_reg_number"]: r["status"] for r in cur.fetchall()}
        conn.close()
        return result
    except Exception:
        return {}


def _torgi_sort_key(card: dict, eff_map: dict) -> tuple:
    """Explicit rank tuple for sorting. Higher tuple = shown first.

    Groups (descending priority):
      GOLD         → base 80_000
      SILVER       → base 60_000
      BRONZE       → base 40_000
      WOOD         → base 20_000
      UNASSESSED   → base  5_000
      INCOMPLETE   → base  3_000
      FAILED       → base  1_000
      OUT_OF_PROFILE → base 0

    Inside group: (eff_score DESC, time_score, price_bonus)
    Dead window (wdays <= 1): sink inside group.
    """
    from src.ui.components.analytics_v2.card_trust import workdays_left
    from src.services.effective_assessment import SORT_GROUP_RANK

    pid = card.get("id")
    eff = eff_map.get(pid) if eff_map else None

    wdays = workdays_left(card.get("end_date")) or 0
    price = card.get("initial_price") or 0

    # Time score
    if wdays <= 1:
        time_score = 0
    elif wdays >= 14:
        time_score = 400
    elif wdays >= 7:
        time_score = 300
    elif wdays >= 4:
        time_score = 200
    elif wdays >= 2:
        time_score = 100
    else:
        time_score = 20

    # Price bonus
    if price >= 10_000_000:
        price_bonus = 150
    elif price >= 3_000_000:
        price_bonus = 100
    elif price >= 1_000_000:
        price_bonus = 50
    elif price >= 500_000:
        price_bonus = 20
    else:
        price_bonus = 0

    if eff is None:
        group_rank = SORT_GROUP_RANK["UNASSESSED"]
        score = 0.0
    else:
        group_rank = SORT_GROUP_RANK.get(eff.sort_group, 0)
        score = eff.best_candidate_score or 0.0

    return (group_rank, score, time_score, price_bonus)


# Keep legacy name for backward compatibility with non-torgi tabs
def _torgi_priority_score(card: dict) -> int:
    """Legacy fallback (no effective map). Used by komissia / razygranye."""
    from src.ui.components.analytics_v2.card_trust import workdays_left
    wdays = workdays_left(card.get("end_date")) or 0
    price = card.get("initial_price") or 0
    signal = card.get("signal_score") or card.get("match_score") or 0
    if wdays <= 1:
        return int(signal)
    time_score = 400 if wdays >= 14 else 300 if wdays >= 7 else 200 if wdays >= 4 else 100 if wdays >= 2 else 20
    price_bonus = 150 if price >= 10_000_000 else 100 if price >= 3_000_000 else 50 if price >= 1_000_000 else 20 if price >= 500_000 else 0
    return time_score + price_bonus + min(int(signal), 100)


def _load_effective_map(cards: list[dict]) -> dict:
    """One batch query for list signals; never performs document resolution."""
    if not cards:
        return {}
    from src.services.db_bootstrap import connect_databases
    from src.services.effective_assessment import get_effective_business_assessments
    try:
        _, _, crm_db, _ = connect_databases()
        return get_effective_business_assessments([card["id"] for card in cards], crm_db)
    except Exception as exc:
        st.warning(f"Effective assessment load error: {exc}")
        return {}



def _load_komissia(limit: int = 25, offset: int = 0) -> list[dict]:
    """Подача закрыта — ждём решения комиссии."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        cat_sql, cat_params = _get_category_filter("commission")
        params = dict(cat_params); params.update({"limit": limit, "offset": offset})

        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT DISTINCT cp.id, cp.contract_number, cp.auction_name,
                       cp.initial_price, cp.customer, cp.delivery_region,
                       cp.okpd_code, cp.okpd_name, cp.crm_category,
                       cp.contractor_name, cp.contractor_inn,
                       cp.match_score, cp.matched_keywords,
                       cp.file_count, cp.match_count, cp.evidence_count,
                       cp.start_date, cp.end_date, cp.delivery_end_date,
                       cp.tender_link, cp.award_status,
                       cp.crm_stage, cp.crm_profile_id,
                       cp.source_table, cp.source_id,
                       cp.crm_created_at, cp.crm_updated_at, cp.source_updated_at,
                       cp.ai_assessment_status, cp.ai_assessment_version,
                       cp.ai_assessment_stability, cp.ai_stability_count,
                       ai.proposed_route_profile, ai.proposed_object_type,
                       ai.proposed_procurement_type, ai.confidence,
                       ai.reasons, ai.normalized_result
                FROM crm_procurements cp
                LEFT JOIN crm_category_candidates cc ON cc.procurement_id = cp.id
                LEFT JOIN procurement_ai_assessments ai ON ai.procurement_id = cp.id AND ai.is_current = TRUE
                WHERE cp.crm_stage = 'torgi'
                  AND cp.award_status IN ('submission_closed_waiting_award', 'award_not_found')
                  AND ({cat_sql})
                ORDER BY cp.end_date DESC, cp.match_score DESC
                LIMIT %(limit)s OFFSET %(offset)s
            """, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        st.warning(f"Ошибка загрузки комиссии: {e}")
        return []


def _load_razygranye(limit: int = 25, offset: int = 0) -> list[dict]:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        cat_sql, cat_params = _get_category_filter("razygranye")
        params = dict(cat_params); params.update({"limit": limit, "offset": offset})

        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT DISTINCT cp.id, cp.contract_number, cp.auction_name,
                       cp.initial_price, cp.final_contract_price,
                       cp.customer, cp.delivery_region,
                       cp.okpd_code, cp.okpd_name, cp.crm_category,
                       cp.contractor_name, cp.contractor_inn,
                       cp.match_score, cp.matched_keywords,
                       cp.file_count, cp.match_count, cp.evidence_count,
                       cp.winner_name, cp.winner_inn,
                       cp.start_date, cp.end_date,
                       cp.contract_signed_at, cp.execution_end_at,
                       cp.delivery_end_date,
                       cp.commercial_window_state,
                       cp.tender_link, cp.award_status,
                       cp.crm_stage, cp.crm_profile_id,
                       cp.source_table, cp.source_id,
                       cp.crm_created_at, cp.crm_updated_at, cp.source_updated_at,
                       cp.ai_assessment_status, cp.ai_assessment_version,
                       cp.ai_assessment_stability, cp.ai_stability_count,
                       ai.proposed_route_profile, ai.proposed_object_type,
                       ai.proposed_procurement_type, ai.confidence,
                       ai.reasons, ai.normalized_result,
                       EXISTS (
                           SELECT 1 FROM crm_procurement_category_opportunities o
                           WHERE o.procurement_id = cp.id
                             AND o.status = 'CURRENT'
                             AND o.confirmed_base_medal IS NOT NULL
                       ) AS is_confirmed
                FROM crm_procurements cp
                LEFT JOIN crm_category_candidates cc ON cc.procurement_id = cp.id
                LEFT JOIN procurement_ai_assessments ai ON ai.procurement_id = cp.id AND ai.is_current = TRUE
                WHERE cp.crm_stage = 'razygranye'
                  AND ({cat_sql})
                ORDER BY cp.contract_signed_at DESC NULLS LAST
                LIMIT %(limit)s OFFSET %(offset)s
            """, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        st.warning(f"Ошибка загрузки разыгранных: {e}")
        return []


def _load_sync_info() -> dict:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT status, finished_at FROM crm_sync_jobs ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def _fmt_date(val) -> str:
    if val is None: return "—"
    try:
        if isinstance(val, date): return val.strftime("%d.%m.%Y")
        return str(val)[:10]
    except Exception: return str(val)


# ─── Торги-таб ────────────────────────────────────────────────────────────────

_TORGI_AI_FILTERS = ["Все", "Неоцененные", "Неполные оценки", "Ошибки AI", "IN_PROFILE", "OUT_OF_PROFILE"]




def _render_review_filter_from_counts(
    counts: dict[str, int], session_key: str, *, on_change=None
) -> str:
    """Render review filter pills using pre-computed SQL counts."""
    from src.ui.components.analytics_v2.stage_workspace import FILTERS
    labels = [f"{label} ?? {counts.get(key, 0)}" for key, label in FILTERS]
    selected_label = st.pills(
        "??????????????",
        labels,
        default=labels[0],
        key=f"annotation_state_filter_{session_key}",
        on_change=on_change,
    )
    return FILTERS[labels.index(selected_label)][0]


def _render_torgi_tab() -> None:
    col_hdr, col_sync = st.columns([3, 1])
    with col_sync:
        info = _load_sync_info()
        if info:
            st.caption(f"Обновлено: {_fmt_date(info.get('finished_at'))}")
        if st.button("↻", key="torgi_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    workset_ids = _stage_workset_ids("torgi")
    sort_mode = st.radio(
        "Сортировка по сроку",
        list(DEADLINE_SORT_LABELS),
        format_func=lambda value: DEADLINE_SORT_LABELS[value],
        horizontal=True,
        key="torgi_deadline_sort",
        on_change=_reset_torgi_page,
    )
    from src.services.annotation_state_service import (
        count_annotation_states_sql,
        load_current_annotation_states,
    )
    from src.services.db_bootstrap import connect_databases
    _, _, crm_db, _ = connect_databases()
    # ── SQL-level counts (no full Python workset load) ──
    sql_counts = count_annotation_states_sql(workset_ids, crm_db)
    selected_review = _render_review_filter_from_counts(
        sql_counts, _SESSION_TORGI, on_change=_reset_torgi_page
    )
    # ── Filtered count for pagination ──
    filtered_total = sql_counts.get(selected_review, sql_counts["ALL"])
    page, offset = _page_offset("torgi", filtered_total)
    cards = _load_torgi(_PAGE_SIZE, offset, sort_mode, workset_ids)
    # ── Page-only annotation state load (max 25 IDs) ──
    page_ids = [c["id"] for c in cards]
    annotation_states = load_current_annotation_states(page_ids, crm_db)

    if not cards:
        st.info("Нет тендеров в стадии торгов.")
        return

    # ── Batch-load processing results (no N+1) ─────────────────────────────
    from src.ui.components.analytics_v2 import card_processing
    proc_results = card_processing.load_batch(cards)
    for card in cards:
        card_processing.enrich_card(card, proc_results.get(card["id"], {}))

    # ── Bulk-load effective assessments (single contract, no N+1) ──────────
    eff_map = _load_effective_map(cards)

    cards_layer = cards

    filtered = cards_layer

    # SQL deadline ordering is global and already applied before pagination.
    filtered = bind_and_advance(filtered, _SESSION_TORGI, st.session_state)

    selected_id = st.session_state.get(_SESSION_TORGI)
    st.markdown(f"### Идут торги · {len(workset_ids)}")
    st.caption(f"Показано {offset + 1}–{offset + len(cards)} из {filtered_total}")
    _render_first_stage_dataset_panel(crm_db, annotation_states)

    render_stage_workspace(
        filtered,
        session_key=_SESSION_TORGI,
        stage="OPEN",
        stage_label="Идут торги",
        effective_map=eff_map,
        workset_ids=workset_ids,
        annotation_states=annotation_states,
        selected_annotation_filter=selected_review,
    )



# ─── Комиссия-таб ─────────────────────────────────────────────────────────────

def _render_komissia_tab() -> None:
    col_hdr, col_sync = st.columns([3, 2])
    with col_sync:
        if st.button("↻ Обновить", key="komissia_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    workset_ids = _stage_workset_ids("commission")
    page, offset = _page_offset("commission", len(workset_ids))
    cards = _load_komissia(_PAGE_SIZE, offset)

    if not cards:
        st.info("Нет тендеров на стадии работы комиссии.")
        return

    waiting   = [c for c in cards if c["award_status"] == "submission_closed_waiting_award"]
    not_found = [c for c in cards if c["award_status"] == "award_not_found"]
    filtered = waiting + not_found
    filtered = bind_and_advance(filtered, _SESSION_KOMISSIA, st.session_state)
    selected_id = st.session_state.get(_SESSION_KOMISSIA)

    st.caption(
        f"Комиссия · {len(workset_ids)} · показано {offset + 1}–{offset + len(cards)}"
    )

    render_stage_workspace(
        filtered,
        session_key=_SESSION_KOMISSIA,
        stage="COMMISSION",
        stage_label="Комиссия",
        effective_map=_load_effective_map(filtered),
        workset_ids=workset_ids,
    )


# ─── Разыгранные-таб ──────────────────────────────────────────────────────────

def _render_razygranye_tab() -> None:
    col_hdr, col_sync = st.columns([3, 2])
    with col_sync:
        if st.button("↻ Обновить данные", key="razygr_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    workset_ids = _stage_workset_ids("razygranye")
    page, offset = _page_offset("razygranye", len(workset_ids))
    cards = _load_razygranye(_PAGE_SIZE, offset)
    if not cards:
        st.info("Нет разыгранных закупок.")
        return

    cards_layer = cards
    cards_layer = bind_and_advance(cards_layer, _SESSION_RAZYGR, st.session_state)

    st.caption(
        f"Разыгранные · {len(workset_ids)} · показано {offset + 1}–{offset + len(cards_layer)}"
    )

    render_stage_workspace(
        cards_layer,
        session_key=_SESSION_RAZYGR,
        stage="AWARDED",
        stage_label="Разыгранные",
        effective_map=_load_effective_map(cards_layer),
        workset_ids=workset_ids,
    )


# ─── На рассмотрении-таб (CRM-SYNC-1) ───────────────────────────────────────

_SESSION_REVIEW_PAGE = "review_page"

_REVIEW_STAGE_OPTIONS = ["Все", "torgi", "razygranye", "commission"]
_REVIEW_QUAL_OPTIONS  = ["Все", "unassessed", "candidate", "confirmed", "rejected", "manual_review"]


def _load_review_counts() -> dict:
    """Счётчики по всей выборке — один запрос."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE crm_stage = 'torgi')       AS open_cnt,
                    count(*) FILTER (WHERE crm_stage = 'razygranye')  AS awarded_cnt,
                    count(*) FILTER (WHERE crm_stage = 'commission')  AS commission_cnt,
                    count(*) FILTER (WHERE evidence_count > 0)        AS with_evidence,
                    count(*) FILTER (WHERE match_count > 0)           AS with_matches,
                    count(*) FILTER (WHERE qualification_state = 'unassessed')    AS unassessed_cnt,
                    count(*) FILTER (WHERE qualification_state = 'candidate')     AS candidate_cnt,
                    count(*) FILTER (WHERE qualification_state = 'manual_review') AS manual_cnt
                FROM crm_procurements
                WHERE qualification_state IN ('unassessed', 'candidate', 'manual_review')
            """)
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        st.warning(f"Ошибка загрузки счётчиков: {e}")
        return {}


def _load_review_page(
    crm_stage_filter: str,
    qual_filter: str,
    has_evidence: str,
    page: int,
    page_size: int = 50,
) -> list[dict]:
    """Загружает страницу объектов для вкладки «На рассмотрении»."""
    where_parts = ["qualification_state IN ('unassessed','candidate','manual_review')"]
    params: dict = {}

    if crm_stage_filter != "Все":
        where_parts.append("crm_stage = %(stage)s")
        params["stage"] = crm_stage_filter

    if qual_filter != "Все":
        where_parts.append("qualification_state = %(qual)s")
        params["qual"] = qual_filter

    if has_evidence == "Да":
        where_parts.append("evidence_count > 0")
    elif has_evidence == "Нет":
        where_parts.append("evidence_count = 0")

    where_sql = " AND ".join(where_parts)
    params["limit"]  = page_size
    params["offset"] = page * page_size

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    id, source_table, source_id, contract_number, auction_name,
                    initial_price, customer, delivery_region,
                    crm_stage, award_status, qualification_state, object_type,
                    match_count, interesting_count, evidence_count, file_count,
                    end_date, last_daemon_at,
                    tender_link, crm_created_at, crm_updated_at
                FROM crm_procurements
                WHERE {where_sql}
                ORDER BY evidence_count DESC, match_count DESC, id DESC
                LIMIT %(limit)s OFFSET %(offset)s
            """, params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        st.warning(f"Ошибка загрузки списка: {e}")
        return []


def _load_last_sync_job() -> dict:
    """Последний job sync_all_processed из crm_sync_jobs."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(**_pg())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT status, finished_at, processed_count, updated_count, error_count
                FROM crm_sync_jobs
                WHERE job_type = 'sync_all_processed'
                ORDER BY id DESC LIMIT 1
            """)
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def _enqueue_sync_job(requested_by: str = "manual_ui") -> bool:
    """Вставляет job со status='queued'. Не запускает реальный sync в render-потоке."""
    try:
        import psycopg2
        conn = psycopg2.connect(**_pg())
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO crm_sync_jobs
                    (job_type, trigger_type, requested_by, status, created_at)
                VALUES ('sync_all_processed', 'manual_ui', %(by)s, 'queued', now())
            """, {"by": requested_by})
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Ошибка постановки sync в очередь: {e}")
        return False


def _qual_badge(q: str) -> str:
    badges = {
        "unassessed":    "⬜ не оценён",
        "candidate":     "🟡 кандидат",
        "confirmed":     "🟢 подтверждён",
        "rejected":      "🔴 отклонён",
        "out_of_profile":"⚫ вне профиля",
        "manual_review": "🔵 ручная проверка",
    }
    return badges.get(q, q)


def _stage_badge(s: str) -> str:
    badges = {
        "torgi":      "OPEN",
        "razygranye": "AWARDED",
        "commission": "COMMISSION",
    }
    return badges.get(s, s)


def _render_review_tab() -> None:
    """На рассмотрении — объекты с документами/matches, не подтверждённые в lifecycle."""

    # ── Sync status ──
    last_job = _load_last_sync_job()
    col_info, col_btn = st.columns([4, 1])
    with col_info:
        if last_job:
            ts = _fmt_date(last_job.get("finished_at"))
            cnt = last_job.get("processed_count") or 0
            st.caption(
                f"Последняя синхронизация: {ts} · +{cnt} объектов · {last_job.get('status','?')}"
            )
        else:
            st.caption("Синхронизация ещё не запускалась")
    with col_btn:
        if st.button("↻ Запустить sync", key="review_sync_btn"):
            if _enqueue_sync_job():
                st.success("Sync поставлен в очередь")

    st.markdown("---")

    # ── Фильтры ──
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        stage_filter = st.selectbox("Lifecycle", _REVIEW_STAGE_OPTIONS, key="review_stage_f")
    with col_f2:
        qual_filter = st.selectbox("Qualification", _REVIEW_QUAL_OPTIONS, key="review_qual_f")
    with col_f3:
        evidence_filter = st.selectbox("Есть evidence", ["Все", "Да", "Нет"], key="review_ev_f")

    # ── Счётчики (по всей выборке, независимо от фильтров и страницы) ──
    counts = _load_review_counts()
    if counts:
        total = counts.get("total", 0)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Всего найдено", total)
        c2.metric("Кандидатов", counts.get("candidate_cnt", 0))
        c3.metric("С evidence", counts.get("with_evidence", 0))
        c4.metric("С matches", counts.get("with_matches", 0))

        st.caption(
            f"OPEN: {counts.get('open_cnt',0)} · "
            f"AWARDED: {counts.get('awarded_cnt',0)} · "
            f"COMMISSION: {counts.get('commission_cnt',0)} · "
            f"Не оценено: {counts.get('unassessed_cnt',0)} · "
            f"Ручная проверка: {counts.get('manual_cnt',0)}"
        )

    # ── Pagination ──
    page = st.session_state.get(_SESSION_REVIEW_PAGE, 0)
    page_size = 50

    rows = _load_review_page(stage_filter, qual_filter, evidence_filter, page, page_size)

    shown_start = page * page_size + 1
    shown_end   = page * page_size + len(rows)
    st.caption(f"Показано: {shown_start}–{shown_end}" if rows else "Ничего не найдено")

    if not rows:
        st.info("По выбранным фильтрам ничего не найдено.")
        return

    # ── Карточки ──
    for card in rows:
        stage_lbl = _stage_badge(card.get("crm_stage", ""))
        qual_lbl  = _qual_badge(card.get("qualification_state", ""))
        price_str = (
            f"{card['initial_price']:,.0f} ₽"
            if card.get("initial_price") else "—"
        )
        ev  = card.get("evidence_count", 0) or 0
        mc  = card.get("match_count", 0) or 0
        fc  = card.get("file_count", 0) or 0
        end = _fmt_date(card.get("end_date"))

        with st.expander(
            f"[{stage_lbl}] {(card.get('auction_name') or '—')[:80]}  "
            f"| {price_str}  | до {end}",
            expanded=False,
        ):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.markdown(f"**Статус:** {qual_lbl}")
                st.markdown(f"**Источник:** {card.get('source_table','?')} #{card.get('source_id','?')}")
                if card.get("customer"):
                    st.markdown(f"**Заказчик:** {card['customer'][:60]}")
            with col_b:
                st.metric("Matches", mc)
                st.metric("Evidence", ev)
                st.metric("Файлы", fc)
            with col_c:
                if card.get("tender_link"):
                    st.markdown(f"[Открыть на портале]({card['tender_link']})")
                st.markdown(f"**Дедлайн:** {end}")
                st.markdown(f"**Обновлено:** {_fmt_date(card.get('last_daemon_at'))}")

    # ── Кнопка «Загрузить ещё» ──
    if len(rows) == page_size:
        if st.button("Загрузить ещё 50", key=f"review_more_{page}"):
            st.session_state[_SESSION_REVIEW_PAGE] = page + 1
            st.rerun()
    else:
        if page > 0 and st.button("↩ В начало", key="review_reset"):
            st.session_state[_SESSION_REVIEW_PAGE] = 0
            st.rerun()


# ─── Главная функция ──────────────────────────────────────────────────────────

def render_tabs() -> None:
    """Лиды / Подготовка к торгам / Идут торги / Комиссия / На рассмотрении / Разыгранные."""
    tabs = st.tabs([
        "Лиды", "Подготовка к торгам", "Идут торги",
        "Комиссия", "На рассмотрении", "Разыгранные",
    ])

    with tabs[0]:
        render_card_feed()

    with tabs[1]:
        st.info("Раздел будет подключён на следующем этапе")

    with tabs[2]:
        _render_torgi_tab()

    with tabs[3]:
        _render_komissia_tab()

    with tabs[4]:
        _render_review_tab()

    with tabs[5]:
        _render_razygranye_tab()
