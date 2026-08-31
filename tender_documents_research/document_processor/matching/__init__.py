"""Подмодули сопоставления ключевых слов."""

def __getattr__(name: str):
    if name == "TableRowMatcher":
        from .table_row_matcher import TableRowMatcher
        return TableRowMatcher
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = ["TableRowMatcher"]

