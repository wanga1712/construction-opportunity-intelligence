"""UI labelling + category stop-phrases + priority research requests.

Lightweight feedback loop driven from the procurement table / card:
- record_label: positive/negative label for a procurement x category;
- apply_negative_rule: create a negative phrase rule and immediately retire
  similar CURRENT opportunities of the same category (disappear from the UI);
- set_priority: mark a procurement as a priority research object.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

_STOP = frozenset((
    "выполнение", "работ", "работы", "по", "на", "в", "и", "для", "с", "от", "до",
    "the", "услуг", "оказание", "объекту", "объект", "закупка", "поставка", "ремонт",
    "капитальный", "текущий", "строительство", "г",
))


def normalize_title(title: Optional[str]) -> str:
    from src.services.commercial_routing_v3.text_normalization import normalize_text
    return normalize_text(title)


def signature_phrases(title: Optional[str], *, max_phrases: int = 3) -> List[str]:
    """Distinctive 2–3 word n-grams from a normalized title."""
    from src.services.commercial_routing_v3.text_normalization import signature_phrases as _sig
    return _sig(title, max_phrases=max_phrases)


def record_label(crm_db: Any, *, procurement_id: int, category_code: Optional[str],
                 polarity: str, created_by: str = "operator", comment: Optional[str] = None) -> None:
    crm_db.execute_update(
        """INSERT INTO crm_ui_feedback
               (procurement_id, category_code, polarity, label_source, comment, created_by)
           VALUES (%s, %s, %s, 'UI_LABEL', %s, %s)""",
        (int(procurement_id), category_code, polarity, comment, created_by),
    )


def retire_similar(crm_db: Any, *, category_code: str, phrases: Sequence[str]) -> int:
    """Retire CURRENT opportunities of a category whose title matches a phrase."""
    if not phrases:
        return 0
    like = " OR ".join(["lower(p.auction_name) LIKE %s"] * len(phrases))
    params: List[Any] = [int(0)] + [f"%{p}%" for p in phrases]
    rows = crm_db.execute_query(
        f"""SELECT o.id FROM crm_procurement_category_opportunities o
              JOIN crm_procurements p ON p.id = o.procurement_id
             WHERE o.status = 'CURRENT' AND o.commercial_category_code = %s
               AND ({like})""",
        tuple([category_code] + [f"%{p}%" for p in phrases]),
    ) or []
    ids = [int(r["id"]) for r in rows]
    retired = 0
    for i in range(0, len(ids), 500):
        retired += int(crm_db.execute_update(
            "UPDATE crm_procurement_category_opportunities SET status='SUPERSEDED', updated_at=now()"
            " WHERE id = ANY(%s) AND status='CURRENT'", (ids[i:i + 500],)) or 0)
    return retired


def apply_negative_rule(crm_db: Any, *, procurement_id: int, category_code: str,
                        title: Optional[str], okpd: Optional[str] = None,
                        created_by: str = "operator") -> Dict[str, Any]:
    """Record the label, create phrase rules and retire similar rows immediately."""
    record_label(crm_db, procurement_id=procurement_id, category_code=category_code,
                 polarity="NEGATIVE", created_by=created_by)
    phrases = signature_phrases(title)
    for phrase in phrases:
        crm_db.execute_update(
            """INSERT INTO crm_category_stop_phrases (category_code, phrase, okpd, source, created_by)
               VALUES (%s, %s, %s, 'UI_LABEL', %s)
               ON CONFLICT (category_code, phrase, polarity) DO NOTHING""",
            (category_code, phrase, okpd, created_by),
        )
    retired = retire_similar(crm_db, category_code=category_code, phrases=phrases)
    return {"phrases": phrases, "retired": retired}


def apply_positive_rule(crm_db: Any, *, procurement_id: int, category_code: str,
                        title: Optional[str], okpd: Optional[str] = None,
                        created_by: str = "operator") -> Dict[str, Any]:
    """'Больше таких в этой категории': positive label + positive phrase rules."""
    record_label(crm_db, procurement_id=procurement_id, category_code=category_code,
                 polarity="POSITIVE", created_by=created_by)
    phrases = signature_phrases(title)
    for phrase in phrases:
        crm_db.execute_update(
            """INSERT INTO crm_category_stop_phrases (category_code, phrase, okpd, polarity, source, created_by)
               VALUES (%s, %s, %s, 'POSITIVE', 'UI_LABEL', %s)
               ON CONFLICT (category_code, phrase, polarity) DO NOTHING""",
            (category_code, phrase, okpd, created_by),
        )
    return {"phrases": phrases}


def set_priority(crm_db: Any, *, procurement_id: int, target_categories: Sequence[str],
                 priority: int = 100, requested_by: str = "operator") -> None:
    import json
    crm_db.execute_update(
        """INSERT INTO crm_research_requests (procurement_id, target_categories, priority, status, requested_by)
           VALUES (%s, %s::jsonb, %s, 'NEW', %s)
           ON CONFLICT (procurement_id) DO UPDATE
             SET target_categories = EXCLUDED.target_categories,
                 priority = EXCLUDED.priority,
                 status = 'NEW',
                 updated_at = now()""",
        (int(procurement_id), json.dumps(list(target_categories)), int(priority), requested_by),
    )
