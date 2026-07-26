"""
core/env_sanitizer.py

Чистка .env: убирает пробелы в начале/конце имён переменных и их значений.
Нужна, потому что лишний пробел в конце (например, в GITHUB_TOKEN) ломает
авторизацию, а глазами такой пробел не виден.

Правила:
- строки-комментарии (# ...) и пустые строки не трогаются;
- KEY = " value "   →   KEY="value";
- обрамляющие кавычки сохраняются, пробелы внутри концов значения срезаются;
- пробелы ВНУТРИ значения (например, путь "C:/My Vault") сохраняются —
  срезаются только ведущие и хвостовые.
"""

from pathlib import Path


def sanitize_env_file(env_path) -> bool:
    """
    Приводит .env в порядок. Возвращает True, если файл был изменён.
    Безопасна: при любой ошибке чтения/записи просто возвращает False.
    """
    env_path = Path(env_path)
    if not env_path.exists():
        return False

    try:
        original = env_path.read_text(encoding="utf-8")
    except Exception:
        return False

    out_lines = []
    changed = False

    for line in original.splitlines():
        stripped = line.strip()

        # комментарии, пустые строки и строки без '=' оставляем как есть
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out_lines.append(line)
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()

        # снимаем обрамляющие кавычки, чистим пробелы внутри, возвращаем кавычки
        quote = ""
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            quote = value[0]
            value = value[1:-1]
        value = value.strip()

        new_line = f"{key}={quote}{value}{quote}"
        out_lines.append(new_line)
        if new_line != line:
            changed = True

    if changed:
        try:
            env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        except Exception:
            return False

    return changed
