"""
Модуль с классом SmartSyncCopier — умная синхронизация файлов и папок.
Копирует только изменённые/новые файлы (по mtime + размеру + хэшу для точности).
Удалённые файлы и папки НЕ обрабатываются здесь - перенесено в do_push.
"""

from pathlib import Path
import shutil
import os
import hashlib
from typing import Optional, Callable
from config import WATCHED_FOLDER

class SmartSyncCopier:
    def __init__(
        self,
        source_dir: Path,
        log_func: Optional[Callable[[str], None]] = None,
        ignored_dirs: list[str] = None,
    ):
        self.source_dir = source_dir
        self.log = log_func or (lambda msg: None)
        self.ignored_dirs = ignored_dirs or [".git", "__pycache__", ".obsidian"]
        self.protected_exts = {".py", ".pyc", ".pyo", ".pyd"}

    def _log(self, msg: str):
        self.log(msg)

    def _compute_hash(self, file_path: Path) -> str:
        hasher = hashlib.md5()
        try:
            with file_path.open("rb") as f:
                while chunk := f.read(4096):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            self._log(f"[HASH-ERROR] {file_path}: {e}")
            return ""

    def sync(self, target_dir: Path) -> bool:
        """
        Возвращает has_changes: были ли копирования/обновления
        Обработка удалений отключена - только синхронизация существующих.
        """
        self._log("[SMART-SYNC] Запуск умной синхронизации...")

        success_count = 0
        failed_count = 0
        skipped_count = 0

        # 1. Файлы источника
        source_files = {}
        source_dirs = set()
        for src_path in self.source_dir.rglob("*"):
            rel_path = src_path.relative_to(self.source_dir).as_posix()
            if any(ign in rel_path.split('/') for ign in self.ignored_dirs):
                continue
            if src_path.is_dir():
                source_dirs.add(rel_path)
                continue
            if not src_path.is_file():
                continue
            try:
                stat = src_path.stat()
                file_hash = self._compute_hash(src_path)
                source_files[rel_path] = {
                    'mtime': stat.st_mtime,
                    'size': stat.st_size,
                    'hash': file_hash,
                    'src': src_path
                }
            except Exception as e:
                self._log(f"[SOURCE-ERROR] {rel_path}: {e}")

        # 2. Файлы цели
        target_files = {}
        for tgt_path in target_dir.rglob("*"):
            rel_path = tgt_path.relative_to(target_dir).as_posix()
            if tgt_path.is_dir():
                continue
            if not tgt_path.is_file():
                continue
            try:
                stat = tgt_path.stat()
                file_hash = self._compute_hash(tgt_path)
                target_files[rel_path] = {
                    'mtime': stat.st_mtime,
                    'size': stat.st_size,
                    'hash': file_hash,
                    'tgt': tgt_path
                }
            except Exception:
                pass

        # 3. Копируем новые/изменённые
        for rel_path, src_info in source_files.items():
            tgt_path = target_dir / rel_path
            tgt_path.parent.mkdir(parents=True, exist_ok=True)

            should_copy = True
            if rel_path in target_files:
                tgt_info = target_files[rel_path]
                if src_info['hash'] == tgt_info['hash']:
                    should_copy = False
                    skipped_count += 1
                elif src_info['mtime'] <= tgt_info['mtime'] and src_info['size'] == tgt_info['size']:
                    should_copy = False
                    skipped_count += 1

            if should_copy:
                try:
                    shutil.copy2(src_info['src'], tgt_path)
                    self._log(f"[COPY-OK] {rel_path}")
                    success_count += 1
                except Exception as e:
                    self._log(f"[COPY-ERROR] {rel_path}: {e}")
                    failed_count += 1

        # 4. Создаём отсутствующие папки из источника
        for rel_dir in source_dirs:
            (target_dir / rel_dir).mkdir(parents=True, exist_ok=True)

        log_summary = f"[SMART-SYNC] Добавлено/обновлено: {success_count}, пропущено: {skipped_count}, ошибок: {failed_count}"
        self._log(log_summary)

        return success_count > 0


def sync_changed_files(
    target_dir: Path,
    deleted_dir: Optional[Path] = None,  # Ignored
    log_soft=None,
    verbose: bool = False,
    allow_delete: bool = False  # Ignored
) -> bool:
    copier = SmartSyncCopier(
        source_dir=WATCHED_FOLDER,
        log_func=log_soft,
        ignored_dirs=[".git", "__pycache__", ".obsidian"]
    )
    return copier.sync(target_dir)
