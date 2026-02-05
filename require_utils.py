# require_utils.py
"""
Утилита для подготовки необходимой структуры файлов и папок приложения.
Вызывается один раз при старте main.py.
"""

import os
from pathlib import Path
import configparser
import sys

# Определяем базовую директорию приложения (там, где лежит main.py)
try:
    # Если нас импортировали из main.py
    BASE_DIR = Path(sys.modules['__main__'].__file__).parent.resolve()
except (KeyError, AttributeError):
    # Запуск напрямую (для тестов)
    BASE_DIR = Path(__file__).parent.resolve()

# Пути, которые нужно создать/проверить
FAKE_GIT_TEMP = BASE_DIR / "fake_git_temp"
VERSIONS_DIR   = BASE_DIR / "Versions"
SETTINGS_FILE  = BASE_DIR / "settings.ini"
LOGGER_FILE    = BASE_DIR / "logger.txt"
LOGGERM_FILE   = BASE_DIR / "loggerm.txt"
ENV_FILE       = BASE_DIR / ".env"  # добавили путь к .env


def ensure_directories():
    """Создаёт необходимые папки, если их нет"""
    dirs_to_create = [
        (FAKE_GIT_TEMP, "fake_git_temp"),
        (VERSIONS_DIR,   "Versions"),
    ]
    for path, name in dirs_to_create:
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                print(f"[require] Создана папка: {name}")
            except Exception as e:
                print(f"[require] Ошибка создания папки {name}: {e}")


def ensure_log_files():
    """Создаёт пустые файлы логов, если их нет"""
    log_files = [
        (LOGGER_FILE,  "logger.txt"),
        (LOGGERM_FILE, "loggerm.txt"),
    ]

    for path, name in log_files:
        if not path.exists():
            try:
                path.touch()
                print(f"[require] Создан файл лога: {name}")
            except Exception as e:
                print(f"[require] Ошибка создания {name}: {e}")


def ensure_settings_ini():
    """Создаёт settings.ini с дефолтными значениями, если файла нет"""
    if SETTINGS_FILE.exists():
        return

    try:
        config = configparser.ConfigParser()
        config['Settings'] = {
            'start_minimized': 'false',
        }

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

        print(f"[require] Создан файл конфигурации: settings.ini")
    except Exception as e:
        print(f"[require] Ошибка создания settings.ini: {e}")


def ensure_env_file():
    """Создаёт .env с шаблоном, если файла нет"""
    if ENV_FILE.exists():
        return

    try:
        content = (
            'GITHUB_USERNAME=""\n'
            'GITHUB_REPO=""\n'
            'GITHUB_TOKEN=""\n'
            'WATCHED_FOLDER=""\n'
            'DEBOUNCE_MINUTES=""\n'
        )
        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.write(content)

        print("[require] Создан файл окружения: .env")
    except Exception as e:
        print(f"[require] Ошибка создания .env: {e}")


def initialize_app_structure():
    """
    Главная функция — вызывается один раз при старте приложения.
    Выполняет все проверки и создания.
    """
    print("[require] Проверка и подготовка структуры приложения...")

    ensure_directories()
    ensure_log_files()
    ensure_settings_ini()
    ensure_env_file()  # добавили вызов

    print("[require] Подготовка структуры завершена")


# Автоматический запуск при импорте модуля
if __name__ != "__main__":
    initialize_app_structure()
else:
    # Для ручного тестирования
    print("Тестовый запуск require_util.py")
    initialize_app_structure()
