# -*- coding: utf-8 -*-
"""
gui/version_ops.py

Операции с версиями репозитория для GUI:
- клонирование репозитория и checkout по commit/тегу (pygit2)
- получение списка последних коммитов через GitHub API
- получение комментария коммита
- копирование SHA в буфер обмена

(Раньше файл назывался git_gui_utils.py и содержал ещё альтернативную
реализацию push через REST API — она была мёртвой и удалена.
Единственный рабочий push живёт в sync/push.py.)
"""

import os
import sys
import time
import requests
import pygit2

from core.logger import log_main, log_soft, log_both
from core.config import VERSIONS_DIR

IS_WINDOWS = os.name == "nt"


# ────────────────────────────────────────────────
# КЛОНИРОВАНИЕ И ВОССТАНОВЛЕНИЕ ВЕРСИИ
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
# FETCH PUSHES через GitHub API
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
# КОПИРОВАНИЕ SHA В БУФЕР ОБМЕНА
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
