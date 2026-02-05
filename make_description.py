"""
make_description.py

Генерация читаемого описания коммита и отправка комментария на GitHub.
Показывает ТОЛЬКО файлы с реальными строковыми изменениями.
"""

import sys
import time
from pathlib import Path
from typing import List, Optional
import requests
import base64
import difflib
import os

from app_logger import log_both, log_soft, log_main, init_logger

from config import GITHUB_USERNAME, GITHUB_REPO, GITHUB_TOKEN

# Константы
SUPPORTED_EXTENSIONS = (".md", ".json")
MAX_BLOCK_LENGTH = 1300
MAX_LINE_LENGTH = 200
MAX_LINES_PER_FILE = 10


def github_api_get_file_content(rel_path: str) -> Optional[str]:
    """Получает содержимое файла из GitHub API"""
    log_soft(f"[API-FILE] Запрос {rel_path}")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{rel_path}"

    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers, timeout=100)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            if data.get('encoding') == 'base64':
                return base64.b64decode(data['content']).decode('utf-8', errors='replace')
            return None
        except Exception as e:
            log_main(f"[API-FILE] Ошибка (попытка {attempt}): {e}")
            if attempt < 3:
                time.sleep(1.3)

    return None



def read_local_file(file_path: Path) -> Optional[str]:
    """Читает локальный файл"""
    if not file_path.exists():
        return None
    try:
        return file_path.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        log_main(f"[LOCAL-FILE] Ошибка чтения {file_path}: {e}")
        return None


