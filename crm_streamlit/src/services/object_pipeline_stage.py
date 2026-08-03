"""Стадии закупочного контура для строительных объектов."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from src.services.object_lifecycle import is_awarded, is_awarded_registry, is_stale_open_tender, tender_days_left
from src.services.object_models import ObjectViewItem


PIPELINE_STAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("news_signal", "0) Новостной сигнал"),
    ("project_design_ai", "1) Проект найден + AI категоризация"),
    ("positive_expertise", "2) Положительное заключение"),
    ("prep_construction", "3) Ожидание стройки"),
    ("construction_active", "4) Торги на строительство / ремонт"),
    ("works_awarded", "5) Работы разыграны"),
)

_STAGE_LABELS = dict(PIPELINE_STAGE_OPTIONS)


@dataclass(frozen=True)
class PipelineStageDetector:
    """Небольшой OOP-контракт для детекции стадий."""

    news_tokens: Sequence[str] = (
        "новост",
        "сми",
        "сообщил",
        "сообщила",
        "планируется",
        "анонс",
        "объявил",
        "объявила",
    )
    design_tokens: Sequence[str] = (
        "проектир",
        "проектная документац",
        "пд",
        "71.12",
        "изыскан",
    )
    expertise_tokens: Sequence[str] = (
        "положит",
        "заключ",
        "экспертиз",
    )
    construction_tokens: Sequence[str] = (
        "строительств",
        "капитальн",
        "реконструкц",
        "ремонт",
        "благоустро",
        "43.",
        "42.",
        "41.",
    )

    def detect(self, item: ObjectViewItem) -> tuple[str, str]:
        """Определить стадию по фактам и текстовым сигналам."""
        linked_domrf = bool(item.domrf_object_id) or ("nashdom" in (item.sources or []))
        has_expertise = self._has_positive_expertise(item)
        is_design = self._is_design_project(item)
        in_construction = self._is_construction_phase(item)

        if is_awarded(item) or is_awarded_registry(item.registry_type):
            code = "works_awarded"
        elif self._is_active_tender(item) and (in_construction or has_expertise or linked_domrf):
            code = "construction_active"
        elif has_expertise and (linked_domrf or in_construction):
            code = "prep_construction"
        elif has_expertise:
            code = "positive_expertise"
        elif is_design:
            code = "project_design_ai"
        elif self._is_news_signal(item):
            code = "news_signal"
        else:
            code = "news_signal"
        return code, _STAGE_LABELS.get(code, _STAGE_LABELS["news_signal"])

    def _has_positive_expertise(self, item: ObjectViewItem) -> bool:
        if (item.expertise_number or "").strip():
            return True
        text = self._item_text(item)
        return all(token in text for token in self.expertise_tokens)

    def _is_design_project(self, item: ObjectViewItem) -> bool:
        text = self._item_text(item, fields=("name", "search_text", "status", "ai_project_stage", "ai_work_type"))
        return any(token in text for token in self.design_tokens)

    def _is_construction_phase(self, item: ObjectViewItem) -> bool:
        text = self._item_text(item, fields=("name", "search_text", "status", "ai_work_type", "ai_project_stage"))
        return any(token in text for token in self.construction_tokens)

    def _is_news_signal(self, item: ObjectViewItem) -> bool:
        text = self._item_text(item, fields=("name", "search_text", "status", "ai_project_stage", "ai_work_type"))
        if not text:
            return False
        if item.tender_id or item.expertise_number or is_awarded(item):
            return False
        return any(token in text for token in self.news_tokens)

    @staticmethod
    def _is_active_tender(item: ObjectViewItem) -> bool:
        """Открытый тендер остаётся активным, пока не стал просроченным."""
        if is_awarded(item) or is_awarded_registry(item.registry_type):
            return False
        if is_stale_open_tender(item):
            return False
        left = tender_days_left(item)
        return left is None or left >= 0

    @staticmethod
    def _item_text(item: ObjectViewItem, *, fields: Sequence[str] | None = None) -> str:
        parts = []
        names = fields or ("name", "search_text", "status", "ai_project_stage", "ai_work_type")
        for field_name in names:
            value = getattr(item, field_name, "")
            if value:
                parts.append(str(value))
        return " ".join(parts).lower()


_STAGE_DETECTOR = PipelineStageDetector()


def detect_pipeline_stage(item: ObjectViewItem) -> tuple[str, str]:
    return _STAGE_DETECTOR.detect(item)


def apply_pipeline_stages(items: Iterable[ObjectViewItem]) -> None:
    for item in items:
        code, label = detect_pipeline_stage(item)
        item.pipeline_stage_code = code
        item.pipeline_stage_label = label
