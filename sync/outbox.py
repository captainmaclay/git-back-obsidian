"""
sync/outbox.py — файл-очередь отложенных изменений (outbox).

Хранит записи об изменениях (создание/удаление/переименование/изменение файлов и
папок), которые ещё НЕ отправлены на GitHub. Файл `pending_changes.json` чистится
ТОЛЬКО после успешного пуша (см. sync/push.py → outbox.clear()). Пока он непустой,
retry-очередь (sync/retry_queue.py) повторяет попытки пуша.

Что отслеживается:
- папки — всегда (кроме служебных из IGNORED_DIRS);
- файлы — только с расширениями из TRACKED_EXTENSIONS (параметризуемо через .env,
  по умолчанию .md/.json).

Записи дедуплицируются по пути: хранится последнее событие для каждого пути — это и
есть текущее «отложенное» состояние (события «создал-потом-удалил» не накапливаются).
"""

import json
import time
import threading
from pathlib import Path

from core.logger import log_soft, log_main
from core.config import PENDING_CHANGES_FILE, IGNORED_DIRS
import core.config as config  # для «живых» значений TRACK_FOLDERS / расширений

_lock = threading.Lock()


def _is_tracked(rel_path: str, is_dir: bool) -> bool:
    parts = Path(rel_path).parts
    if any(p in IGNORED_DIRS for p in parts):
        return False
    if is_dir:
        return config.TRACK_FOLDERS            # папки — по флагу из Settings/.env
    return rel_path.lower().endswith(tuple(config.get_tracked_extensions()))


def _read() -> list:
    try:
        data = json.loads(Path(PENDING_CHANGES_FILE).read_text(encoding="utf-8"))
        return data.get("events", [])
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _write(events: list) -> None:
    try:
        Path(PENDING_CHANGES_FILE).write_text(
            json.dumps({"events": events}, ensure_ascii=False, indent=0),
            encoding="utf-8",
        )
    except Exception as e:
        log_main(f"[OUTBOX] Не удалось записать {Path(PENDING_CHANGES_FILE).name}: {e}")


def record(event_type: str, path, is_dir: bool = False) -> None:
    """
    Регистрирует изменение, если оно отслеживается. Дедуп по пути (последнее событие).
    event_type: created | modified | deleted | moved (из watchdog).
    """
    rel = str(path)
    if not _is_tracked(rel, is_dir):
        return
    with _lock:
        events = [e for e in _read() if e.get("path") != rel]
        events.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": event_type,
            "path": rel,
            "is_dir": bool(is_dir),
        })
        _write(events)
        n = len(events)
    log_soft(f"[OUTBOX] +{event_type}: {rel} (в очереди: {n})")


def has_pending() -> bool:
    with _lock:
        return len(_read()) > 0


def count() -> int:
    with _lock:
        return len(_read())


def load() -> list:
    with _lock:
        return list(_read())


def clear() -> None:
    """Очищает очередь. Вызывать ТОЛЬКО после успешного пуша (или когда remote уже актуален)."""
    with _lock:
        had = len(_read())
        _write([])
    if had:
        log_soft(f"[OUTBOX] Очередь очищена ({had} записей) — изменения отправлены")
