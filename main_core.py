"""
Отдельный модуль с главной функцией do_push() — полностью на GitHub REST API.
Без pygit2 и локального git-репозитория.
Временная папка создаётся и удаляется каждый раз.
"""
import os
import shutil
import sys
import traceback
import datetime
import time
import base64
import requests
import tempfile
from pathlib import Path
import config



from app_logger import log_main, log_both, log_soft, init_logger

from config import (
    GITHUB_USERNAME,
    GITHUB_TOKEN,
    GITHUB_REPO,
    WATCHED_FOLDER,
    DELETED_TEMP,
    push_lock,
    parser_logger,
    run_logger_clean,
    VERSIONS_DIR,
)

VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


def github_api_get_current_head():
    """Получает SHA последнего коммита main"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/git/ref/heads/main"

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()['object']['sha']
    except Exception as e:
        log_main(f"[API-ERROR] Не удалось получить HEAD main: {e}")
        return None


def github_api_create_tree_from_folder(folder_path: Path):
    """Создаёт tree из всех файлов в папке"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    base_url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}"

    try:
        tree_entries = []
        for root, _, files in os.walk(folder_path):
            for file in files:
                if file.startswith('.') or 'deleted_temp' in root:
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(folder_path).as_posix()
                try:
                    content = file_path.read_bytes()
                except Exception as e:
                    log_main(f"Не удалось прочитать {rel_path}: {e}")
                    continue
                b64 = base64.b64encode(content).decode('utf-8')

                r = requests.post(
                    f"{base_url}/git/blobs",
                    headers=headers,
                    json={"content": b64, "encoding": "base64"},
                    timeout=15
                )
                if r.status_code != 201:
                    log_main(f"Ошибка blob {rel_path}: {r.status_code} - {r.text[:200]}")
                    continue
                blob_sha = r.json()['sha']
                log_soft(f"Blob для {rel_path}: {blob_sha}")

                tree_entries.append({
                    "path": rel_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha
                })

        if not tree_entries:
            log_main("Нет файлов для коммита → пустой tree")
            return None

        r = requests.post(
            f"{base_url}/git/trees",
            headers=headers,
            json={"tree": tree_entries},
            timeout=25
        )
        if r.status_code != 201:
            log_main(f"Ошибка создания tree: {r.status_code} - {r.text[:200]}")
            return None

        tree_sha = r.json()['sha']
        log_both(f"[API] Новый tree создан: {tree_sha}")
        return tree_sha

    except Exception as e:
        log_main(f"[API-TREE-ERROR] {type(e).__name__}: {e}")
        return None


