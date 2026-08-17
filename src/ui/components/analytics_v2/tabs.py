"""Вкладки рабочей области аналитического контура v2.

Layout внутри правой панели:
  - Список компактных карточек (card_compact)
  - При выборе: полный детейл ниже (card_detail) с кнопкой «Назад»
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from src.ui.components.analytics_v2.card_feed import render_card_feed
from src.ui.components.analytics_v2.card_compact import render_compact_card
# Removed render_card_detail import

_SESSION_TORGI    = "selected_torgi_id"
_SESSION_KOMISSIA = "selected_komissia_id"
_SESSION_RAZYGR   = "selected_razygr_id"


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
    return build_category_sql_filter(selected_cats, set())


def _load_torgi() -> list[dict]:
    """Только submission_open и ещё не истёкшие."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        cat_sql, cat_params = _get_category_filter("torgi")

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
                  AND cp.end_date >= CURRENT_DATE
                  AND ({cat_sql})
                ORDER BY cp.end_date ASC, cp.match_score DESC
                LIMIT 500
            """, cat_params)
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



def _load_komissia() -> list[dict]:
    """Подача закрыта — ждём решения комиссии."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        cat_sql, cat_params = _get_category_filter("commission")

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
                LIMIT 500
            """, cat_params)
            rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        st.warning(f"Ошибка загрузки комиссии: {e}")
        return []


def _load_razygranye() -> list[dict]:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        cat_sql, cat_params = _get_category_filter("razygranye")

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
                LIMIT 500
            """, cat_params)
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


