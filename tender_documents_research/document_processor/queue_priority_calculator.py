"""
Priority calculator for document_processing_queue.

Computes queue_type, priority_class (P0–P4), and priority_score (0–100)
BEFORE documents are downloaded, based on deadline slack, price, category
confidence, and historical gold rate.

Medal (GOLD/SILVER/BRONZE/WOOD) is assigned AFTER documents are parsed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Priority class constants  (P0 = most urgent)
# ---------------------------------------------------------------------------
P0 = 0  # 85–100   download immediately
P1 = 1  # 70–84    after P0
P2 = 2  # 50–69    normal queue
P3 = 3  # 25–49    weak / small
P4 = 4  # 0–24     submission closed / archive

QUEUE_TYPE_HOT      = "commercial_hot"
QUEUE_TYPE_NORMAL   = "commercial_normal"
QUEUE_TYPE_AWARD    = "award_transition"
QUEUE_TYPE_HIST     = "historical"

MODEL_VERSION = "v1_formula"


# ---------------------------------------------------------------------------
# Input / output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PriorityInput:
    """All data available before downloading documents."""
    contract_number: str
    table_source: str

    # Tender metadata
    initial_price: Optional[int] = None          # НМЦК, ₽
    submission_end_at: Optional[object] = None   # datetime | None
    publication_date: Optional[object] = None    # datetime | None
    category_code: Optional[str] = None          # e.g. "computers_it"

    # Pre-computed deadline fields (may come from the registry row)
    remaining_workdays: Optional[int] = None     # рабочих дней до подачи
    required_workdays: int = 2                   # минимум нужно для подготовки

    # Qwen pre-analysis (optional; if absent → formula-only)
    category_confidence: Optional[float] = None  # 0–1
    commercial_scale_score: Optional[int] = None # 0–100  (from Qwen or formula)
    gold_probability: Optional[float] = None     # 0–1    (from Qwen or formula)

    # Historical stats for the category
    hist_gold_confirmation_rate: Optional[float] = None  # 0–1
    hist_median_price: Optional[int] = None
    hist_p75_price: Optional[int] = None

    # Legacy AI hint from crm_docs_priority_hints (0–100)
    legacy_ai_score: int = 0

    # Aging: hours this row has been pending
    aging_hours: int = 0


@dataclass
class PriorityResult:
    queue_type: str
    priority_class: int          # 0–4
    priority_score: int          # 0–100
    deadline_slack: Optional[int]
    predicted_gold_prob: float
    commercial_scale_score: int
    deadline_feasibility_score: int
    category_confidence: float
    reason_codes: list = field(default_factory=list)
    model_version: str = MODEL_VERSION

    @property
    def priority_class_label(self) -> str:
        return f"P{self.priority_class}"


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class QueuePriorityCalculator:
    """
    Computes priority without calling Qwen (formula-only mode).
    When Qwen results are available, pass them via PriorityInput fields
    (category_confidence, commercial_scale_score, gold_probability).
    """

    # Weights / caps
    MAX_SCORE = 100
    CATEGORY_MAX     = 20
    COMMERCIAL_MAX   = 20
    DEADLINE_MAX     = 25
    TITLE_MAX        = 0   # reserved; set via category_confidence surrogate
    HIST_GOLD_MAX    = 10
    REGION_MAX       = 5
    AGING_MAX        = 5

    # Penalty caps
    CLOSED_PENALTY   = 50
    NARROW_WINDOW_PENALTY = 25
    ONE_DAY_PENALTY  = 20

    def calculate(self, inp: PriorityInput) -> PriorityResult:
        reason_codes: list[str] = []
        is_awarded = "_awarded" in (inp.table_source or "")

        # ------------------------------------------------------------------
        # 1. Determine if submission is already closed
        # ------------------------------------------------------------------
        slack = self._deadline_slack(inp)
        submission_closed = (slack is not None and slack < -1) or is_awarded

        # ------------------------------------------------------------------
        # 2. Category confidence score  (0–20)
        # ------------------------------------------------------------------
        if inp.category_confidence is not None:
            cat_score = round(inp.category_confidence * self.CATEGORY_MAX)
        elif inp.category_code:
            cat_score = 14  # known category, no confidence given
            reason_codes.append("category_known")
        else:
            cat_score = 5
            reason_codes.append("category_unknown")

        # ------------------------------------------------------------------
        # 3. Commercial scale score  (0–20)
        # ------------------------------------------------------------------
        if inp.commercial_scale_score is not None:
            comm_score = min(self.COMMERCIAL_MAX, inp.commercial_scale_score * self.COMMERCIAL_MAX // 100)
        else:
            comm_score = self._formula_commercial_score(inp, reason_codes)

        # ------------------------------------------------------------------
        # 4. Deadline feasibility score  (0–25)
        # ------------------------------------------------------------------
        dl_score, dl_codes = self._deadline_score(slack, submission_closed)
        reason_codes.extend(dl_codes)

        # ------------------------------------------------------------------
        # 5. Historical gold score  (0–10)
        # ------------------------------------------------------------------
        hist_score = 0
        if inp.hist_gold_confirmation_rate is not None:
            hist_score = round(inp.hist_gold_confirmation_rate * self.HIST_GOLD_MAX)
            if inp.hist_gold_confirmation_rate >= 0.3:
                reason_codes.append("high_hist_gold_rate")

        # ------------------------------------------------------------------
        # 6. Aging bonus  (0–5, capped)
        # ------------------------------------------------------------------
        aging_bonus = min(self.AGING_MAX, inp.aging_hours // 24)

        # ------------------------------------------------------------------
        # 7. Penalties
        # ------------------------------------------------------------------
        penalties = 0
        if submission_closed:
            penalties += self.CLOSED_PENALTY
            reason_codes.append("submission_closed")
        elif slack == 0:
            penalties += self.NARROW_WINDOW_PENALTY
            reason_codes.append("deadline_zero_slack")
        elif slack is not None and slack == 1:
            penalties += self.ONE_DAY_PENALTY
            reason_codes.append("deadline_one_day")

        # ------------------------------------------------------------------
        # 8. Raw score
        # ------------------------------------------------------------------
        raw = (
            cat_score
            + comm_score
            + dl_score
            + hist_score
            + aging_bonus
            - penalties
        )
        score = max(0, min(self.MAX_SCORE, raw))

        # ------------------------------------------------------------------
        # 9. Gold probability estimate
        # ------------------------------------------------------------------
        if inp.gold_probability is not None:
            gold_prob = inp.gold_probability
        else:
            gold_prob = self._formula_gold_probability(
                cat_score, comm_score, dl_score, hist_score, submission_closed
            )

        # ------------------------------------------------------------------
        # 10. Priority class
        # ------------------------------------------------------------------
        if submission_closed or is_awarded:
            pclass = P4
            qtype  = QUEUE_TYPE_AWARD if is_awarded else QUEUE_TYPE_HIST
        elif score >= 85:
            pclass = P0
            qtype  = QUEUE_TYPE_HOT
            reason_codes.append("P0_hot")
        elif score >= 70:
            pclass = P1
            qtype  = QUEUE_TYPE_HOT
        elif score >= 50:
            pclass = P2
            qtype  = QUEUE_TYPE_NORMAL
        elif score >= 25:
            pclass = P3
            qtype  = QUEUE_TYPE_NORMAL
        else:
            pclass = P4
            qtype  = QUEUE_TYPE_HIST

        return PriorityResult(
            queue_type=qtype,
            priority_class=pclass,
            priority_score=score,
            deadline_slack=slack,
            predicted_gold_prob=round(gold_prob, 3),
            commercial_scale_score=comm_score * 5,   # back to 0–100 scale
            deadline_feasibility_score=dl_score,
            category_confidence=inp.category_confidence or 0.0,
            reason_codes=reason_codes,
            model_version=MODEL_VERSION,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deadline_slack(inp: PriorityInput) -> Optional[int]:
        if inp.remaining_workdays is None:
            return None
        return inp.remaining_workdays - inp.required_workdays

    def _deadline_score(
        self, slack: Optional[int], submission_closed: bool
    ) -> tuple[int, list[str]]:
        codes: list[str] = []
        if submission_closed or slack is None:
            return 0, ["deadline_no_data" if slack is None else "deadline_closed"]
        if slack >= 5:
            return 25, ["deadline_comfortable"]
        if slack >= 3:
            return 23, ["deadline_ok"]
        if slack >= 1:
            return 19, ["deadline_tight"]
        if slack == 0:
            return 12, ["deadline_minimum"]
        if slack == -1:
            return 3, ["deadline_missed_minus1"]
        return 0, ["deadline_missed"]

    def _formula_commercial_score(
        self, inp: PriorityInput, reason_codes: list[str]
    ) -> int:
        price = inp.initial_price or 0
        p75 = inp.hist_p75_price
        median = inp.hist_median_price

        if price <= 0:
            return 2

        # Relative to category benchmarks
        if p75 and price > p75:
            reason_codes.append("price_above_category_p75")
            return self.COMMERCIAL_MAX  # 20
        if p75 and price > p75 * 0.6:
            reason_codes.append("price_above_category_median")
            return 15
        if median and price > median:
            return 10

        # Absolute tiers (₽)
        if price >= 10_000_000:
            reason_codes.append("price_tier_10m")
            return 18
        if price >= 3_000_000:
            reason_codes.append("price_tier_3m")
            return 13
        if price >= 1_000_000:
            return 8
        if price >= 300_000:
            return 4
        return 1

    @staticmethod
    def _formula_gold_probability(
        cat_score: int,
        comm_score: int,
        dl_score: int,
        hist_score: int,
        submission_closed: bool,
    ) -> float:
        if submission_closed:
            return 0.0
        raw = (cat_score / 20) * (comm_score / 20) * (dl_score / 25)
        hist_boost = 1.0 + (hist_score / 10) * 0.3
        return min(0.99, raw * hist_boost)


# ---------------------------------------------------------------------------
# Convenience: enrich a queue row dict in-place
# ---------------------------------------------------------------------------

def enrich_queue_row(row: dict, inp: PriorityInput) -> dict:
    """
    Given a dict representing one document_processing_queue row and its
    PriorityInput, compute priority and merge results back into the dict.
    Returns the same dict for chaining.
    """
    calc = QueuePriorityCalculator()
    res = calc.calculate(inp)
    row.update(
        queue_type=res.queue_type,
        priority_class=res.priority_class,
        priority_score=res.priority_score,
        deadline_slack=res.deadline_slack,
        predicted_gold_prob=float(res.predicted_gold_prob),
        commercial_scale_score=res.commercial_scale_score,
        deadline_feasibility_score=res.deadline_feasibility_score,
        category_confidence=float(res.category_confidence),
        priority_reason_json={"codes": res.reason_codes},
        priority_model_version=res.model_version,
    )
    return row
