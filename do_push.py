"""
Отдельный модуль с главной функцией do_push() — полностью на GitHub REST API + pygit2.
Автоматическая инициализация репозитория, если .git отсутствует.
Обработка deleted_files только для текущего пуша.
"""

import shutil
import sys
import traceback
import datetime
import time
import base64
import requests
from pathlib import Path
import threading
import os
import tempfile
import glob
import pygit2

from typing import Optional, List, Tuple, Callable

from observer_manager import start_observer, stop_observer, is_observer_running, restart_observer

from copy_item import sync_changed_files

from app_logger import log_main, log_both, log_soft, init_logger

from config import (
    GITHUB_USERNAME,
    GITHUB_TOKEN,
    GITHUB_REPO,
    WATCHED_FOLDER,
    push_lock,
    parser_logger,
    run_logger_clean,
    VERSIONS_DIR,
    FAKE_PUSH_GIT,
    SCRIPT_DIR,
)

# Импорт из make_description.py
from make_description import CommitAnalyzer, GitHubCommenter


# Получаем директорию скрипта
script_dir = Path(__file__).parent.absolute()

# Папка репозитория
if not FAKE_PUSH_GIT.is_absolute():
    FAKE_PUSH_GIT = script_dir / FAKE_PUSH_GIT

# Константы
SUPPORTED_EXTENSIONS = (".md", ".json")
MAX_BLOCK_LENGTH = 1300

VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


def clear_python_cache():
    """Безопасная очистка Python-кэша в проекте (__pycache__ и *.pyc)"""
    log_both("[CACHE-CLEAN] Запуск очистки Python-кэша...")

    try:
        for cache_dir in glob.glob(str(SCRIPT_DIR / "**" / "__pycache__"), recursive=True):
            if os.path.isdir(cache_dir):
                shutil.rmtree(cache_dir, ignore_errors=True)
                log_both(f"[CACHE-CLEAN] Удалена папка: {cache_dir}")

        for pyc_file in glob.glob(str(SCRIPT_DIR / "**" / "*.pyc"), recursive=True):
            if os.path.isfile(pyc_file):
                os.remove(pyc_file)
                log_both(f"[CACHE-CLEAN] Удалён файл: {pyc_file}")

        log_both("[CACHE-CLEAN] Очистка кэша завершена успешно")
    except Exception as e:
        log_main(f"[CACHE-CLEAN-ERROR] Не удалось очистить кэш: {e}")


def is_malformed_path(rel_path: str) -> bool:
    forbidden_parts = {'.git', '.obsidian', '__MACOSX'}
    if rel_path.startswith('/'): return True
    if rel_path.endswith('/'): return True
    if '//' in rel_path: return True
    if '..' in rel_path.split('/'): return True
    if any(c in rel_path for c in '\x00-\x1f\x7f<>:"\\|?*'): return True
    if any(part in forbidden_parts for part in rel_path.split('/')): return True
    return False


def normalize_path(rel_path: str) -> str:
    rel_path = rel_path.lstrip('./').lstrip('/')
    rel_path = rel_path.rstrip('/')
    while '//' in rel_path:
        rel_path = rel_path.replace('//', '/')
    parts = []
    for part in rel_path.split('/'):
        if part == '..':
            if parts:
                parts.pop()
        elif part not in ('', '.'):
            parts.append(part)
    return '/'.join(parts)


def debug_directory_contents(dir_path: Path, label: str):
    log_both(f"[DEBUG] {label} ({dir_path}):")
    if not dir_path.exists():
        log_both("[DEBUG] Директория не существует")
        return
    count = 0
    file_list = []
    for root, dirs, files in os.walk(dir_path):
        root_rel = Path(root).relative_to(dir_path)
        log_soft(f"[DEBUG] Папка: {root_rel}")
        for d in dirs[:5]:
            log_soft(f"[DEBUG]   Подпапка: {d}")
        for f in files:
            log_soft(f"[DEBUG]   Файл: {f}")
            file_list.append(f)
            count += 1
            if count > 150:
                log_soft("[DEBUG] ... обрезано (слишком много файлов)")
                return
    log_both(f"[DEBUG] Количество файлов: {len(file_list)}")
    log_both(f"[DEBUG] Имена файлов: {file_list}")


