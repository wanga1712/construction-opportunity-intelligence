"""Единый read-only источник статуса/позиции/ETA документационной очереди.

PROCUREMENT_CARD_CATEGORY_PIPELINE_V1: и таблица закупок, и карточка берут
позицию и оценку времени из одного алгоритма. Модуль ничего не пишет.

ETA считается из фактической средней длительности последних COMPLETED-задач и
позиции закупки среди claimable-строк. Если истории мало — ETA = None
(«время пока не определено»), ноль не подставляется.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional, Sequence


QUEUE_LABELS = {
    "PENDING": "в очереди",
    "PRE_RESEARCH_WAITING": "ожидает pre-research",
    "PROCESSING": "обрабатывается",
    "COMPLETED": "обработана",
    "NO_LINKS": "нет документов",
    "FAILED": "ошибка",
    "SKIPPED_NOISE": "пропущена (шум)",
    "SKIPPED_NOT_TARGET": "вне цели",
}


def _di_conn():
    import psycopg2

    from src.services.crm_db_runtime import require_crm_db_connect_kwargs

    kw = dict(require_crm_db_connect_kwargs())
    kw["dbname"] = os.getenv("S13_DOCUMENT_DB_NAME", "document_intelligence")
    kw["connect_timeout"] = 5
    return psycopg2.connect(**kw)


def load_queue_progress(
    procurement_ids: Sequence[int],
    *,
    conn: Any = None,
) -> Dict[str, Any]:
    """Снимок очереди для набора закупок (read-only, один коннект)."""
    ids = sorted({int(p) for p in procurement_ids if p})
    empty = {
        "latest": {}, "positions": {}, "live_depth": 0, "pending_total": None,
        "legacy_backlog": None, "avg_sec": None, "workers": 1,
        "doc_counts": {}, "find_counts": {},
    }
    if not ids:
        return empty
    own_conn = conn is None
    try:
        from src.services.queue_admission import (
            CLAIMABLE_QUEUE_SQL,
            claimable_params,
            claim_order_key,
        )

        db = conn or _di_conn()
        try:
            with db.cursor() as cur:
                cur.execute(
                    """SELECT DISTINCT ON (procurement_id) procurement_id, status, priority_score
                         FROM document_processing_queue
                        WHERE procurement_id = ANY(%s)
                        ORDER BY procurement_id, id DESC""",
                    (ids,),
                )
                latest = {int(pid): (st, pr) for pid, st, pr in cur.fetchall()}
                cur.execute(
                    f"SELECT COUNT(*) FROM document_processing_queue q WHERE {CLAIMABLE_QUEUE_SQL}",
                    claimable_params(),
                )
                live_depth = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """SELECT COUNT(*) FROM document_processing_queue
                        WHERE status IN ('PENDING','PRE_RESEARCH_WAITING')"""
                )
                pending_total = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    f"""SELECT q.procurement_id, q.queue_lane, q.work_tier,
                               q.priority_score, q.id
                          FROM document_processing_queue q
                         WHERE {CLAIMABLE_QUEUE_SQL}""",
                    claimable_params(),
                )
                claimable = sorted(
                    cur.fetchall(),
                    key=lambda r: claim_order_key(r[1], r[2], r[3], r[4]),
                )
                positions: Dict[int, int] = {}
                seen = set()
                for idx, r in enumerate(claimable, start=1):
                    pid = int(r[0])
                    if pid not in seen:
                        seen.add(pid)
                        positions[pid] = idx
                cur.execute(
                    """SELECT AVG(EXTRACT(EPOCH FROM (completed_at - started_at)))
                         FROM (SELECT completed_at, started_at
                                 FROM document_processing_queue
                                WHERE status='COMPLETED' AND completed_at IS NOT NULL
                                  AND started_at IS NOT NULL
                                  AND completed_at > started_at
                                ORDER BY completed_at DESC LIMIT 300) t"""
                )
                row_avg = cur.fetchone()
                avg_sec = float(row_avg[0]) if row_avg and row_avg[0] is not None else None
                cur.execute("SELECT COUNT(*) FROM document_processing_queue WHERE status='PROCESSING'")
                active = int((cur.fetchone() or [0])[0] or 0)
                doc_counts: Dict[int, int] = {}
                cur.execute(
                    """SELECT procurement_id, COUNT(*) FROM document_files
                        WHERE procurement_id = ANY(%s) GROUP BY procurement_id""",
                    (ids,),
                )
                for pid, n in cur.fetchall():
                    doc_counts[int(pid)] = int(n or 0)
                find_counts: Dict[int, int] = {}
                cur.execute(
                    """SELECT m.procurement_id, f.file_name, COUNT(*)
                         FROM document_match_details d
                         JOIN document_matches m ON m.id = d.match_id
                         JOIN document_files f ON f.id = m.file_id
                        WHERE m.procurement_id = ANY(%s)
                        GROUP BY m.procurement_id, f.file_name""",
                    (ids,),
                )
                # MATCH_TERM_HYGIENE_V1: матчи из требований/оценки/протоколов
                # не считаем находками (см. match_source_filter).
                from src.services.match_source_filter import (
                    NON_RESEARCHABLE,
                    classify_match_source,
                )

                for pid, file_name, n in cur.fetchall():
                    if classify_match_source(file_name) == NON_RESEARCHABLE:
                        continue
                    find_counts[int(pid)] = find_counts.get(int(pid), 0) + int(n or 0)
        finally:
            if own_conn:
                db.close()
    except Exception:
        return empty

    return {
        "latest": latest,
        "positions": positions,
        "doc_counts": doc_counts,
        "find_counts": find_counts,
        "live_depth": live_depth,
        "pending_total": pending_total,
        "legacy_backlog": max(0, pending_total - live_depth),
        "avg_sec": avg_sec,
        "workers": max(1, min(11, active or 1)),
    }


def queue_position(progress: Dict[str, Any], procurement_id: int) -> Optional[int]:
    return (progress.get("positions") or {}).get(int(procurement_id))


def queue_eta_seconds(progress: Dict[str, Any], procurement_id: int) -> Optional[float]:
    pos = queue_position(progress, procurement_id)
    avg = progress.get("avg_sec")
    if not pos or avg is None:
        return None
    return float(avg) * float(pos) / float(progress.get("workers") or 1)


def queue_status_label(status: Any) -> str:
    key = str(status or "").upper()
    return QUEUE_LABELS.get(key, str(status) if status else "нет в очереди")
