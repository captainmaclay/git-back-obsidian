"""
gui_watcher.py

Git AutoSync Watcher

watchdog отслеживает изменения файлов
debounce защита
pygit2 push всегда основной
 если GitHub repo пустой (409) → bootstrap CLI push
CLI используется только один раз
никакого flag-файла
 initial_check_loop присутствует
"""

import time
import threading
from threading import Timer, Lock
from pathlib import Path
import traceback
import subprocess

import requests
import pygit2
from watchdog.events import FileSystemEventHandler

from app_logger import log_main, log_soft

from config import (
    DEBOUNCE_SECONDS,
    IGNORED_DIRS,
    GITHUB_USERNAME,
    GITHUB_REPO,
    GITHUB_TOKEN,
    REPO_PATH
)

from observer_manager import (
    start_observer,
    stop_observer,
    is_observer_running
)

# ─────────────────────────────────────────────
# Locks + state
# ─────────────────────────────────────────────

_repo_init_lock = Lock()
_push_lock = Lock()

_repo_initialized = False
_push_in_progress = False
_cli_bootstrap_done = False

debounce_timer: Timer | None = None
watcher_thread: threading.Thread | None = None
_watcher_running = False


# ─────────────────────────────────────────────
# GitHub API check: repo empty?
# ─────────────────────────────────────────────

def github_repo_is_empty() -> bool:
    """
    True если GitHub repo реально пустой (409).
    """

    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/commits",
            headers={"Authorization": f"token {GITHUB_TOKEN}"},
            timeout=5
        )

        if r.status_code == 409:
            log_main("[GitHub API] Repo EMPTY (409)")
            return True

        log_main("[GitHub API] Repo NOT empty")
        return False

    except Exception as e:
        log_main(f"[GitHub API ERROR] {e}")
        return True


# ─────────────────────────────────────────────
# CLI Bootstrap exactly как ты указал
# ─────────────────────────────────────────────

def bootstrap_force_push_cli():
    """
    Делает bootstrap push строго командами:

    echo "# repo" >> README.md
    git init
    git add README.md
    git commit -m "first commit"
    git branch -M main
    git remote add origin ...
    git push -u origin main --force

    Запускается ТОЛЬКО если GitHub реально пустой.
    """

    global _cli_bootstrap_done

    if _cli_bootstrap_done:
        return

    log_main("[BOOTSTRAP CLI] GitHub пустой → выполняем первый push через CLI")

    repo_dir = Path(REPO_PATH)
    readme = repo_dir / "README.md"

    try:
        # 1) README
        if not readme.exists():
            readme.write_text(f"# {GITHUB_REPO}\n", encoding="utf-8")

        remote_url = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}.git"

        commands = [
            ["git", "init"],
            ["git", "add", "README.md"],
            ["git", "commit", "-m", "first commit"],
            ["git", "branch", "-M", "main"],
            ["git", "remote", "remove", "origin"],
        ]

        # origin может не существовать → игнорируем ошибку
        subprocess.run(
            ["git", "remote", "remove", "origin"],
            cwd=REPO_PATH,
            capture_output=True,
            text=True
        )

        # добавляем origin заново
        subprocess.run(
            ["git", "remote", "add", "origin", remote_url],
            cwd=REPO_PATH,
            check=True,
            capture_output=True,
            text=True
        )

        # push
        subprocess.run(
            ["git", "push", "-u", "origin", "main", "--force"],
            cwd=REPO_PATH,
            check=True,
            capture_output=True,
            text=True
        )

        log_main("[BOOTSTRAP CLI] Первый push выполнен успешно ")
        _cli_bootstrap_done = True

    except subprocess.CalledProcessError as e:
        log_main("[BOOTSTRAP CLI ERROR] push провалился")
        log_main(e.stdout)
        log_main(e.stderr)

    except Exception as e:
        log_main(f"[BOOTSTRAP CLI ERROR] {e}")


# ─────────────────────────────────────────────
# Watchdog handler
# ─────────────────────────────────────────────

class ChangeHandler(FileSystemEventHandler):

    def _ignore(self, path: str) -> bool:
        return any(p in IGNORED_DIRS for p in Path(path).parts)

    def on_any_event(self, event):

        if event.is_directory:
            return

        if self._ignore(event.src_path):
            return

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

            from do_push import do_push
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
# INIT + bootstrap + pygit2 push
# ─────────────────────────────────────────────


def safe_ensure_repository_and_main_branch():
    """
    Гарантирует что main существует на GitHub.
    Если repo пустой → bootstrap CLI.
    Потом всегда pygit2.
    """
    global _repo_initialized

    with _repo_init_lock:

        if _repo_initialized:
            return

        repo_dir = Path(REPO_PATH)
        remote_url = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}.git"

        try:
            # ───────────── repo open/init
            if not (repo_dir / ".git").exists():
                repo = pygit2.init_repository(str(repo_dir))
                log_main("[INIT] Repo создан")
            else:
                repo = pygit2.Repository(str(repo_dir))
                log_main("[INIT] Repo открыт")

            # ───────────── если GitHub пустой → CLI bootstrap
            if github_repo_is_empty():
                bootstrap_force_push_cli()

            # ───────────── origin safe
            try:
                origin = repo.remotes["origin"]
            except KeyError:
                origin = repo.remotes.create("origin", remote_url)
                log_main("[INIT] origin создан")

            callbacks = pygit2.RemoteCallbacks(
                credentials=lambda url, user, allowed:
                    pygit2.UserPass(GITHUB_USERNAME, GITHUB_TOKEN)
            )

            # ───────────── pygit2 push main
            log_main("[INIT PUSH] pygit2 push → GitHub")

            origin.push(
                ["+refs/heads/main:refs/heads/main"],
                callbacks=callbacks
            )

            log_main("[INIT PUSH] main успешно синхронизирован ")

        except Exception as e:
            log_main(f"[INIT ERROR] {e}")
            traceback.print_exc()

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


def stop_watcher():
    global _watcher_running
    _watcher_running = False
    stop_observer()


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

    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/commits",
            headers={"Authorization": f"token {GITHUB_TOKEN}"},
            timeout=5
        )

        report.append(f"GitHub API: {r.status_code}")

    except Exception as e:
        report.append(f"GitHub API ERROR: {e}")

    log_soft("\n".join(report))


__all__ = [
    "start_watcher",
    "stop_watcher",
    "initial_check_loop",
    "ChangeHandler"
]