def clear_temp_repo_content(temp_repo_path: Path):
    log_both("[TEMP-CLEAN] Полная очистка содержимого fake_git_temp (кроме .git)")

    git_dir = temp_repo_path / ".git"
    keep = {git_dir} if git_dir.exists() else set()

    debug_directory_contents(temp_repo_path, "Перед очисткой fake_git_temp")

    for item in list(temp_repo_path.iterdir()):
        if item in keep:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=False)
            else:
                item.unlink(missing_ok=False)
            log_soft(f"[TEMP-CLEAN] Удалено: {item.name}")
        except Exception as e:
            log_main(f"[TEMP-CLEAN-ERROR] Не удалось удалить {item}: {e}")
            try:
                fallback_dir = Path(tempfile.gettempdir()) / f"clean_fallback_{int(time.time())}"
                fallback_dir.mkdir(exist_ok=True)
                shutil.move(str(item), str(fallback_dir))
                log_both(f"[TEMP-CLEAN-FALLBACK] Перемещено {item} в {fallback_dir}")
                shutil.rmtree(fallback_dir, ignore_errors=True)
            except Exception as fb_e:
                log_main(f"[TEMP-CLEAN-FALLBACK-ERROR] Не удалось fallback: {fb_e}")


# ───────────────────────────────────────────────────────────────
# Закомментированы функции эвакуации и восстановления .git из корня проекта
# ───────────────────────────────────────────────────────────────
"""
def temporarily_evacuate_root_git() -> Optional[Path]:
    root_git = SCRIPT_DIR / ".git"
    if not root_git.exists() or not root_git.is_dir():
        log_both("[ROOT-GIT] Папка .git в корне проекта не найдена → ничего не перемещаем")
        return None

    log_both("[ROOT-GIT-EVACUATE] Обнаружена .git в корне проекта — временно перемещаем")

    temp_git_dir = Path(tempfile.mkdtemp(prefix="root_git_backup_", dir=tempfile.gettempdir()))
    backup_path = temp_git_dir / ".git"

    try:
        shutil.move(str(root_git), str(backup_path))
        log_both(f"[ROOT-GIT-EVACUATE] .git успешно перемещена в: {backup_path}")
        return backup_path
    except Exception as e:
        log_main(f"[ROOT-GIT-EVACUATE-ERROR] Не удалось переместить .git → {e}")
        try:
            shutil.rmtree(temp_git_dir, ignore_errors=True)
        except:
            pass
        return None


def restore_root_git(backup_path: Optional[Path]):
    if not backup_path or not backup_path.exists():
        return

    root_git_target = SCRIPT_DIR / ".git"

    log_both(f"[ROOT-GIT-RESTORE] Возвращаем .git обратно в {SCRIPT_DIR}")

    try:
        if root_git_target.exists():
            log_main("[ROOT-GIT-RESTORE-WARN] .git уже существует в корне — удаляем старую")
            shutil.rmtree(root_git_target, ignore_errors=True)

        shutil.move(str(backup_path), str(root_git_target))
        log_both("[ROOT-GIT-RESTORE] .git успешно восстановлена")

        try:
            shutil.rmtree(backup_path.parent, ignore_errors=True)
        except:
            pass

    except Exception as e:
        log_main(f"[ROOT-GIT-RESTORE-ERROR] Не удалось восстановить .git: {e}")
"""


class PushRecoveryHandler:
    def __init__(
        self,
        temp_repo_path: Path,
        backup_dir: Path,
        recovery_delay: int = 25,
        max_retries: int = 3
    ):
        self.temp_repo_path = temp_repo_path
        self.backup_dir = backup_dir / "recovery_backups"
        self.recovery_delay = recovery_delay
        self.max_retries = max_retries
        self.current_retry = 0

        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def handle_error(
        self,
        exception: Exception,
        retry_callback: Optional[Callable[[], None]] = None
    ) -> bool:
        self.current_retry += 1
        log_main(f"[RECOVERY] Попытка #{self.current_retry}/{self.max_retries}")

        error_type = type(exception).__name__
        error_msg = str(exception)
        log_main(f"[RECOVERY] Ошибка: {error_type}: {error_msg}")

        is_recoverable = isinstance(exception, (pygit2.GitError, FileNotFoundError, AttributeError)) or \
                         "invalid path" in str(exception).lower() or \
                         "reference not found" in str(exception).lower() or \
                         "cannot create" in str(exception).lower()

        if not is_recoverable:
            log_main("[RECOVERY] Ошибка не подлежит авто-восстановлению")
            return False

        if self.current_retry > self.max_retries:
            log_main(f"[RECOVERY] Превышено {self.max_retries} попыток")
            return False

        log_both(f"[RECOVERY] Пауза {self.recovery_delay} сек...")
        time.sleep(self.recovery_delay)

        if retry_callback:
            try:
                retry_callback()
                self.current_retry = 0
                return True
            except Exception as e:
                log_main(f"[RECOVERY] Повтор упал: {type(e).__name__}: {e}")
        return True


