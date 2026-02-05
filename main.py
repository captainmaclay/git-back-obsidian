"""
Git Autosync & Version Restore — основной скрипт приложения

✔ Один экземпляр на систему
✔ Второй запуск → предупреждение → выход
✔ Надёжная защита через Mutex (Windows) и lock+psutil (Linux/macOS)
✔ Автоочистка логов через mem.py при каждом запуске
"""

import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path

# Подготовка структуры файлов и папок (самое первое действие)
import require_utils

import config
from app_logger import init_logger, log_both, log_main
from gui_watcher import start_watcher, stop_watcher, initial_check_loop
from observer_manager import stop_observer
from gui_func_adds import show_duplicate_warning


# Single-instance защита
from defense import SingleInstance

# GUI импорт
try:
    from gui import GitVersionRestoreApp
except ImportError as e:
    print(f"[GUI] GUI модуль не найден: {e}")
    GitVersionRestoreApp = None


# ==============================
# .env автосоздание
# ==============================

ENV_FILE = Path(__file__).parent / ".env"


def ensure_env_file():
    """
    Создаёт или дополняет .env файл необходимыми переменными.
    Не перезаписывает существующие значения.
    """
    default_env = {
        "GITHUB_USERNAME": "rollexpollex-hash",
        "GITHUB_REPO": "obsidian",
        "GITHUB_TOKEN": "",
    }

    existing = {}

    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        existing[key.strip()] = value.strip().strip('"')
        except Exception as e:
            print(f"[ENV] Ошибка чтения .env: {e}")

    missing = [k for k in default_env if k not in existing]

    if missing or not ENV_FILE.exists():
        print("[ENV] Обнаружены отсутствующие ключи или файла нет → дополняем/создаём .env")

        mode = "w" if not ENV_FILE.exists() else "a"

        with open(ENV_FILE, mode, encoding="utf-8") as f:
            if mode == "w":
                f.write("# Автоматически созданный .env файл\n")
                f.write("# Заполните значения и перезапустите приложение\n\n")

            for key in missing:
                comment = ""
                if key == "GITHUB_TOKEN":
                    comment = "  # ← Получите токен: https://github.com/settings/tokens"
                f.write(f'{key}="{default_env[key]}"{comment}\n')

        print(f"[ENV] .env обновлён/создан: {ENV_FILE}")


# ==============================
# Фоновое наблюдение
# ==============================

def start_observation():
    """Фоновый запуск watcher и периодических проверок"""
    log_main("[observation] Запуск фоновых процессов...")

    start_watcher()
    threading.Thread(target=initial_check_loop, daemon=True).start()

    log_main("[observation] Фоновые процессы запущены")


# ==============================
# MAIN
# ==============================

def main():
    # 1. Подготовка структуры уже выполнена через import require_util

    # 2. Создаём/дополняем .env
    ensure_env_file()

    # 3. Single Instance защита
    instance = SingleInstance("GitAutoSyncRestoreApp")

    if not instance.acquire():
        print("[MAIN] Другой экземпляр уже запущен → выход")
        show_duplicate_warning(block=True)
        sys.exit(0)

    # 4. Очистка/проверка логов через mem.py
    try:
        import mem
        mem.main()
        print("[MEM] Логи проверены и очищены при необходимости")
    except ImportError:
        print("[MEM] Модуль mem.py не найден — пропускаем очистку логов")
    except Exception as e:
        print(f"[MEM] Ошибка при проверке/очистке логов: {e}")

    # 5. Инициализация логгера
    try:
        init_logger()
        time.sleep(0.1)  # небольшой запас на инициализацию
        log_both("===== ЗАПУСК Git Autosync & Version Restore =====")
        log_both("[logger] Логгер успешно инициализирован")
    except Exception as e:
        print(f"[CRITICAL] Не удалось инициализировать логгер: {e}")
        sys.exit(1)

    # 6. Создание GUI
    root = tk.Tk()

    app = None
    if GitVersionRestoreApp:
        try:
            app = GitVersionRestoreApp(root)
            log_both("[GUI] Интерфейс успешно создан")
        except Exception:
            log_main("[GUI] Ошибка создания интерфейса:\n" + traceback.format_exc())
            app = None
    else:
        log_main("[GUI] gui.py не импортирован")

    if not app:
        log_main("[GUI] Интерфейс не запущен → работа в фоновом режиме")

    # 7. Запуск фонового наблюдателя
    threading.Thread(target=start_observation, daemon=True).start()

    # 8. Главный цикл Tkinter
    log_both("[MAIN] Входим в Tkinter mainloop...")

    try:
        root.mainloop()

    except KeyboardInterrupt:
        log_both("[MAIN] Ctrl+C → graceful shutdown")

    except Exception:
        log_main("[CRITICAL] Критическая ошибка в mainloop:\n" + traceback.format_exc())

    finally:
        log_both("[MAIN] Завершение приложения → остановка процессов...")

        stop_watcher()
        stop_observer()

        log_both("===== ПРИЛОЖЕНИЕ ЗАВЕРШЕНО =====")


# ==============================
# ENTRY POINT
# ==============================

if __name__ == "__main__":
    main()