def generate_diff(old_content: Optional[str], new_content: Optional[str], rel_path: str,
                  is_added: bool = False, is_deleted: bool = False) -> List[str]:
    """Генерирует diff-строки. Возвращает ТОЛЬКО значимые + и - строки"""
    if is_added and new_content:
        lines = new_content.splitlines()
        diff_lines = [f"* {line[:MAX_LINE_LENGTH]}" for line in lines if line.strip()]
    elif is_deleted and old_content:
        lines = old_content.splitlines()
        diff_lines = [f"- {line[:MAX_LINE_LENGTH]}" for line in lines if line.strip()]
    else:
        # modified
        old_lines = old_content.splitlines() if old_content else []
        new_lines = new_content.splitlines() if new_content else []
        diff = difflib.unified_diff(old_lines, new_lines, n=0)
        diff_lines = []
        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                cleaned = line[1:].strip()
                if cleaned:
                    diff_lines.append(f"* {cleaned[:MAX_LINE_LENGTH]}")
            elif line.startswith('-') and not line.startswith('---'):
                cleaned = line[1:].strip()
                if cleaned:
                    diff_lines.append(f"- {cleaned[:MAX_LINE_LENGTH]}")

    # Ограничение количества строк
    if len(diff_lines) > MAX_LINES_PER_FILE:
        diff_lines = diff_lines[:MAX_LINES_PER_FILE // 2] + ['... (ещё строки опущены)'] + diff_lines[-MAX_LINES_PER_FILE // 2:]

    return diff_lines


class CommitAnalyzer:
    def __init__(self):
        init_logger()
        log_both("CommitAnalyzer инициализирован")
    def generate_commit_description(
            self,
            commit_sha: str,
            repo_path: Path,
            added: List[str],
            modified: List[str],
            deleted: List[str]
    ) -> str:
        """Генерирует ТОЛЬКО осмысленный комментарий с реальными изменениями"""
        log_both(f"[GENERATE] Генерация описания для {commit_sha[:10]}...")

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"PUSH - [{timestamp}]"]

        # Собираем ВСЕ файлы с реальными diff
        meaningful_added = []
        meaningful_modified = []
        meaningful_deleted = []

        # ─── Обработка added ───────────────────────────────────────
        for rel in added:
            new_content = read_local_file(repo_path / rel)
            if not new_content:
                continue
            diff_lines = generate_diff(None, new_content, rel, is_added=True)
            if diff_lines:  # только если есть непустые строки
                meaningful_added.append((rel, diff_lines))

        # ─── Обработка modified ────────────────────────────────────
        for rel in modified:
            new_content = read_local_file(repo_path / rel)
            old_content = github_api_get_file_content(rel)
            diff_lines = generate_diff(old_content, new_content, rel)
            if diff_lines:
                meaningful_modified.append((rel, diff_lines))

        # ─── Обработка deleted ─────────────────────────────────────
        deleted_root = repo_path / "deleted_files"
        for rel in deleted:
            deleted_path = deleted_root / rel.replace("/", os.sep)
            old_content = read_local_file(deleted_path)
            if not old_content:
                continue
            diff_lines = generate_diff(old_content, None, rel, is_deleted=True)
            if diff_lines:
                meaningful_deleted.append((rel, diff_lines))

        # Подсчёт реальных изменений
        real_added = len(meaningful_added)
        real_modified = len(meaningful_modified)
        real_deleted = len(meaningful_deleted)
        total_real = real_added + real_modified + real_deleted

        total_files_scanned = len(added) + len(modified) + len(deleted)

        lines.append(f"Всего реальных изменений: {total_real} (из {total_files_scanned} файлов)")

        if total_real == 0:
            lines.append("")
            lines.append("Нет файлов с реальными строковыми изменениями.")
            lines.append("END")
            return "\n".join(lines)

        if real_added + real_modified > 0:
            lines.append(f"Добавлено/изменено с содержимыми изменениями: {real_added + real_modified}")

        if real_deleted > 0:
            lines.append(f"Удалено с содержимым: {real_deleted}")

        lines.append("")

        # ─── Вывод только значимых файлов ──────────────────────────
        if meaningful_added or meaningful_modified:
            lines.append("=== Файлы с реальными изменениями ===")
            lines.append("")

            for rel, diff_lines in sorted(meaningful_added + meaningful_modified, key=lambda x: x[0]):
                is_added = rel in added
                status = "Добавлен" if is_added else "Изменён"
                lines.append(f"Файл: {rel}")
                lines.append(f"Статус: {status}")
                lines.extend(diff_lines)
                lines.append("")
                lines.append("────────────────────────────────────────────────────────────")
                lines.append("")

        if meaningful_deleted:
            lines.append("=== Удалённые файлы с содержимым ===")
            lines.append("")

            for rel, diff_lines in sorted(meaningful_deleted, key=lambda x: x[0]):
                lines.append(f"Файл: {rel}")
                lines.append("Статус: Удалён")
                lines.extend(diff_lines)
                lines.append("")
                lines.append("────────────────────────────────────────────────────────────")
                lines.append("")

        if total_files_scanned > total_real:
            lines.append("=== Файлы без значимых изменений ===")
            lines.append(f"(остальные {total_files_scanned - total_real} файлов либо пустые, либо ложные срабатывания)")
            lines.append("")

        lines.append("END")

        text = "\n".join(lines)
        log_both(f"[GENERATE] Сформировано описание (длина: {len(text)} символов)")
        return text


class GitHubCommenter:
    @staticmethod
    def post_to_commit(commit_sha: str, comment_text: str) -> bool:
        if not comment_text.strip():
            log_main("[COMMENTER] Пустой комментарий — пропуск")
            return False

        url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/commits/{commit_sha}/comments"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        data = {"body": comment_text}

        log_both(f"[COMMENTER] Отправка к {commit_sha[:12]}...")

        for attempt in range(1, 6):
            try:
                resp = requests.post(url, headers=headers, json=data, timeout=30)
                if resp.status_code == 201:
                    log_both(f"[COMMENTER] Успех! Комментарий добавлен")
                    return True
                else:
                    log_main(f"[COMMENTER] Ошибка {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                log_main(f"[COMMENTER] Ошибка (попытка {attempt}): {e}")
            time.sleep(4)

        log_main("[COMMENTER] Не удалось отправить комментарий")
        return False


if __name__ == "__main__":
    init_logger()
    log_both("=== Тест make_description.py ===")

    test_repo = Path("test_repo")
    test_sha = "abcdef123456"
    test_added = ["new.md", "empty.md"]
    test_modified = ["old.md"]
    test_deleted = ["gone.md"]

    analyzer = CommitAnalyzer()
    text = analyzer.generate_commit_description(
        commit_sha=test_sha,
        repo_path=test_repo,
        added=test_added,
        modified=test_modified,
        deleted=test_deleted
    )

    log_both(text)


