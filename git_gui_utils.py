# -*- coding: utf-8 -*-
"""
Утилиты для GUI:
- клонирование репозитория и checkout по commit/тегу (pygit2)
- fetch последних коммитов через GitHub API
- получение комментария коммита
- копирование SHA в буфер обмена
- пуш через чистый GitHub REST API (замена do_push_with_fake_git)
"""

from app_logger import log_main, log_soft, log_both

import time
import os
import shutil
import sys
import base64
import requests
import traceback
import datetime
import tempfile
from pathlib import Path

import pygit2

from config import (
    REPO_PATH, FAKE_PUSH_GIT,
    GITHUB_USERNAME, GITHUB_REPO, GITHUB_TOKEN,
    WATCHED_FOLDER, DELETED_TEMP, VERSIONS_DIR,
    IGNORED_DIRS   # ← добавлен импорт
)

IS_WINDOWS = os.name == "nt"




# ────────────────────────────────────────────────
# КЛОНИРОВАНИЕ И ВОССТАНОВЛЕНИЕ ВЕРСИИ (без изменений)
# ────────────────────────────────────────────────

def clone_version(commit_hash: str, github_user: str, github_repo: str, github_token: str):
    """
    Клонирует репозиторий и восстанавливает указанную версию по commit/тегу.
    Сохраняет в папку Versions/commit_hash_дата-время
    """
    if not commit_hash:
        log_main("Ошибка: commit_hash пустой — клонирование отменено")
        return

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    folder_name = f"{commit_hash}_{timestamp}"
    clone_path = VERSIONS_DIR / folder_name
    clone_path.mkdir(exist_ok=True)

    url = f"https://{github_user}:{github_token}@github.com/{github_user}/{github_repo}.git"

    log_main(f"Начинаем клонирование версии {commit_hash} → {clone_path}")

    try:
        repo = pygit2.clone_repository(url, str(clone_path), bare=False)
        log_main(f"Репозиторий успешно клонирован в {clone_path}")

        obj = repo.revparse_single(commit_hash)
        if isinstance(obj, pygit2.Tag):
            obj = obj.target
        if isinstance(obj, pygit2.Commit):
            repo.checkout_tree(obj)
            repo.set_head(obj.id)
            log_main(f"Версия {commit_hash} успешно восстановлена")
        else:
            log_main(f"Не удалось распознать объект для checkout: {type(obj).__name__}")

    except Exception as e:
        log_main(f"Ошибка pygit2 при клонировании версии {commit_hash}: {type(e).__name__}: {e}")


def open_versions():
    """Открывает папку Versions в проводнике/файловом менеджере"""
    path = VERSIONS_DIR.resolve()
    log_soft(f"Открываем папку версий: {path}")

    try:
        if IS_WINDOWS:
            os.startfile(str(path))
        elif sys.platform == "darwin":
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")
    except Exception as e:
        log_main(f"Не удалось открыть папку версий: {e}")


# ────────────────────────────────────────────────
# FETCH PUSHES через GitHub API (без изменений)
# ────────────────────────────────────────────────

def fetch_pushes(github_user: str, github_repo: str, github_token: str):
    """Получает последние коммиты из репозитория через GitHub API"""
    url = f"https://api.github.com/repos/{github_user}/{github_repo}/commits"
    headers = {"Authorization": f"token {github_token}"}

    log_soft(f"Запрашиваем последние коммиты через GitHub API: {url}")

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            log_soft(f"Получено {len(data)} коммитов")
            return data
        else:
            log_main(f"GitHub API вернул ошибку: {resp.status_code} - {resp.text[:200]}")
            return []
    except Exception as e:
        log_main(f"Ошибка запроса к GitHub API: {type(e).__name__}: {e}")
        return []


def fetch_commit_comment(commit_sha: str, github_user: str, github_repo: str, github_token: str):
    """Получает полный комментарий коммита по SHA"""
    url = f"https://api.github.com/repos/{github_user}/{github_repo}/commits/{commit_sha}"
    headers = {"Authorization": f"token {github_token}"}

    log_soft(f"Запрашиваем комментарий коммита: {commit_sha}")

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            message = data["commit"]["message"]
            log_soft(f"Комментарий коммита получен (длина: {len(message)} символов)")
            return message
        else:
            log_main(f"GitHub API ошибка для коммита {commit_sha}: {resp.status_code}")
            return f"Ошибка: {resp.status_code}"
    except Exception as e:
        log_main(f"Ошибка получения комментария коммита {commit_sha}: {type(e).__name__}: {e}")
        return f"Ошибка: {e}"


# ────────────────────────────────────────────────
# КОПИРОВАНИЕ SHA В БУФЕР ОБМЕНА (без изменений)
# ────────────────────────────────────────────────

def copy_push_sha(selected_commit: str, gui_callback=None):
    """Копирует SHA коммита в буфер обмена"""
    if not selected_commit:
        log_main("Нет выбранного SHA для копирования")
        return

    log_soft(f"Копируем SHA в буфер обмена: {selected_commit}")

    try:
        if IS_WINDOWS:
            import ctypes
            ctypes.windll.user32.OpenClipboard(0)
            ctypes.windll.user32.EmptyClipboard()
            ctypes.windll.user32.SetClipboardText(selected_commit.encode('utf-8'))
            ctypes.windll.user32.CloseClipboard()
        elif sys.platform == "darwin":
            os.system(f"echo '{selected_commit}' | pbcopy")
        else:
            os.system(f"echo '{selected_commit}' | xclip -selection clipboard")

        log_main(f"SHA {selected_commit} успешно скопирован в буфер обмена")
        if gui_callback:
            gui_callback(selected_commit)
    except Exception as e:
        log_main(f"Ошибка копирования SHA {selected_commit}: {type(e).__name__}: {e}")