def github_api_get_current_head() -> Optional[str]:
    log_both("[API-HEAD] Запрос HEAD main...")
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/git/ref/heads/main"

    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            log_both(f"[API-HEAD] статус {r.status_code} (попытка {attempt})")
            r.raise_for_status()
            sha = r.json()['object']['sha']
            log_both(f"[API-HEAD] HEAD: {sha[:10]}...")
            return sha
        except (requests.Timeout, requests.ConnectionError) as e:
            log_main(f"[API-HEAD] Сетевая ошибка (попытка {attempt}): {e}")
            time.sleep(5 * attempt)
        except Exception as e:
            log_main(f"[API-HEAD] Ошибка (попытка {attempt}): {e}")
            break
    log_main("[API-HEAD] Не удалось получить HEAD после 3 попыток")
    return None


def github_api_get_remote_blobs(sha: str) -> set:
    if not sha:
        return set()

    log_soft(f"[API-TREE] Получаем дерево для {sha[:10]}...")
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/git/trees/{sha}?recursive=1"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        blobs = {item['path'] for item in data.get('tree', []) if item['type'] == 'blob'}
        log_soft(f"[API-TREE] Найдено {len(blobs)} файлов в remote")
        return blobs
    except Exception as e:
        log_main(f"[API-TREE] Ошибка получения дерева: {e}")
        return set()


def github_api_get_file_content(rel_path: str) -> Optional[str]:
    log_soft(f"[API-FILE] Запрос содержимого удалённого файла: {rel_path}")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{rel_path}"

    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 404:
                log_soft(f"[API-FILE] Файл не найден на remote: {rel_path}")
                return None
            r.raise_for_status()
            data = r.json()
            if data.get('encoding') == 'base64':
                content = base64.b64decode(data['content']).decode('utf-8', errors='replace')
                log_soft(f"[API-FILE] Успешно получено {len(content)} символов")
                return content
            else:
                log_main(f"[API-FILE] Неизвестный формат кодировки для {rel_path}")
                return None
        except Exception as e:
            log_main(f"[API-FILE] Ошибка (попытка {attempt}): {e}")
            if attempt < 3:
                time.sleep(3)

    log_main(f"[API-FILE] Не удалось получить содержимое {rel_path} после 3 попыток")
    return None


def collect_changes(temp_repo_path: Path) -> Tuple[List[str], List[str], List[str]]:
    added = []
    modified = []
    deleted = []

    head_sha = github_api_get_current_head()
    remote_files = github_api_get_remote_blobs(head_sha)

    local_rels = set()
    for f in temp_repo_path.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(temp_repo_path).as_posix()
        if rel.startswith("deleted_files/"):
            continue
        if not rel.lower().endswith(SUPPORTED_EXTENSIONS):
            continue
        if is_malformed_path(rel):
            continue
        local_rels.add(rel)

    for rel in local_rels:
        if rel in remote_files:
            modified.append(rel)
        else:
            added.append(rel)

    for rel in remote_files:
        if rel not in local_rels and not rel.startswith("deleted_files/"):
            deleted.append(rel)

    log_soft(f"[COLLECT] added: {len(added)}, modified: {len(modified)}, deleted: {len(deleted)}")
    return sorted(added), sorted(modified), sorted(deleted)


