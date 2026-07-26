"""
sync/watcher.py

Git AutoSync Watcher:
- watchdog отслеживает изменения файлов в отслеживаемой папке;
- debounce гасит «шторм» правок;
- по debounce запускается do_push (sync/push.py), который через REST API
  собирает изменения и отправляет их на GitHub.

Инициализация пустого репозитория (первый коммит + ветка main) выполняется
целиком в sync/push.py (_github_api_first_commit) при первом пуше — поэтому
здесь больше нет CLI-bootstrap и pygit2 init-push (последний давал ошибку
'failed to set credentials').
"""

import time
import threading
from threading import Timer, Lock
from pathlib import Path
import traceback

import requests
from watchdog.events import FileSystemEventHandler

from core.logger import log_main, log_soft

from core.config import (
    DEBOUNCE_SECONDS,
    IGNORED_DIRS,
    GITHUB_USERNAME,
    GITHUB_REPO,
    GITHUB_TOKEN,
    is_github_configured,
    WATCHED_FOLDER,
)

from sync.observer import (
    start_observer,
    stop_observer,
    is_observer_running
)
from sync import outbox
import core.config as config  # для «живого» флага TRACK_FOLDERS


def _rel_to_vault(p: str) -> str:
    """Путь относительно отслеживаемой папки (для читаемых записей в outbox)."""
    try:
        return Path(p).resolve().relative_to(Path(WATCHED_FOLDER).resolve()).as_posix()
    except Exception:
        return Path(p).name

# ─────────────────────────────────────────────
# Locks + state
# ─────────────────────────────────────────────

_repo_init_lock = Lock()
_push_lock = Lock()

_repo_initialized = False
_push_in_progress = False

debounce_timer: Timer | None = None
watcher_thread: threading.Thread | None = None
_watcher_running = False


# ─────────────────────────────────────────────
# Watchdog handler
# ─────────────────────────────────────────────

class ChangeHandler(FileSystemEventHandler):

    def _ignore(self, path: str) -> bool:
        return any(p in IGNORED_DIRS for p in Path(path).parts)

    def on_any_event(self, event):

        if self._ignore(event.src_path):
            return

        is_dir = event.is_directory

        # Папки: реагируем на их события (создание/удаление/переименование) только
        # если включён флаг TRACK_FOLDERS (галочка в Settings → .env). По умолчанию вкл.
        if is_dir and not config.TRACK_FOLDERS:
            return

        # Регистрируем изменение в файл-очереди (файлы — по расширениям из
        # push_extensions.txt; папки — по флагу). Очередь чистится только после пуша.
        try:
            outbox.record(event.event_type, _rel_to_vault(event.src_path), is_dir=is_dir)
            dest = getattr(event, "dest_path", None)
            if dest:  # перемещение/переименование
                outbox.record("moved", _rel_to_vault(dest), is_dir=is_dir)
        except Exception as e:
            log_soft(f"[watchdog] Не удалось записать изменение в очередь: {e}")

        with _push_lock:
            if _push_in_progress:
                return

        log_soft(f"[watchdog] Изменение: {event.src_path}")
        schedule_push()


# ─────────────────────────────────────────────
# Debounce push
# ─────────────────────────────────────────────

def schedule_push():
    global debounce_timer

    def safe_do_push():
        global _push_in_progress

        try:
            with _push_lock:
                _push_in_progress = True

            stop_observer()

            from sync.push import do_push
            do_push()

        except Exception as e:
            log_main(f"[PUSH ERROR] {e}")
            traceback.print_exc()

        finally:
            with _push_lock:
                _push_in_progress = False

            start_observer()

    if debounce_timer:
        debounce_timer.cancel()

    debounce_timer = Timer(DEBOUNCE_SECONDS, safe_do_push)
    debounce_timer.start()


# ─────────────────────────────────────────────
# Watcher loop
# ─────────────────────────────────────────────

def watcher_loop():
    global _watcher_running

    while _watcher_running:
        time.sleep(60)

        if not is_observer_running():
            if not _push_in_progress:
                log_main("[watcher] Observer упал → restart")
                start_observer()


# ─────────────────────────────────────────────
# INIT (лёгкий — реальная инициализация репо идёт через REST при первом пуше)
# ─────────────────────────────────────────────

def safe_ensure_repository_and_main_branch():
    """
    Раньше здесь делались CLI-bootstrap пустого репозитория и pygit2 init-push.
    Теперь инициализация пустого репозитория (первый коммит + ветка main) полностью
    выполняется через REST API в sync/push.py (_github_api_first_commit) при первом
    же пуше, поэтому отдельный init-push не нужен (он и давал 'failed to set credentials').

    Функция сохранена для совместимости вызовов (start_watcher, GUI).
    """
    global _repo_initialized

    with _repo_init_lock:
        if _repo_initialized:
            return

        if not is_github_configured():
            log_main("[INIT] GitHub не настроен (нет username/repo/token) → "
                     "заполните поля во вкладке Settings.")
        else:
            log_soft("[INIT] Инициализация репозитория выполнится через REST при первом пуше")

        _repo_initialized = True


# ─────────────────────────────────────────────
# Start watcher
# ─────────────────────────────────────────────

def start_watcher():
    global watcher_thread, _watcher_running

    if _watcher_running:
        return

    log_main("[watcher] Запуск Git-Watcher")
    _watcher_running = True

    safe_ensure_repository_and_main_branch()

    watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
    watcher_thread.start()

    start_observer()

    # Отдельная retry-очередь: досылает отложенные изменения, если пуш не удался.
    try:
        from sync.retry_queue import start_retry_queue
        start_retry_queue()
    except Exception as e:
        log_main(f"[watcher] Не удалось запустить retry-очередь: {e}")


def stop_watcher():
    global _watcher_running
    _watcher_running = False
    stop_observer()
    try:
        from sync.retry_queue import stop_retry_queue
        stop_retry_queue()
    except Exception:
        pass


# ─────────────────────────────────────────────
# Initial check loop
# ─────────────────────────────────────────────

def initial_check_loop():
    """
    Через 25 секунд проверяет watcher/observer/GitHub.
    """

    log_main("[initial-check] Проверка через 25 сек...")
    time.sleep(25)

    report = []
    report.append("Начальная проверка:")

    report.append("Watcher: OK" if watcher_thread else "Watcher: FAIL")
    report.append("Observer: OK" if is_observer_running() else "Observer: FAIL")

    if is_github_configured():
        try:
            r = requests.get(
                f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/commits",
                headers={"Authorization": f"token {GITHUB_TOKEN}"},
                timeout=5
            )
            report.append(f"GitHub API: {r.status_code}")
        except Exception as e:
            report.append(f"GitHub API ERROR: {e}")
    else:
        report.append("GitHub API: не настроен (заполните Settings)")

    log_soft("\n".join(report))


__all__ = [
    "start_watcher",
    "stop_watcher",
    "initial_check_loop",
    "ChangeHandler"
]
