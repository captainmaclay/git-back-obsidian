"""
Single Instance Protection — Git Autosync & Version Restore

✔ Windows: Global Mutex (pywin32)
✔ Linux/macOS: lock-file + PID check
✔ TTL очистка зависших lock
✔ Авто release при выходе
✔ Без ошибок win32con.ERROR_ALREADY_EXISTS
"""

import os
import time
import atexit
import logging
from pathlib import Path

# ==============================
# Настройки
# ==============================

APP_NAME = "GitAutoSyncRestoreApp"

LOCK_TTL_SECONDS = 3600  # 1 час

logger = logging.getLogger("SingleInstance")
logger.setLevel(logging.INFO)

# ==============================
# psutil (для точной проверки PID)
# ==============================

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil не установлен → PID проверка будет упрощённой")

# ==============================
# pywin32 Mutex (Windows)
# ==============================

WIN32_AVAILABLE = False

if os.name == "nt":
    try:
        import win32event
        import win32api

        WIN32_AVAILABLE = True
    except ImportError:
        logger.warning("pywin32 не установлен → fallback lock-file")


# ==============================
# Вспомогательные функции
# ==============================

def is_our_process(pid: int) -> bool:
    """
    Проверяет, что PID принадлежит именно нашему приложению.
    Через cmdline (если доступно).
    """
    if not PSUTIL_AVAILABLE:
        return True

    try:
        proc = psutil.Process(pid)

        if not proc.is_running():
            return False

        cmdline = " ".join(proc.cmdline()).lower()

        return (
            "gitautosync" in cmdline
            or "restore" in cmdline
            or "main.py" in cmdline
        )

    except psutil.NoSuchProcess:
        return False
    except Exception:
        return False


def is_lock_too_old(lock_path: Path) -> bool:
    """
    Если lock старше TTL → считаем зависшим.
    """
    try:
        age = time.time() - lock_path.stat().st_mtime
        return age > LOCK_TTL_SECONDS
    except Exception:
        return False


# ==============================
# Основной класс SingleInstance
# ==============================

class SingleInstance:
    """
    Надёжная защита от повторного запуска приложения.
    """

    def __init__(self, name: str = APP_NAME):
        self.name = name.strip().replace(" ", "_")

        self.mutex = None

        self.lock_path: Path | None = None
        self.lock_file = None

        self.acquired = False

        atexit.register(self.release)

    # ==============================
    # Захват блокировки
    # ==============================

    def acquire(self) -> bool:
        """
        True → экземпляр первый
        False → уже запущен другой
        """

        if self.acquired:
            return True


        # =====================================================
        # Windows Mutex (самый лучший способ)
        # =====================================================
        if WIN32_AVAILABLE:
            mutex_name = f"Global\\{self.name}_Mutex"

            self.mutex = win32event.CreateMutex(None, False, mutex_name)

            # Код Windows: ERROR_ALREADY_EXISTS = 183
            if win32api.GetLastError() == 183:
                logger.info("Mutex уже существует → другой экземпляр запущен")
                return False

            logger.info("Mutex создан → экземпляр первый")
            self.acquired = True
            return True

        # =====================================================
        # ✅ Lock-file fallback (Linux/macOS)
        # =====================================================

        temp_dir = os.getenv("TEMP") or os.getenv("TMP") or "/tmp"
        self.lock_path = Path(temp_dir) / f"{self.name}.lock"

        # Удаляем старый lock
        if self.lock_path.exists() and is_lock_too_old(self.lock_path):
            logger.warning("Lock слишком старый → удаляем")
            try:
                self.lock_path.unlink()
            except:
                pass

        # Пробуем создать lock
        try:
            self.lock_file = self.lock_path.open("x", encoding="utf-8")
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()

            logger.info("Lock-file создан → экземпляр первый")
            self.acquired = True
            return True

        except FileExistsError:
            # Lock уже существует → проверяем PID
            try:
                pid_text = self.lock_path.read_text().strip()
                pid = int(pid_text)

                if pid and is_our_process(pid):
                    logger.info("Другой экземпляр уже работает")
                    return False

                logger.warning("Lock битый или процесс мёртв → удаляем lock")
                self.lock_path.unlink(missing_ok=True)

                # Повторяем один раз
                return self.acquire()

            except Exception:
                logger.warning("Lock повреждён → удаляем")
                try:
                    self.lock_path.unlink(missing_ok=True)
                except:
                    pass
                return True

        except Exception as e:
            logger.error(f"Ошибка lock-file: {e}")
            return False

    # ==============================
    # Освобождение блокировки
    # ==============================

    def release(self):
        """
        Очистка lock или mutex при завершении приложения.
        """

        if not self.acquired:
            return

        # Windows Mutex release
        if WIN32_AVAILABLE and self.mutex:
            try:
                win32api.CloseHandle(self.mutex)
            except:
                pass
            self.mutex = None

        # Lock-file release
        if self.lock_file:
            try:
                self.lock_file.close()
            except:
                pass
            self.lock_file = None

        if self.lock_path and self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except:
                pass

        self.acquired = False
        logger.info("SingleInstance: освобождение выполнено")
