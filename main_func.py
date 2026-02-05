"""
Хранилище вспомогательных функций и классов для do_push и других модулей.
Все функции, которые нужны do_push.py, теперь здесь.
НЕ СОДЕРЖИТ ГЛОБАЛЬНОГО СОСТОЯНИЯ И НЕ ЗАПУСКАЕТ НИЧЕГО САМОСТОЯТЕЛЬНО.
"""

import time
import shutil
import tempfile
import traceback
from pathlib import Path
from threading import Timer

from app_logger import log_both, log_main, log_soft

import config
import pygit2
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


# ────────────────────────────────────────────────
# Импорты констант из config
# ────────────────────────────────────────────────
from config import (
    WATCHED_FOLDER,
    FAKE_PUSH_GIT,
    DELETED_TEMP,
    DEBOUNCE_SECONDS,
    IGNORED_DIRS,
    PUSH_COMMENTS_DIR
)


# ────────────────────────────────────────────────
# Функции безопасной очистки папок
# ────────────────────────────────────────────────

def safe_clean_folder_via_temp(folder_path: Path | str, max_retries: int = 3) -> bool:
    """
    Полностью безопасно очищает папку через временное перемещение.
    Принимает как Path, так и str.
    """
    folder_path = Path(folder_path).resolve()
    log_both(f"[SAFE_CLEAN] Запуск безопасной очистки папки: {folder_path}")

    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)
        log_both(f"[SAFE_CLEAN] Папка не существовала → создана пустая")
        return True

    for attempt in range(1, max_retries + 1):
        try:
            start_time = time.time()

            with tempfile.TemporaryDirectory() as tmp_base:
                tmp_dir = Path(tmp_base)
                temp_target = tmp_dir / folder_path.name
                log_both(f"[SAFE_CLEAN] Перемещаем {folder_path} → {temp_target}")
                shutil.move(str(folder_path), str(temp_target))

                log_both(f"[SAFE_CLEAN] Удаляем временную копию: {temp_target}")
                shutil.rmtree(temp_target, ignore_errors=True)

            folder_path.mkdir(parents=True, exist_ok=True)
            log_both(f"[SAFE_CLEAN] Папка успешно очищена за {time.time() - start_time:.2f} сек")
            return True

        except Exception as e:
            log_both(f"[SAFE_CLEAN] Попытка {attempt}/{max_retries} провалилась: {type(e).__name__}: {e}")
            if attempt < max_retries:
                time.sleep(1.5)
            else:
                log_both(f"[SAFE_CLEAN] Критическая ошибка после {max_retries} попыток")
                traceback.print_exc()
                return False


# ────────────────────────────────────────────────
# Вспомогательные функции для do_push
# ────────────────────────────────────────────────


def safe_reset_folder(folder_path: Path | str) -> bool:
    """Синоним для совместимости"""
    return safe_clean_folder_via_temp(folder_path)


def open_repo(repo_path: Path | str | None = None):
    """Открывает репозиторий по пути (по умолчанию FAKE_PUSH_GIT)"""
    if repo_path is None:
        repo_path = Path(config.FAKE_PUSH_GIT)
    elif isinstance(repo_path, str):
        repo_path = Path(repo_path)

    repo_path = repo_path.resolve()
    try:
        repo = pygit2.Repository(str(repo_path))
        workdir = Path(repo.workdir).resolve()
        if workdir != repo_path:
            log_both(f"WARNING: workdir {workdir} ≠ ожидаемый путь {repo_path}")
        log_both(f"Репозиторий успешно открыт: {workdir}")
        return repo
    except Exception as e:
        log_both(f"Ошибка открытия репозитория {repo_path}: {type(e).__name__}: {e}")
        return None


