"""Пагинация списка карточек (сверху и снизу)."""
import math
from typing import Callable, List, Optional, TypeVar

import streamlit as st

T = TypeVar("T")


def paginate_items(items: List[T], page: int, page_size: int) -> tuple:
    """Вернуть (страница, всего страниц, срез элементов)."""
    total = len(items)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    return page, total_pages, items[start : start + page_size]


def render_pagination_bar(
    page: int,
    total_pages: int,
    page_items_count: int,
    total: int,
    tab_key: str,
    position: str,
) -> None:
    """Строка навигации «Назад / страница / Вперёд»."""
    page_key = f"cards_page_{tab_key}"
    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button(
            "← Назад",
            disabled=page <= 1,
            key=f"prev_{position}_{tab_key}",
        ):
            st.session_state[page_key] = page - 1
            st.rerun()
    with nav2:
        st.caption(
            f"Страница **{page}** из **{total_pages}** · "
            f"показано **{page_items_count}** из **{total}**"
        )
    with nav3:
        if st.button(
            "Вперёд →",
            disabled=page >= total_pages,
            key=f"next_{position}_{tab_key}",
        ):
            st.session_state[page_key] = page + 1
            st.rerun()


def render_card_grid_with_pagination(
    items: List[T],
    tab_key: str,
    page_size: int,
    render_item: Optional[Callable[[T], None]] = None,
    render_batch: Optional[Callable[[List[T], int], None]] = None,
    before_render: Optional[Callable[[List[T]], None]] = None,
) -> None:
    """Сетка карточек с пагинацией сверху и снизу."""
    page_key = f"cards_page_{tab_key}"
    page = st.session_state.get(page_key, 1)
    page, total_pages, page_items = paginate_items(items, page, page_size)
    st.session_state[page_key] = page

    if before_render:
        before_render(page_items)

    render_pagination_bar(page, total_pages, len(page_items), len(items), tab_key, "top")
    if render_batch:
        render_batch(page_items, page)
    elif render_item:
        for item in page_items:
            render_item(item)
    if total_pages > 1:
        render_pagination_bar(page, total_pages, len(page_items), len(items), tab_key, "bottom")
