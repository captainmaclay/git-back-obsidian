"""
observer_manager.py

Централизованное управление watchdog-observer'ом.
Все вызовы start/stop/проверки состояния observer идут только через этот модуль.
"""

from threading import Lock
from watchdog.observers import Observer
from config import WATCHED_FOLDER
from app_logger import log_main, log_soft

# Импорт ChangeHandler делаем ЛОКАЛЬНО внутри функции,
# чтобы избежать циклического импорта при загрузке модуля
# (gui_watcher импортирует observer_manager, а не наоборот)

observer: Observer | None = None
observer_lock = Lock()


def start_observer():
    """
    Запускает observer, если он не запущен.
    Импорт ChangeHandler происходит только в момент первого запуска.
    """
    global observer
    with observer_lock:
        if observer is not None and observer.is_alive():
            log_soft("[observer_manager] Observer уже запущен — пропуск")
            return

        try:
            # Импорт здесь — безопасно, gui_watcher уже загружен к моменту вызова
            from gui_watcher import ChangeHandler

            observer = Observer()
            observer.schedule(ChangeHandler(), str(WATCHED_FOLDER), recursive=True)
            observer.start()
            log_main("[observer_manager] Наблюдатель успешно запущен")
            log_soft(f"[observer_manager] Папка наблюдения: {WATCHED_FOLDER}")
        except Exception as e:
            log_main(f"[observer_manager] Ошибка при запуске observer: {e}")
            observer = None


def stop_observer():
    """Останавливает observer, если он запущен."""
    global observer
    with observer_lock:
        if observer is None or not observer.is_alive():
            log_soft("[observer_manager] Observer уже остановлен или не запущен")
            return

        try:
            log_main("[observer_manager] Остановка наблюдателя...")
            observer.stop()
            observer.join(timeout=5.0)
            if observer.is_alive():
                log_main("[observer_manager] WARNING: Observer не остановился за 5 сек")
        except Exception as e:
            log_main(f"[observer_manager] Ошибка при остановке observer: {e}")
        finally:
            observer = None
            log_soft("[observer_manager] Observer остановлен")

def is_observer_running() -> bool:
    """Проверяет, активен ли observer в данный момент."""
    with observer_lock:
        return observer is not None and observer.is_alive()

def restart_observer():
    """Удобная комбинация: stop → start."""
    stop_observer()
    start_observer()
    log_soft("[observer_manager] Observer принудительно перезапущен")