def ensure_fake_repo_initialized(repo_path: Path | str | None = None):
    """Инициализирует репозиторий (по умолчанию FAKE_PUSH_GIT)"""
    repo_path = repo_path or Path(config.FAKE_PUSH_GIT)
    repo_path = Path(repo_path).resolve()
    git_dir = repo_path / ".git"

    if git_dir.is_dir():
        log_both("Репозиторий уже существует")
    else:
        log_both(f"Инициализируем новый репозиторий в {repo_path}")
        pygit2.init_repository(str(repo_path), bare=False)

    repo = open_repo(repo_path)
    if not repo:
        return False

    repo_url = getattr(config, 'GITHUB_REPO_URL', None)
    if not repo_url:
        log_both("ERROR: GITHUB_REPO_URL отсутствует в config")
        return False

    if "origin" not in [r.name for r in repo.remotes]:
        repo.remotes.create("origin", repo_url)
        log_both(f"Добавлен remote origin → {repo_url}")

    if repo.head_is_unborn:
        index = repo.index
        tree = index.write_tree()
        author = pygit2.Signature("Autosync", "Autosync@localhost")
        repo.create_commit("refs/heads/main", author, author,
                           "Initial commit by Autosync script", tree, [])
        repo.set_head("refs/heads/main")
        log_both("Создан initial commit и установлен HEAD на main")

    log_both("Репозиторий готов (remote проверен)")
    return True


def clean_fake_git_temp_if_needed(repo):
    """Очищает индекс или полностью сбрасывает репозиторий при ошибке"""
    if not repo:
        log_both("clean_fake_git_temp_if_needed: repo is None")
        return False

    index = repo.index
    log_both("Принудительная очистка индекса (index.clear())...")

    try:
        index.clear()
        log_both("index.clear() выполнен")

        log_both("Начинаем index.add_all()...")
        start_time = time.time()
        index.add_all()
        log_both(f"index.add_all() завершён за {time.time() - start_time:.2f} сек")

        log_both("Запись индекса (index.write())...")
        start_time = time.time()
        index.write()
        log_both(f"index.write() завершён за {time.time() - start_time:.2f} сек")

        log_both("Индекс успешно перестроен")
        return True

    except pygit2.GitError as ge:
        log_both(f"GitError при очистке индекса: {ge}")
    except Exception as e:
        log_both(f"Ошибка при очистке индекса: {type(e).__name__}: {e}")
        traceback.print_exc()

    log_both("Очистка индекса не удалась → применяем полную очистку через temp")
    return safe_clean_folder_via_temp(Path(repo.workdir))


def sync_files_to_fake(target_dir: Path | None = None):
    target_dir = Path(target_dir).resolve() if target_dir else Path(config.FAKE_PUSH_GIT)  # Добавлен дефолт для безопасности
    log_both(f"[DEBUG-SYNC] Начало синхронизации → {target_dir}")

    copied = 0
    skipped = 0
    total = 0
    errors = 0  # Добавлено отслеживание ошибок

    try:
        for src in WATCHED_FOLDER.rglob("*"):
            total += 1
            if src.is_dir():
                skipped += 1
                continue
            if any(p in IGNORED_DIRS for p in src.parts):
                log_soft(f"[SKIP] Игнор по IGNORED_DIRS: {src}")
                skipped += 1
                continue
            rel = src.relative_to(WATCHED_FOLDER)
            dst = target_dir / rel
            if '.git' in rel.parts or 'deleted_temp' in rel.parts:
                log_soft(f"[SKIP] .git или deleted_temp: {rel}")
                skipped += 1
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                try:
                    shutil.copy2(src, dst)
                    copied += 1
                    log_both(f"[COPY] {rel}")
                except Exception as e:
                    log_main(f"[ERROR-COPY] {rel}: {e}")
                    errors += 1
            else:
                log_soft(f"[SKIP] Уже актуален: {rel}")
                skipped += 1

        log_both(f"[DEBUG-SYNC] ИТОГО: файлов просмотрено {total}, скопировано {copied}, пропущено {skipped}, ошибок {errors}")

        deleted_count = 0
        for dst in target_dir.rglob("*"):
            if dst.is_dir() or any(p in config.IGNORED_DIRS for p in dst.parts):
                continue
            rel = dst.relative_to(target_dir)
            if '.git' in rel.parts or 'deleted_temp' in rel.parts:
                continue
            src = config.WATCHED_FOLDER / rel
            if not src.exists():
                temp_dst = config.DELETED_TEMP / rel
                temp_dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(dst, temp_dst)
                    log_both(f"Перенесён в deleted_temp: {rel}")
                    deleted_count += 1
                except Exception as e:
                    log_both(f"ERROR: Ошибка переноса {rel}: {e}")
                    errors += 1

        log_both(f"Синхронизация завершена. Удалено файлов: {deleted_count}, ошибок {errors}")
        log_both(f"Удалённые файлы → {config.DELETED_TEMP}")
    except Exception as e:
        log_both(f"[CRITICAL-SYNC] Общая ошибка синхронизации: {e}")
        traceback.print_exc()


