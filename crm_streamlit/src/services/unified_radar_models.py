"""Модели Unified Radar.

Этот модуль хранит только структуры данных для карточек и сигналов.
Нужен как общий контракт между сервисом данных и UI страницы радара.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


@dataclass
class UnifiedSignalFlags:
    """Флаги найденной информации по объекту.

    Каждый флаг отвечает за конкретный контур:
    - nashdom: есть карточка объекта из NashDom;
    - positive_expertise: есть положительное заключение;
    - procurement_plan: есть запись из плана закупок;
    - tender_found: есть найденная закупка в реестрах.
    """

    nashdom: bool = False
    positive_expertise: bool = False
    procurement_plan: bool = False
    news_signal: bool = False
    projector_found: bool = False
    customer_found: bool = False
    tender_found: bool = False


@dataclass
class UnifiedRadarCard:
    """Сводная карточка объекта из нескольких контуров."""

    object_uid: str
    object_name: str
    region_name: str = ""
    address: str = ""
    expertise_number: str = ""
    expertise_date: Optional[date] = None
    planner_name: str = ""
    customer_name: str = ""
    domrf_object_id: str = ""
    tender_match_count: int = 0
    ai_priority_score: int = 0
    ai_priority_reason: str = ""
    status: str = "idea"
    signal_flags: UnifiedSignalFlags = field(default_factory=UnifiedSignalFlags)
    sources: list[str] = field(default_factory=list)

    @property
    def predicted_tender_date(self) -> Optional[date]:
        """Прогноз выхода закупки: +240 дней от положительного заключения."""
        if not self.expertise_date:
            return None
        return self.expertise_date + timedelta(days=240)

    @property
    def days_to_predicted_tender(self) -> Optional[int]:
        """Сколько дней до прогнозной даты торгов."""
        pred = self.predicted_tender_date
        if not pred:
            return None
        return (pred - date.today()).days

    def recompute_status(self) -> None:
        """Авто-статус карточки.

        Важное правило:
        - при найденной закупке объект автоматически становится golden_lead.
        """
        if self.signal_flags.tender_found or self.tender_match_count > 0:
            self.status = "golden_lead"
            return
        days = self.days_to_predicted_tender
        if self.signal_flags.positive_expertise and days is not None and days <= 30:
            self.status = "predicted_tender_window"
            return
        if self.signal_flags.positive_expertise or self.signal_flags.procurement_plan:
            self.status = "watch"
            return
        self.status = "idea"

