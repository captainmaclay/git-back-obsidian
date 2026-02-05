import re
import math
import difflib
import fnmatch
import hashlib
import ast
import json
import base64
import zlib
from datetime import datetime, date
from collections import Counter


HEX_40_RE = re.compile(r'/([a-f0-9]{40})\.txt', re.IGNORECASE)
PUSH_COMMENTS_RE = re.compile(r'../push_comments/', re.IGNORECASE)
TEMPLATE = '[YYYY-MM-DD HH:MM:SS] "push_comments/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.txt",'


def looks_like_push_comment_line(s: str, time_part: str | None = None) -> bool:
    """
    Тяжёлые эвристики.
    Сюда попадают ТОЛЬКО строки, которые уже прошли базовые проверки.
    """

    # 1. Классика: путь + 40 hex
    if HEX_40_RE.search(s):
        return True

    # 2. Длинные hex-последовательности
    hex_chunks = re.findall(r'[0-9a-f]{20,}', s, re.IGNORECASE)
    if any(len(chunk) >= 30 for chunk in hex_chunks):
        return True

    # 3. Энтропия 40-hex
    m = re.search(r'([a-f0-9]{40})', s, re.IGNORECASE)
    if m:
        chars = m.group(1).lower()
        freq = Counter(chars)
        entropy = -sum((c / 40) * math.log2(c / 40) for c in freq.values())
        if entropy > 3.5:
            return True

    # 4. Сходство с шаблоном
    if difflib.SequenceMatcher(None, s.lower(), TEMPLATE.lower()).ratio() > 0.7:
        return True

    # 5. shlex-парсинг
    try:
        import shlex
        parsed = shlex.split(s[s.find(']') + 1 :].strip())
        if (
            len(parsed) == 1
            and parsed[0].startswith('push_comments/')
            and parsed[0].endswith('.txt')
        ):
            return True
    except ValueError:
        pass

    # 6. fnmatch
    path = s[s.find('"') + 1 : s.rfind('"')]
    if fnmatch.fnmatch(path, 'push_comments/*.txt'):
        name = path.split('/')[-1]
        if len(name) in (44, 45):  # 40 hex + ".txt"
            return True

    # 7. ast.literal_eval
    try:
        eval_part = ast.literal_eval(path)
        if (
            isinstance(eval_part, str)
            and eval_part.startswith('push_comments/')
            and eval_part.endswith('.txt')
        ):
            return True
    except Exception:
        pass

    # 8. base16 / base64 попытка
    try:
        base64.b16decode(path.split('/')[-1].split('.')[0].upper())
        return True
    except Exception:
        pass

    # 9. levenshtein distance
    def levenshtein(a, b):
        if len(a) < len(b):
            return levenshtein(b, a)
        if not b:
            return len(a)
        prev = range(len(b) + 1)
        for i, c1 in enumerate(a):
            curr = [i + 1]
            for j, c2 in enumerate(b):
                curr.append(
                    min(
                        prev[j + 1] + 1,
                        curr[j] + 1,
                        prev[j] + (c1 != c2),
                    )
                )
            prev = curr
        return prev[-1]

    if levenshtein(s.lower(), TEMPLATE.lower()) < 20:
        return True

    # 10. JSON-подобность
    try:
        json_like = '{' + s.replace('[', '"time":"').replace('] "', '","file":') + '}'
        json.loads(json_like)
        return True
    except Exception:
        pass

    # 11. zlib compressibility (entropy косвенно)
    try:
        if len(zlib.compress(s.encode())) < len(s) / 2:
            return True
    except Exception:
        pass

    # 12. Контроль даты
    if time_part:
        try:
            ts = datetime.strptime(time_part, '%Y-%m-%d %H:%M:%S')
            if ts.year > date.today().year + 1:
                return True
        except ValueError:
            pass

    return False