def _render_torgi_tab() -> None:
    col_hdr, col_sync = st.columns([3, 1])
    with col_sync:
        info = _load_sync_info()
        if info:
            st.caption(f"Обновлено: {_fmt_date(info.get('finished_at'))}")
        if st.button("↻", key="torgi_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    cards = _load_torgi()

    if not cards:
        st.info("Нет тендеров в стадии торгов.")
        return

    # ── Batch-load processing results (no N+1) ─────────────────────────────
    from src.ui.components.analytics_v2 import card_processing
    proc_results = card_processing.load_batch(cards)
    for card in cards:
        card_processing.enrich_card(card, proc_results.get(card["id"], {}))

    # ── Bulk-load effective assessments (single contract, no N+1) ──────────
    from src.services.db_bootstrap import connect_databases
    from src.services.effective_assessment import get_effective_business_assessments
    eff_map: dict = {}
    try:
        _, _, crm_db, _ = connect_databases()
        pids = [c["id"] for c in cards]
        eff_map = get_effective_business_assessments(pids, crm_db)
    except Exception as e:
        st.warning(f"Effective assessment load error: {e}")

    # ── Qualification layer sub-tabs ─────────────────────────────────────────
    n_candidate = sum(1 for c in cards if not c.get("is_confirmed"))
    n_confirmed = sum(1 for c in cards if c.get("is_confirmed"))
    qual_layer = st.pills(
        "Уровень квалификации:",
        options=["Предварительно ИИ", "✓ Подтверждено"],
        format_func=lambda x: (
            f"{x} · {n_candidate}" if x == "Предварительно ИИ"
            else f"{x} · {n_confirmed}"
        ),
        default="Предварительно ИИ",
        key="torgi_qual_layer",
        label_visibility="collapsed",
    )
    is_confirmed_layer = qual_layer == "✓ Подтверждено"
    cards_layer = [c for c in cards if bool(c.get("is_confirmed")) == is_confirmed_layer]

    # ── AI state filter ────────────────────────────────────────────────────
    ai_filter = st.selectbox(
        "Фильтр AI-состояния:", _TORGI_AI_FILTERS,
        key="torgi_ai_filter", label_visibility="collapsed"
    )

    def _matches_filter(card: dict) -> bool:
        eff = eff_map.get(card["id"])
        ai_s = eff.ai_status if eff else "UNASSESSED"
        scope = eff.business_relevance if eff else "UNKNOWN"
        if ai_filter == "Неоцененные":
            return ai_s == "UNASSESSED"
        if ai_filter == "Неполные оценки":
            return ai_s == "INCOMPLETE"
        if ai_filter == "Ошибки AI":
            return ai_s == "FAILED"
        if ai_filter == "IN_PROFILE":
            return ai_s == "ASSESSED" and scope == "IN_PROFILE"
        if ai_filter == "OUT_OF_PROFILE":
            return scope == "OUT_OF_PROFILE"
        return True  # "Все"

    filtered = [c for c in cards_layer if _matches_filter(c)]

    # ── Sort by effective assessment (explicit rank tuple) ──────────────────
    filtered = sorted(
        filtered,
        key=lambda c: _torgi_sort_key(c, eff_map),
        reverse=True,
    )

    selected_id = st.session_state.get(_SESSION_TORGI)
    caption = f"Активных торгов: {len(cards)}"
    if ai_filter != "Все":
        caption += f" · фильтр: {ai_filter} ({len(filtered)})"
    if selected_id:
        caption += f" · выбрана #{selected_id}"
    st.caption(caption)

    for idx, card in enumerate(filtered):
        pid = card["id"]
        render_compact_card(card, idx, session_key=_SESSION_TORGI, effective=eff_map.get(pid))

    # Details rendered inline inside render_compact_card



# ─── Комиссия-таб ─────────────────────────────────────────────────────────────

def _render_komissia_tab() -> None:
    col_hdr, col_sync = st.columns([3, 2])
    with col_sync:
        if st.button("↻ Обновить", key="komissia_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    cards = _load_komissia()

    if not cards:
        st.info("Нет тендеров на стадии работы комиссии.")
        return

    selected_id   = st.session_state.get(_SESSION_KOMISSIA)
    selected_card = next((c for c in cards if c["id"] == selected_id), None)

    waiting   = [c for c in cards if c["award_status"] == "submission_closed_waiting_award"]
    not_found = [c for c in cards if c["award_status"] == "award_not_found"]

    st.caption(
        f"Ждём решения: {len(waiting)} · результат не найден: {len(not_found)}"
        + (f" · выбрана #{selected_id}" if selected_id else "")
    )

    for idx, card in enumerate(waiting):
        render_compact_card(card, idx, session_key=_SESSION_KOMISSIA)

    if not_found:
        with st.expander(f"Результат не найден ({len(not_found)})"):
            for idx, card in enumerate(not_found, start=len(waiting)):
                render_compact_card(card, idx, session_key=_SESSION_KOMISSIA)

    # Details rendered inline inside render_compact_card


# ─── Разыгранные-таб ──────────────────────────────────────────────────────────

def _render_razygranye_tab() -> None:
    col_hdr, col_sync = st.columns([3, 2])
    with col_sync:
        if st.button("↻ Обновить данные", key="razygr_sync_btn"):
            st.cache_data.clear()
            st.rerun()

    cards = _load_razygranye()
    if not cards:
        st.info("Нет разыгранных закупок.")
        return

    selected_id   = st.session_state.get(_SESSION_RAZYGR)
    selected_card = next((c for c in cards if c["id"] == selected_id), None)

    # ── Qualification layer sub-tabs ─────────────────────────────────────────
    n_candidate = sum(1 for c in cards if not c.get("is_confirmed"))
    n_confirmed = sum(1 for c in cards if c.get("is_confirmed"))
    qual_layer = st.pills(
        "Уровень квалификации:",
        options=["Предварительно ИИ", "✓ Подтверждено"],
        format_func=lambda x: (
            f"{x} · {n_candidate}" if x == "Предварительно ИИ"
            else f"{x} · {n_confirmed}"
        ),
        default="Предварительно ИИ",
        key="razygr_qual_layer",
        label_visibility="collapsed",
    )
    is_confirmed_layer = qual_layer == "✓ Подтверждено"
    cards_layer = [c for c in cards if bool(c.get("is_confirmed")) == is_confirmed_layer]

    st.caption(
        f"Найдено: {len(cards)} записей"
        f" · {('✓ Подтверждено' if is_confirmed_layer else 'Предварительно ИИ')}: {len(cards_layer)}"
    )

    for idx, card in enumerate(cards_layer):
        render_compact_card(card, idx, session_key=_SESSION_RAZYGR)

    # Details rendered inline inside render_compact_card


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