def initialize_repository(temp_repo_path: Path) -> bool:
    git_dir = temp_repo_path / ".git"
    log_main("[INIT] Проверка/инициализация репозитория после синхронизации...")

    def try_init():
        try:
            repo = pygit2.init_repository(str(temp_repo_path), bare=False)
            log_soft("[INIT] Репозиторий инициализирован")

            if repo.is_empty:
                index = repo.index
                tree = index.write_tree()
                author = pygit2.Signature('AutoSync', 'autosync@example.com')
                committer = author
                commit = repo.create_commit('refs/heads/main', author, committer,
                                           "Initial commit by AutoSync", tree, [])
                log_both("[INIT] Создан initial commit в новой ветке main")
            else:
                log_soft("[INIT] Репозиторий не пустой")

            if 'main' not in repo.branches.local:
                commit = repo.head.peel()
                repo.branches.local.create('main', commit)
                log_soft("[INIT] Создана ветка main")

            repo.set_head('refs/heads/main')
            repo.checkout('refs/heads/main')
            log_both("[INIT] HEAD установлен на main, checkout выполнен")

            return True
        except Exception as e:
            log_main(f"[INIT-ERROR] Не удалось инициализировать: {type(e).__name__}: {e}")
            traceback.print_exc(file=sys.stderr)
            return False

    if not git_dir.exists():
        log_main("[INIT] .git отсутствует — создаём новый репозиторий")
        return try_init()

    try:
        repo = pygit2.Repository(str(temp_repo_path))
        log_soft("[INIT] Репозиторий загружен")

        if 'main' not in repo.branches.local:
            commit = repo.head.peel()
            repo.branches.local.create('main', commit)
            log_soft("[INIT] Создана ветка main")

        repo.set_head('refs/heads/main')
        repo.checkout('refs/heads/main')
        log_both("[INIT] Репозиторий валиден, HEAD на main, checkout OK")
        return True
    except pygit2.GitError as e:
        log_main(f"[INIT] Репозиторий повреждён: {e}")
        traceback.print_exc(file=sys.stderr)

    for attempt in range(1, 3):
        try:
            shutil.rmtree(git_dir)
            log_both(f"[INIT-CLEAN] Удалена повреждённая .git (попытка {attempt})")
            return try_init()
        except Exception as e:
            log_main(f"[INIT-CLEAN-ERROR] Не удалось удалить .git (попытка {attempt}): {e}")
            time.sleep(3)

    log_main("[INIT] Не удалось восстановить репозиторий")
    return False


def should_include_in_tree_and_index(rel_path: str) -> bool:
    if is_malformed_path(rel_path):
        return False

    if 'temp' in rel_path.lower() or rel_path.endswith('.lock'):
        return False

    if rel_path.startswith("deleted_files/") and rel_path.lower().endswith(SUPPORTED_EXTENSIONS):
        return True

    if rel_path.lower().endswith(SUPPORTED_EXTENSIONS):
        return True

    return False


def github_api_create_tree_from_folder(folder_path: Path):
    log_both(f"[API-TREE] Создание tree из {folder_path}")

    all_files = []
    for f in folder_path.rglob("*"):
        if not f.is_file():
            continue
        rel_path = f.relative_to(folder_path).as_posix()

        if not should_include_in_tree_and_index(rel_path):
            continue

        all_files.append(f)

    if not all_files:
        log_main("[API-TREE] Нет файлов для включения в tree")
        return None

    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    base_url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}"

    tree_entries = []
    for file_path in all_files:
        rel_path = normalize_path(file_path.relative_to(folder_path).as_posix())

        try:
            content = file_path.read_bytes()
            b64 = base64.b64encode(content).decode('utf-8')

            r = requests.post(
                f"{base_url}/git/blobs",
                headers=headers,
                json={"content": b64, "encoding": "base64"},
                timeout=30
            )
            r.raise_for_status()
            blob_sha = r.json()['sha']

            tree_entries.append({
                "path": rel_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_sha
            })

            log_soft(f"[TREE-ADD] {rel_path}")
        except Exception as e:
            log_main(f"[TREE-ERROR] {rel_path}: {e}")

    if not tree_entries:
        log_main("[API-TREE] Не удалось создать ни одного blob → tree пустой")
        return None

    log_both("=== Пути в tree ===")
    for entry in tree_entries:
        log_soft(f"  → {entry['path']}")

    try:
        r = requests.post(
            f"{base_url}/git/trees",
            headers=headers,
            json={"tree": tree_entries},
            timeout=30
        )
        r.raise_for_status()
        tree_sha = r.json()['sha']
        log_both(f"[API-TREE] Tree готов: {tree_sha[:10]}...")
        return tree_sha
    except Exception as e:
        log_main(f"[API-TREE] Ошибка создания tree: {e}")
        return None