def github_api_force_push_from_tree(tree_sha, commit_message):
    """Создаёт коммит и force-update main"""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    base_url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}"

    try:
        current_sha = github_api_get_current_head()
        if not current_sha:
            log_main("Нет текущего HEAD → невозможно создать коммит")
            return False

        log_both(f"[API-PUSH] Создаём коммит parent={current_sha[:8]} tree={tree_sha[:8]}")

        r = requests.post(
            f"{base_url}/git/commits",
            headers=headers,
            json={
                "message": commit_message,
                "tree": tree_sha,
                "parents": [current_sha]
            },
            timeout=15
        )
        if r.status_code != 201:
            log_main(f"[API-ERROR] Создание коммита failed: {r.status_code} - {r.text[:200]}")
            return False

        new_commit_sha = r.json()['sha']
        log_both(f"[API-PUSH] Создан коммит: {new_commit_sha[:10]}")

        r = requests.patch(
            f"{base_url}/git/refs/heads/main",
            headers=headers,
            json={"sha": new_commit_sha, "force": True},
            timeout=10
        )
        if r.status_code != 200:
            log_main(f"[API-ERROR] Force-push failed: {r.status_code} - {r.text[:200]}")
            return False

        log_main(f"[API-SUCCESS] main обновлён (force) → {commit_message}")
        return True

    except Exception as e:
        log_main(f"[API-CRITICAL] {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


# ─── Интеграция conflict.py ─────────────────────────────────────────────────

def handle_conflict_force_push(local_tree_sha=None):
    """
    Проверка конфликта + создание бэкап-ветки при необходимости
    Возвращает: 'ok' / 'force_needed' / False
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    conflict_branch = f"Conflict_{timestamp}"
    log_both(f"[CONFLICT] Проверка → {timestamp}")

    try:
        main_sha = github_api_get_current_head()
        if not main_sha:
            log_main("Не удалось получить HEAD → считаем конфликт")
            main_sha = None

        server_tree = None
        if main_sha:
            commit_resp = requests.get(
                f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/git/commits/{main_sha}",
                headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
                timeout=10
            )
            if commit_resp.status_code == 200:
                commit_data = commit_resp.json()
                server_tree = commit_data.get('tree', {}).get('sha')
            else:
                log_main(f"Не удалось получить commit {main_sha[:8]}: {commit_resp.status_code}")

        if local_tree_sha and server_tree and local_tree_sha == server_tree:
            log_both("Дерево совпадает с серверным → можно было бы fast-forward")
            return 'ok'

        log_both("Расхождение → создаём бэкап-ветку")

        success = False
        for attempt in range(1, 4):
            payload = {"ref": f"refs/heads/{conflict_branch}", "sha": main_sha}
            r = requests.post(
                f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/git/refs",
                headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
                json=payload,
                timeout=12
            )
            if r.status_code in (201, 422):
                log_both(f"[CONFLICT] Ветка {conflict_branch} создана / уже существует")
                success = True
                break
            log_main(f"Попытка {attempt}/3: {r.status_code} {r.text[:120]}")
            time.sleep(2.5)

        if success:
            return 'force_needed'

        # fallback
        backup_dir = VERSIONS_DIR / f"failed_{timestamp}"
        backup_dir.mkdir(exist_ok=True)
        (backup_dir / "conflict_info.txt").write_text(
            f"Main SHA: {main_sha or 'не получен'}\n"
            f"Local tree: {local_tree_sha or 'не передан'}\n"
            f"Дата: {timestamp}\n"
        )
        log_main(f"[FALLBACK] Метка конфликта → {backup_dir}")
        return False

    except Exception as e:
        log_main(f"[CONFLICT CRASH] {type(e).__name__}: {e}")
        return False

def sync_files_to_fake(target_dir: Path | None = None):
    """
    Синхронизация файлов из WATCHED_FOLDER → указанную папку (target_dir).
    В API-режиме target_dir — это временная папка, а не постоянный FAKE_PUSH_GIT.
    """
    if target_dir is None:
        target_dir = config.FAKE_PUSH_GIT  # fallback...
    target_dir = Path(target_dir).resolve()
# ─── Основная функция ───────────────────────────────────────────────────────

def do_push():
    global push_lock
    if push_lock:
        log_main("do_push уже выполняется → пропуск")
        return

    push_lock = True
    log_both("do_push ЗАПУЩЕН")

    temp_repo_path = None

    try:
        log_both("[TEMP] Создаём временную папку...")
        temp_dir = tempfile.mkdtemp(prefix="temp_sync_")
        temp_repo_path = Path(temp_dir)
        log_both(f"[TEMP] Временная папка: {temp_repo_path}")

        log_both("[1] Синхронизация файлов из OneDrive → временная папка")
        sync_files_to_fake(target_dir=temp_repo_path)
        time.sleep(0.8)

        log_both("[API] Создаём tree из временной папки...")
        tree_sha = github_api_create_tree_from_folder(temp_repo_path)
        if not tree_sha:
            log_main("Не удалось создать tree → push отменён")
            return

        log_both("[CONFLICT] Проверка перед пушем...")
        conflict_status = handle_conflict_force_push(tree_sha)

        if conflict_status is False:
            log_main("Критическая ошибка проверки конфликта → push отменён")
            return

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        message = f"AutoSync {timestamp}"
        log_both("[9] Выполняем push через GitHub API")
        push_success = github_api_force_push_from_tree(tree_sha, message)

        if push_success:
            log_main(f"УСПЕШНЫЙ PUSH через API → {message}")
        else:
            log_main("Push через API не удался — смотрите выше ошибки")

    except Exception as e:
        log_main(f"КРИТИЧЕСКАЯ ОШИБКА В do_push: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stderr)

    finally:
        if temp_repo_path and temp_repo_path.exists():
            log_both(f"[TEMP] Удаляем: {temp_repo_path}")
            for attempt in range(5):
                try:
                    shutil.rmtree(temp_repo_path, ignore_errors=False)
                    log_both("[TEMP] Удалено успешно")
                    break
                except Exception as e:
                    log_main(f"[TEMP] Попытка {attempt+1}/5: {e}")
                    time.sleep(2.5)
            else:
                log_main("[TEMP] Не удалось удалить — оставляем")

        if DELETED_TEMP.exists():
            try:
                shutil.rmtree(DELETED_TEMP, ignore_errors=True)
                log_main("deleted_temp очищена")
            except Exception as e:
                log_main(f"Не удалось очистить deleted_temp: {e}")

        push_lock = False
        log_both("do_push ЗАВЕРШЁН")

        try:
            if callable(parser_logger):
                parser_logger("")
            if callable(run_logger_clean):
                run_logger_clean()
        except Exception as e:
            log_main(f"Ошибка очистки логов: {e}")


# ─── Тестовый запуск ───
if __name__ == "__main__":
    log_both("=== ТЕСТОВЫЙ ЗАПУСК do_push.py ===")
    try:
        init_logger()
        log_both("Логгер успешно инициализирован")
    except Exception as e:
        log_both(f"Логгер не инициализирован: {e}")

    try:
        do_push()
    except Exception as e:
        log_both(f"Тест завершился ошибкой: {type(e).__name__}: {e}")
        traceback.print_exc()

