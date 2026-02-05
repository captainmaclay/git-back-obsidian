# filters/__init__.py
"""
Фильтры и эвристики для очистки логов.
"""

from .push_comment_filter import should_skip_push_comment_line
from .deep_heuristics import looks_like_push_comment_line

__all__ = [
    "should_skip_push_comment_line",
    "looks_like_push_comment_line",
]

