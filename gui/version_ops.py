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
import json
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
import pygit2

from core.logger import log_main, log_soft, log_both
from core.config import VERSIONS_DIR

IS_WINDOWS = os.name == "nt"




_CACHE_FILE = Path(__file__).resolve().parents[1] / "push_cache.json"
_pushes_cache = {}   # in-memory: repo_key -> list


def _build_session() -> requests.Session:
    """requests.Session с ретраями на connect/read-таймауты и 5xx."""
    session = requests.Session()
    try:
        from urllib3.util.retry import Retry
        try:
            retry = Retry(
                total=3, connect=3, read=3,
                backoff_factor=1.5,                     # паузы 0, 1.5, 3, 6 сек…
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
                raise_on_status=False,
            )
        except TypeError:
            # старые версии urllib3 (method_whitelist вместо allowed_methods)
            retry = Retry(total=3, backoff_factor=1.5,
                          status_forcelist=(429, 500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    except Exception:
        pass  # без urllib3.Retry сессия всё равно работает, просто без авто-ретраев
    return session


_session = _build_session()


def _cache_load(repo_key: str) -> list:
    """Возвращает кэш (память → диск) для repo_key, иначе []."""
    if _pushes_cache.get(repo_key):
        return _pushes_cache[repo_key]
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("repo") == repo_key:
            _pushes_cache[repo_key] = data.get("pushes", [])
            return _pushes_cache[repo_key]
    except Exception:
        pass
    return []


def _cache_save(repo_key: str, pushes: list) -> None:
    _pushes_cache[repo_key] = pushes
    try:
        _CACHE_FILE.write_text(
            json.dumps({"repo": repo_key, "pushes": pushes}, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass


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
    """
    Получает последние коммиты через GitHub API — отказоустойчиво.

    - ретраи с бэк-оффом (внутри сессии) гасят кратковременные таймауты/5xx;
    - при полном сбое сети возвращается КЭШ последнего успешного ответа,
      чтобы список в GUI не обнулялся;
    - 409 (пустой репозиторий) — не ошибка, просто пушей ещё нет.
    """
    repo_key = f"{github_user}/{github_repo}"
    url = f"https://api.github.com/repos/{github_user}/{github_repo}/commits"
    headers = {"Authorization": f"token {github_token}"}

    log_soft(f"Запрашиваем последние коммиты: {url}")

    try:
        # timeout=(connect, read): быстро отсекаем «висящий» коннект, даём время на чтение
        resp = _session.get(url, headers=headers, timeout=(6, 20))

        if resp.status_code == 200:
            data = resp.json()
            _cache_save(repo_key, data)
            log_soft(f"Получено {len(data)} коммитов")
            return data

        if resp.status_code == 409:
            log_soft("GitHub: репозиторий пуст (409) — пушей ещё нет")
            return []

        # прочие ошибки: не роняем список — показываем последний известный кэш
        cached = _cache_load(repo_key)
        log_main(f"GitHub API вернул {resp.status_code} — показываю кэш ({len(cached)} коммитов)")
        return cached

    except Exception as e:
        cached = _cache_load(repo_key)
        log_soft(f"Сеть недоступна ({type(e).__name__}) → показываю кэш ({len(cached)} коммитов)")
        return cached


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