def github_api_force_push_from_tree(tree_sha, commit_message):
    log_both(f"[PUSH] force-push: {commit_message}")

    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    base_url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}"

    current_sha = github_api_get_current_head()
    if not current_sha:
        return None

    payload = {
        "message": commit_message,
        "tree": tree_sha,
        "parents": [current_sha]
    }

    try:
        r = requests.post(f"{base_url}/git/commits", headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        new_commit_sha = r.json()['sha']

        payload_ref = {"sha": new_commit_sha, "force": True}
        r_ref = requests.patch(f"{base_url}/git/refs/heads/main", headers=headers, json=payload_ref, timeout=30)
        r_ref.raise_for_status()

        log_both("[PUSH] выполнен")
        return new_commit_sha
    except Exception as e:
        log_main(f"[PUSH] Ошибка: {e}")
        return None


def push_with_retry(tree_sha, commit_message):
    for attempt in range(1, 4):
        log_both(f"[PUSH-ATTEMPT {attempt}] {commit_message}")
        new_sha = github_api_force_push_from_tree(tree_sha, commit_message)
        if new_sha:
            log_both("[PUSH] УСПЕХ")
            return new_sha
        time.sleep(5 * attempt)
    log_main("[PUSH] Все попытки исчерпаны")
    return None


def do_push():
    global push_lock
    if push_lock:
        log_main("do_push уже идёт — пропуск (global lock)")
        return

    push_lock = True
    log_both("do_push ЗАПУЩЕН")

    # root_git_backup = temporarily_evacuate_root_git()   # ← закомментировано
    root_git_backup = None   # отключаем эвакуацию .git

    temp_repo_path = FAKE_PUSH_GIT

    log_both(f"ОТЛАДКА КОНФИГА: temp_repo_path = {temp_repo_path}")
    if "fake_git_temp" not in str(temp_repo_path).lower():
        log_main("!!! КРИТИЧЕСКАЯ ОШИБКА КОНФИГА !!!")
        clear_python_cache()
        push_lock = False
        # restore_root_git(root_git_backup)   # ← закомментировано
        return

    if not temp_repo_path.exists():
        temp_repo_path.mkdir(parents=True, exist_ok=True)

    lock_file = temp_repo_path / "push.lock"
    try:
        with open(lock_file, 'x') as f:
            pass
    except FileExistsError:
        log_main("do_push заблокирован другим процессом (lock-файл существует) — пропуск")
        push_lock = False
        # restore_root_git(root_git_backup)   # ← закомментировано
        return

    clear_temp_repo_content(temp_repo_path)

    deleted_root = temp_repo_path / "deleted_files"

    recovery = PushRecoveryHandler(
        temp_repo_path=temp_repo_path,
        backup_dir=VERSIONS_DIR,
        recovery_delay=25,
        max_retries=3
    )

    try:
        log_both("[SYNC] Синхронизация изменённых файлов...")
        has_changes = sync_changed_files(
            target_dir=temp_repo_path,
            log_soft=log_soft,
            verbose=False
        )


        time.sleep(0.6)

        debug_directory_contents(temp_repo_path, "После sync")

        added, modified, deleted = collect_changes(temp_repo_path)

        # ─── КРИТИЧЕСКАЯ ЗАЩИТА ОТ ПУСТЫХ ПУШЕЙ ───────────────────────────────
        if not added and not modified and not deleted:
            log_main("[SYNC] Нет ни добавленных, ни изменённых, ни удалённых файлов — push отменён")
            return

        has_deleted = len(deleted) > 0

        if has_deleted:
            log_both(f"[DELETED] Найдено {len(deleted)} удалённых файлов — популяция deleted_files...")
            deleted_root.mkdir(exist_ok=True)
            populated_count = 0
            for rel in deleted:
                content = github_api_get_file_content(rel)
                if content is not None and content.strip():
                    flat_rel = rel.replace('/', '_').replace('\\', '_')
                    deleted_path = deleted_root / flat_rel
                    deleted_path.parent.mkdir(parents=True, exist_ok=True)
                    deleted_path.write_text(content, encoding='utf-8')
                    populated_count += 1
                    log_soft(f"[DELETED-POPULATE] {rel} → flat {flat_rel} ({len(content)} символов)")
                else:
                    log_soft(f"[DELETED-SKIP] Пустой или недоступный: {rel}")

            log_both(f"[DELETED] Успешно популировано {populated_count} из {len(deleted)} файлов")

            if not any(deleted_root.rglob("*")):
                (deleted_root / ".gitkeep").touch()
                log_soft("[GITKEEP] Добавлен .gitkeep в deleted_files (нет содержимого)")

        debug_directory_contents(deleted_root, "deleted_files после популяции")

        time.sleep(0.8)

        if not initialize_repository(temp_repo_path):
            log_main("[ERROR] Не удалось подготовить репозиторий — push отменён")
            return

        repo = pygit2.Repository(temp_repo_path)
        index = repo.index
        index.clear()

        log_both("[GIT] Добавление файлов в индекс (включая deleted_files)...")
        added_count = error_count = 0

        for file_path in temp_repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(temp_repo_path).as_posix()

            if not should_include_in_tree_and_index(rel_path):
                continue

            try:
                index.add(rel_path)
                added_count += 1
                log_soft(f"[INDEX-ADD] {rel_path}")
            except Exception as e:
                log_main(f"[GIT-ERROR] {rel_path}: {e}")
                error_count += 1

        index.write()

        if added_count == 0:
            log_main("[GIT] После фильтрации не осталось файлов для коммита — push отменён")
            return

        commit_sha = datetime.datetime.now().strftime('%Y%m%d%H%M%S')

        analyzer = CommitAnalyzer()
        comment_text = analyzer.generate_commit_description(
            commit_sha=commit_sha,
            repo_path=temp_repo_path,
            added=added,
            modified=modified,
            deleted=deleted
        )

        log_both("Сгенерированное описание коммита:")
        log_both("-" * 80)
        log_both(comment_text)
        log_both("-" * 80)

        log_both("[API] Создаём tree...")
        tree_sha = github_api_create_tree_from_folder(temp_repo_path)
        if not tree_sha:
            log_main("[API] Tree не создан — push отменён")
            return

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        message = f"PUSH - [{timestamp}]"

        log_both("[PUSH] Отправка...")
        new_commit_sha = push_with_retry(tree_sha, message)

        if new_commit_sha:
            log_main(f"[PUSH] УСПЕХ: {message}")

            log_soft(f"[COMMENT] Планируем отправку комментария через 10 сек...")
            threading.Timer(
                10,
                GitHubCommenter.post_to_commit,
                args=(new_commit_sha, comment_text)
            ).start()

        else:
            log_main("[PUSH] Не удалось выполнить пуш")

    except Exception as e:
        log_main(f"[DO_PUSH] Критическая ошибка: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stderr)
        recovery.handle_error(e, retry_callback=do_push)

    finally:
        clear_temp_repo_content(temp_repo_path)
        push_lock = False
        if lock_file.exists():
            try:
                os.remove(lock_file)
            except:
                pass

        # restore_root_git(root_git_backup)   # ← закомментировано
        time.sleep(1.5)  # Задержка для стабилизации системы

        # Принудительный перезапуск наблюдателя
        try:
            stop_observer()
            start_observer()
            log_both("[do_push] Принудительный перезапуск наблюдателя")
        except Exception as e:
            log_main(f"[do_push] Ошибка при force restart observer: {e}")

        log_both("do_push ЗАВЕРШЁН - watcher должен возобновиться")


        try:
            if callable(run_logger_clean):
                run_logger_clean()
        except Exception as e:
            log_main(f"[LOG-CLEAN] ошибка: {e}")


if __name__ == "__main__":
    log_both("=== ТЕСТ do_push.py ===")
    try:
        init_logger()
    except Exception as e:
        log_both(f"Логгер ошибка: {e}")

    do_push()