# ────────────────────────────────────────────────
# PUSH ЧЕРЕЗ GITHUB REST API (без локального git)
# ────────────────────────────────────────────────

def do_push_with_fake_git(repo_path: Path = REPO_PATH, fake_git: Path = FAKE_PUSH_GIT):
    """
    Выполняет push напрямую через GitHub REST API.
    Игнорирует локальный репозиторий и FAKE_PUSH_GIT.
    Берёт актуальное содержимое из WATCHED_FOLDER.
    """
    log_both("Запуск push через GitHub REST API (без локального git)")

    # 1. Создаём временную папку
    temp_dir = tempfile.mkdtemp(prefix="api_push_")
    temp_path = Path(temp_dir)
    log_soft(f"Временная папка для API-push: {temp_path}")

    try:
        # 2. Копируем актуальные файлы из WATCHED_FOLDER
        log_both("[SYNC] Копируем содержимое из OneDrive → временная папка")
        DELETED_TEMP.mkdir(parents=True, exist_ok=True)

        copied = 0
        for src in WATCHED_FOLDER.rglob("*"):
            if src.is_dir() or any(p in IGNORED_DIRS for p in src.parts):
                continue
            rel = src.relative_to(WATCHED_FOLDER)
            dst = temp_path / rel
            if '.git' in rel.parts or 'deleted_temp' in rel.parts:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(src, dst)
                copied += 1
                log_soft(f"  + {rel}")

        log_both(f"Скопировано/обновлено файлов: {copied}")

        # 3. Создаём tree через API
        log_both("[API] Создаём Git tree...")
        tree_sha = _create_tree_from_folder(temp_path)
        if not tree_sha:
            log_main("Не удалось создать tree → push отменён")
            return

        # 4. Создаём коммит и force-push
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        message = f"Autosync GUI push {timestamp}"
        log_both(f"[API-PUSH] Коммит: {message}")

        success = _force_push_tree(tree_sha, message)
        if success:
            log_main(f"[SUCCESS] Push выполнен через API → {message}")
        else:
            log_main("Push через API не удался")

    except Exception as e:
        log_main(f"Критическая ошибка в API-push: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        # 5. Очистка временной папки
        try:
            shutil.rmtree(temp_path, ignore_errors=True)
            log_soft("Временная папка удалена")
        except Exception as e:
            log_main(f"Не удалось удалить временную папку: {e}")


# ─── Вспомогательные функции для API-push ────────────────────────────────────

def _create_tree_from_folder(folder: Path):
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    base = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}"

    tree_entries = []

    for root, _, files in os.walk(folder):
        for file in files:
            if file.startswith('.') or 'deleted_temp' in root:
                continue
            fp = Path(root) / file
            rel = fp.relative_to(folder).as_posix()

            try:
                content = fp.read_bytes()
            except Exception as e:
                log_main(f"Не удалось прочитать {rel}: {e}")
                continue

            b64 = base64.b64encode(content).decode()

            r = requests.post(
                f"{base}/git/blobs",
                headers=headers,
                json={"content": b64, "encoding": "base64"},
                timeout=15
            )
            if r.status_code != 201:
                log_main(f"Blob не создан для {rel}: {r.status_code}")
                continue

            sha = r.json()["sha"]
            tree_entries.append({
                "path": rel,
                "mode": "100644",
                "type": "blob",
                "sha": sha
            })

    if not tree_entries:
        log_main("Нет файлов → tree пустой")
        return None

    r = requests.post(
        f"{base}/git/trees",
        headers=headers,
        json={"tree": tree_entries},
        timeout=25
    )
    if r.status_code != 201:
        log_main(f"Tree не создан: {r.status_code} - {r.text[:200]}")
        return None

    tree_sha = r.json()["sha"]
    log_both(f"Tree создан: {tree_sha}")
    return tree_sha


def _force_push_tree(tree_sha: str, message: str) -> bool:
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    base = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}"

    # 1. Получаем текущий HEAD
    r = requests.get(f"{base}/git/ref/heads/main", headers=headers, timeout=10)
    if r.status_code != 200:
        log_main(f"Не удалось получить HEAD main: {r.status_code}")
        return False
    current_sha = r.json()["object"]["sha"]

    # 2. Создаём коммит
    r = requests.post(
        f"{base}/git/commits",
        headers=headers,
        json={
            "message": message,
            "tree": tree_sha,
            "parents": [current_sha]
        },
        timeout=15
    )
    if r.status_code != 201:
        log_main(f"Коммит не создан: {r.status_code} - {r.text[:200]}")
        return False

    new_commit_sha = r.json()["sha"]
    log_soft(f"Создан коммит: {new_commit_sha[:10]}")

    # 3. Force-update main
    r = requests.patch(
        f"{base}/git/refs/heads/main",
        headers=headers,
        json={"sha": new_commit_sha, "force": True},
        timeout=10
    )
    if r.status_code != 200:
        log_main(f"Force-push failed: {r.status_code} - {r.text[:200]}")
        return False

    log_main("[API-PUSH] Успешный force-push")
    return True



