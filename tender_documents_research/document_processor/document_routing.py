"""Document routing for project, construction and computer procurements."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_PROJECT_PATTERNS = (
    r"\u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440",
    r"\u043f\u0440\u043e\u0435\u043a\u0442\u043d",
    r"\u0440\u0430\u0431\u043e\u0447[\u0430-\u044f]* \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446",
    r"\u043f\u043e\u043b\u043e\u0436\u0438\u0442\u0435\u043b\u044c\u043d[\u0430-\u044f]* \u0437\u0430\u043a\u043b\u044e\u0447\u0435\u043d",
    r"\u0437\u0430\u0434\u0430\u043d\u0438[\u0435\u044f] \u043d\u0430 \u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d",
)
_CONSTRUCTION_PATTERNS = (
    r"\u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b",
    r"\u043a\u0430\u043f\u0438\u0442\u0430\u043b\u044c\u043d[\u0430-\u044f]* \u0440\u0435\u043c\u043e\u043d\u0442",
    r"\u043a\u0430\u043f\u0440\u0435\u043c\u043e\u043d\u0442",
    r"\u0440\u0435\u043a\u043e\u043d\u0441\u0442\u0440\u0443\u043a\u0446",
    r"\u0440\u0435\u043c\u043e\u043d\u0442",
    r"\u0441\u043d\u043e\u0441",
)
_COMPUTER_PATTERNS = (
    r"\u043d\u043e\u0443\u0442\u0431\u0443\u043a",
    r"\u043a\u043e\u043c\u043f\u044c\u044e\u0442\u0435\u0440",
    r"\u043c\u043e\u043d\u043e\u0431\u043b\u043e\u043a",
    r"\u0441\u0435\u0440\u0432\u0435\u0440",
    r"\u043c\u043e\u043d\u0438\u0442\u043e\u0440",
    r"\u043f\u0440\u0438\u043d\u0442\u0435\u0440",
    r"\u043c\u0444\u0443",
    r"ssd",
    r"\u043f\u0440\u043e\u0446\u0435\u0441\u0441\u043e\u0440",
)


@dataclass(frozen=True)
class RoutingContext:
    title: str = ""
    okpd_code: str = ""
    okpd_name: str = ""
    contour_code: str = "procurement"


@dataclass(frozen=True)
class RoutingDecision:
    mode: str
    reason: str


class DocumentRouter:
    def detect(self, context: RoutingContext) -> RoutingDecision:
        title = (context.title or "").lower()
        okpd_code = (context.okpd_code or "").strip()
        okpd_name = (context.okpd_name or "").lower()
        haystack = f"{title} {okpd_name}".strip()

        if context.contour_code == "computers" or okpd_code.startswith("26.20"):
            return RoutingDecision("computer_tz", "computer_contour")
        if self._has_any(haystack, _COMPUTER_PATTERNS):
            return RoutingDecision("computer_tz", "computer_title_signal")
        if okpd_code.startswith("71") or self._has_any(haystack, _PROJECT_PATTERNS):
            return RoutingDecision("project_tz", "project_signal")
        if okpd_code.startswith(("41", "42", "43")) or self._has_any(haystack, _CONSTRUCTION_PATTERNS):
            return RoutingDecision("construction_docs", "construction_signal")
        return RoutingDecision("generic_docs", "fallback")

    def prioritize_links(
        self,
        links: list[tuple[str, str | None]],
        context: RoutingContext,
        *,
        limit: int = 0,
    ) -> list[tuple[str, str | None]]:
        decision = self.detect(context)
        scored = [(self._score_name(decision.mode, file_name or url), (url, file_name)) for url, file_name in links]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        prioritized = [item for _, item in scored]

        if decision.mode in {"project_tz", "computer_tz"}:
            strong = [item for item in prioritized if self._score_name(decision.mode, item[1] or item[0]) >= 60]
            if strong:
                prioritized = strong + [item for item in prioritized if item not in strong]
        elif decision.mode == "construction_docs":
            dense = [item for item in prioritized if self._score_name(decision.mode, item[1] or item[0]) >= 45]
            if dense:
                prioritized = dense + [item for item in prioritized if item not in dense]
        return prioritized[:limit] if limit and limit > 0 else prioritized

    def _score_name(self, mode: str, raw_name: str) -> int:
        name = (raw_name or "").lower()
        if mode == "project_tz":
            return self._weighted_score(
                name,
                positives=(
                    (r"\u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a[\u0430-\u044f]* \u0437\u0430\u0434\u0430\u043d\u0438", 100),
                    (r"\b\u0442\u0437\b", 95),
                    (r"\u0437\u0430\u0434\u0430\u043d\u0438[\u0435\u044f] \u043d\u0430 \u043f\u0440\u043e\u0435\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u043d", 95),
                    (r"\u0438\u0441\u0445\u043e\u0434\u043d[\u0430-\u044f]* \u0434\u0430\u043d\u043d", 70),
                    (r"\u0441\u043f\u0435\u0446\u0438\u0444\u0438\u043a\u0430\u0446", 55),
                    (r"\u043f\u043e\u044f\u0441\u043d\u0438\u0442\u0435\u043b\u044c\u043d[\u0430-\u044f]* \u0437\u0430\u043f\u0438\u0441", 45),
                ),
                negatives=((r"\u0444\u043e\u0440\u043c\u0430 \u0437\u0430\u044f\u0432\u043a", -60), (r"\u0434\u043e\u0433\u043e\u0432\u043e\u0440", -25), (r"\u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b", -25)),
            )
        if mode == "computer_tz":
            return self._weighted_score(
                name,
                positives=(
                    (r"\u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a[\u0430-\u044f]* \u0437\u0430\u0434\u0430\u043d\u0438", 100),
                    (r"\b\u0442\u0437\b", 95),
                    (r"\u0441\u043f\u0435\u0446\u0438\u0444\u0438\u043a\u0430\u0446", 90),
                    (r"\u0445\u0430\u0440\u0430\u043a\u0442\u0435\u0440\u0438\u0441\u0442\u0438\u043a", 85),
                    (r"\u043a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446", 75),
                    (r"\u043e\u043f\u0438\u0441\u0430\u043d\u0438[\u0435\u044f] \u043e\u0431\u044a\u0435\u043a\u0442\u0430 \u0437\u0430\u043a\u0443\u043f\u043a\u0438", 70),
                ),
                negatives=((r"\u043f\u0440\u043e\u0435\u043a\u0442 \u0434\u043e\u0433\u043e\u0432\u043e\u0440", -50), (r"\u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b", -30), (r"\u0437\u0430\u044f\u0432\u043a", -25)),
            )
        if mode == "construction_docs":
            return self._weighted_score(
                name,
                positives=(
                    (r"\u0441\u0432\u043e\u0434\u043d[\u0430-\u044f]* \u0432\u0435\u0434\u043e\u043c", 100),
                    (r"\u0432\u0435\u0434\u043e\u043c\u043e\u0441\u0442[\u044c\u044f] \u043e\u0431\u044a\u0435\u043c", 95),
                    (r"\u043b\u043e\u043a\u0430\u043b\u044c\u043d[\u0430-\u044f]* \u0441\u043c\u0435\u0442", 92),
                    (r"\u0441\u043c\u0435\u0442", 88),
                    (r"\u0441\u043f\u0435\u0446\u0438\u0444\u0438\u043a\u0430\u0446", 80),
                    (r"\u0432\u0435\u0434\u043e\u043c\u043e\u0441\u0442[\u044c\u044f] \u043c\u0430\u0442\u0435\u0440\u0438\u0430\u043b", 75),
                    (r"\u0440\u0430\u0431\u043e\u0447[\u0430-\u044f]* \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446", 55),
                    (r"\u0447\u0435\u0440\u0442\u0435\u0436", 45),
                ),
                negatives=((r"\u0444\u043e\u0440\u043c\u0430 \u0437\u0430\u044f\u0432\u043a", -60), (r"\u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b", -30), (r"\u0434\u043e\u0433\u043e\u0432\u043e\u0440", -20)),
            )
        return self._weighted_score(
            name,
            positives=((r"\u0441\u043f\u0435\u0446\u0438\u0444\u0438\u043a\u0430\u0446", 45), (r"\u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a[\u0430-\u044f]* \u0437\u0430\u0434\u0430\u043d\u0438", 45), (r"\u0441\u043c\u0435\u0442", 40)),
            negatives=((r"\u0437\u0430\u044f\u0432\u043a", -30),),
        )

    @staticmethod
    def _has_any(text: str, patterns: Iterable[str]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _weighted_score(name: str, *, positives: tuple[tuple[str, int], ...], negatives: tuple[tuple[str, int], ...]) -> int:
        score = 0
        for pattern, weight in positives:
            if re.search(pattern, name, flags=re.IGNORECASE):
                score += weight
        for pattern, penalty in negatives:
            if re.search(pattern, name, flags=re.IGNORECASE):
                score += penalty
        return score
