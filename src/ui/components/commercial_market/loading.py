"""Reusable retro-science loading state for the commercial market workspace."""
from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Optional

import streamlit as st

LOADING_PHRASES = (
    "Собираем данные…",
    "Строим модель объекта…",
    "Создаём квантовый компьютер…",
    "Запускаем квантовый процессор…",
    "Ищем материалы во Вселенной смет…",
    "Эволюционируем коммерческую модель…",
    "Сверяем результат с законами физики…",
    "Пытаемся понять проектировщика…",
    "Запускаем промышленную революцию…",
)

LOADING_IMAGES = (
    "loading_data",
    "loading_model",
    "loading_quantum",
    "loading_processor",
    "loading_space",
    "loading_evolution",
)

LOADING_SCENE_BY_PHRASE = dict(zip(LOADING_PHRASES, (
    "loading_data",
    "loading_model",
    "loading_quantum",
    "loading_processor",
    "loading_space",
    "loading_evolution",
    "loading_processor",
    "loading_model",
    "loading_evolution",
)))

_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets" / "commercial_loader"


def load_loading_svg(name: str) -> str:
    if name not in LOADING_IMAGES:
        raise ValueError(f"unknown commercial loader image: {name}")
    return (_ASSET_ROOT / f"{name}.svg").read_text(encoding="utf-8")


class CommercialLoadingState(AbstractContextManager):
    """Display a styled loading state while a synchronous read-model call runs."""

    def __init__(
        self,
        label: Optional[str] = None,
        *,
        image: Optional[str] = None,
        slot: Optional[st.delta_generator.DeltaGenerator] = None,
    ) -> None:
        self.label = label
        self.image = image
        self.slot = slot
        self._placeholder = None

    def __enter__(self) -> "CommercialLoadingState":
        self._placeholder = self.slot.empty() if self.slot is not None else st.empty()
        self.render()
        return self

    def render(self) -> None:
        if self._placeholder is None:
            return
        phrase = self.label or LOADING_PHRASES[0]
        image_name = self.image or LOADING_SCENE_BY_PHRASE.get(phrase, LOADING_IMAGES[0])
        svg = load_loading_svg(image_name)
        self._placeholder.markdown(
            f"""
            <div class="crm-loader" role="status" aria-live="polite">
              <div class="crm-loader-visual">{svg}</div>
              <div class="crm-loader-copy">
                <span class="crm-loader-kicker">COMMERCIAL DOSSIER ENGINE</span>
                <strong>{phrase}</strong>
                <span class="crm-loader-line"><i></i><i></i><i></i></span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._placeholder is not None:
            self._placeholder.empty()
        return False


def render_loading_demo() -> None:
    for image, phrase in zip(LOADING_IMAGES, LOADING_PHRASES):
        with CommercialLoadingState(phrase, image=image):
            st.caption(phrase)
            break