def stage_all_safe(repo):
    """Безопасное добавление всех изменений в индекс"""
    if not repo:
        log_both("ERROR: stage_all_safe: repo is None")
        return

    try:
        log_both("stage_all_safe: начинаем add_all...")
        start = time.time()
        repo.index.add_all()
        log_both(f"add_all завершён за {time.time() - start:.2f} сек")

        log_both("stage_all_safe: пишем индекс...")
        start = time.time()
        repo.index.write()
        log_both(f"index.write() завершён за {time.time() - start:.2f} сек")

        log_both("stage_all_safe: add_all + write успешно")
    except Exception as e:
        log_both(f"CRITICAL ERROR в stage_all_safe: {type(e).__name__}: {e}")
        traceback.print_exc()
        raise


def has_changes(repo):
    """Проверяет, есть ли изменения в репозитории"""
    if not repo:
        return False
    status = repo.status()
    changed_count = sum(1 for s in status.values() if s != pygit2.GIT_STATUS_CURRENT)
    has = changed_count > 0
    log_soft(f"has_changes → {has} (изменённых/неактуальных файлов: {changed_count})")
    return has


def commit(repo, message: str) -> str:
    """Создаёт коммит из текущего индекса"""
    if not repo:
        log_both("commit: repo is None → возвращаем FAKE_COMMIT")
        return "FAKE_COMMIT"
    try:
        index = repo.index
        tree = index.write_tree()
        author = repo.default_signature
        parents = [] if repo.head_is_unborn else [repo.head.target]
        cid = repo.create_commit("HEAD", author, author, message, tree, parents)
        log_both(f"Создан коммит: {cid}")
        return str(cid)
    except Exception as e:
        log_both(f"Ошибка при создании коммита: {e}")
        traceback.print_exc()
        return "ERROR_COMMIT"


def save_push_comment(commit_sha: str, body: str):
    """Сохраняет комментарий коммита в push_comments"""
    config.PUSH_COMMENTS_DIR.mkdir(exist_ok=True)
    path = config.PUSH_COMMENTS_DIR / f"{commit_sha}.txt"
    path.write_text(body + "\n", encoding="utf-8", errors="replace")
    log_both(f"[save_comment] Сохранён комментарий: {path}")


# ────────────────────────────────────────────────
# Debounce и обработчик событий (для watchdog)
# ────────────────────────────────────────────────

_debounce_timer: Timer | None = None


def schedule_push():
    """Планирует отложенный вызов do_push через debounce"""
    from do_push import do_push  # ленивый импорт

    global _debounce_timer
    if _debounce_timer is not None:
        _debounce_timer.cancel()

    _debounce_timer = Timer(config.DEBOUNCE_SECONDS, do_push)
    _debounce_timer.start()
    log_both(f"[debounce] Push запланирован через {config.DEBOUNCE_SECONDS} сек")


class ChangeHandler(FileSystemEventHandler):
    """Обработчик событий файловой системы"""
    def _ignore(self, path: str) -> bool:
        return any(p in config.IGNORED_DIRS for p in Path(path).parts)

    def on_any_event(self, event):
        if not self._ignore(event.src_path):
            log_both(f"[watchdog] Изменение: {event.src_path}")
            schedule_push()


# ────────────────────────────────────────────────
# Функции управления наблюдателем
# ────────────────────────────────────────────────

_observer: Observer | None = None
def start_observation():
    """Запуск наблюдения за файлами (watchdog)"""
    global _observer

    log_both(f"[OBSERVER] Запуск наблюдения за {WATCHED_FOLDER}")

    _observer = Observer()
    _observer.schedule(ChangeHandler(), str(WATCHED_FOLDER), recursive=True)
    _observer.start()

    log_both("[OBSERVER] Наблюдение запущено")

def shutdown_components():
    """Корректное завершение компонентов"""
    log_both("[SHUTDOWN] Завершение компонентов...")

    if _observer:
        log_both("[SHUTDOWN] Остановка observer...")
        _observer.stop()
        _observer.join(timeout=5.0)
        log_both("[SHUTDOWN] Observer остановлен")

    log_both("[SHUTDOWN] Компоненты остановлены")
