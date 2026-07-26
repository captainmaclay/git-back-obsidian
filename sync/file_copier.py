"""
Модуль с классом SmartSyncCopier — умная синхронизация файлов и папок.
Копирует только изменённые/новые файлы (по размеру + хэшу + mtime для точности).
Удалённые файлы и папки НЕ обрабатываются здесь - перенесено в do_push.

Копирование выполняется ПАРАЛЛЕЛЬНО (пул потоков): все файлы обрабатываются
одновременно, а не последовательно. Задача I/O-bound (чтение/запись + хэш),
поэтому потоки дают реальный выигрш по времени — GIL освобождается на I/O.
"""

from pathlib import Path
import shutil
import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable

from core.config import WATCHED_FOLDER


class SmartSyncCopier:
    def __init__(
        self,
        source_dir: Path,
        log_func: Optional[Callable[[str], None]] = None,
        ignored_dirs: list[str] = None,
        max_workers: Optional[int] = None,
    ):
        self.source_dir = source_dir
        self.log = log_func or (lambda msg: None)
        self.ignored_dirs = ignored_dirs or [".git", "__pycache__", ".obsidian"]
        self.protected_exts = {".py", ".pyc", ".pyo", ".pyd"}
        # I/O-bound → потоков можно заметно больше числа ядер
        self.max_workers = max_workers or min(32, (os.cpu_count() or 4) * 4)

    def _log(self, msg: str):
        self.log(msg)

    def _compute_hash(self, file_path: Path) -> str:
        hasher = hashlib.md5()
        try:
            with file_path.open("rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            self._log(f"[HASH-ERROR] {file_path}: {e}")
            return ""

    def _process_one(self, rel_path: str, src_path: Path, target_dir: Path) -> str:
        """
        Обрабатывает ОДИН файл: решает, нужно ли копировать, и копирует.
        Выполняется в отдельном потоке. Возвращает 'copied' | 'skipped' | 'failed'.
        Не трогает общие изменяемые данные — результат агрегируется вызывающим кодом.
        """
        tgt_path = target_dir / rel_path

        try:
            src_stat = src_path.stat()
        except Exception as e:
            self._log(f"[SOURCE-ERROR] {rel_path}: {e}")
            return "failed"

        # Решаем, копировать ли (логика эквивалентна прежней последовательной)
        should_copy = True
        try:
            if tgt_path.is_file():
                tgt_stat = tgt_path.stat()
                # Если размер совпал — сверяем хэш (иначе точно изменён, хэш не нужен)
                if src_stat.st_size == tgt_stat.st_size:
                    if self._compute_hash(src_path) == self._compute_hash(tgt_path):
                        should_copy = False
                    elif src_stat.st_mtime <= tgt_stat.st_mtime:
                        should_copy = False
        except Exception:
            should_copy = True  # при любой неясности — безопаснее скопировать

        if not should_copy:
            return "skipped"

        try:
            tgt_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, tgt_path)
            self._log(f"[COPY-OK] {rel_path}")
            return "copied"
        except Exception as e:
            self._log(f"[COPY-ERROR] {rel_path}: {e}")
            return "failed"

    def sync(self, target_dir: Path) -> bool:
        """
        Возвращает has_changes: были ли копирования/обновления.
        Обработка удалений отключена - только синхронизация существующих.
        """
        self._log("[SMART-SYNC] Запуск параллельной синхронизации...")
        target_dir = Path(target_dir)

        # 1. Собираем список файлов и папок источника (быстрый обход, без хэшей)
        source_files = []          # список кортежей (rel_path, src_path)
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
            source_files.append((rel_path, src_path))

        # 2. Заранее создаём папки-источники (дёшево, последовательно)
        for rel_dir in source_dirs:
            try:
                (target_dir / rel_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._log(f"[MKDIR-ERROR] {rel_dir}: {e}")

        # 3. Обрабатываем ВСЕ файлы одновременно в пуле потоков
        success_count = skipped_count = failed_count = 0
        if source_files:
            workers = min(self.max_workers, len(source_files))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = pool.map(
                    lambda item: self._process_one(item[0], item[1], target_dir),
                    source_files,
                )
                for result in results:
                    if result == "copied":
                        success_count += 1
                    elif result == "skipped":
                        skipped_count += 1
                    else:
                        failed_count += 1

        self._log(
            f"[SMART-SYNC] Добавлено/обновлено: {success_count}, "
            f"пропущено: {skipped_count}, ошибок: {failed_count} "
            f"(потоков: {min(self.max_workers, max(1, len(source_files)))})"
        )

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
