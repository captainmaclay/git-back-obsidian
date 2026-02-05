import re
from filters.deep_heuristics import looks_like_push_comment_line


def should_skip_push_comment_line(s: str) -> bool:
    s = s.strip()

    if len(s) < 70 or not s.startswith('['):
        return False

    close = s.find(']')
    if close == -1 or close > 30:
        return False

    if "push_comments/" not in s.lower():
        return False

    time_part = s[1:close].strip()

    # быстрые базовые проверки прошли →
    return looks_like_push_comment_line(s, time_part)


