"""
Центральный конфигурационный файл проекта.
Все пути, токены, константы и глобальные переменные — здесь.
"""

from pathlib import Path
import os
import sys
from typing import Union
import dotenv
from dataclasses import dataclass

from core.logger import log_main, log_soft, log_both


# ────────────────────────────────────────────────────────────────
# Базовые пути проекта
# ────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parents[1]  # корень проекта (на уровень выше core/)

# Временные / служебные директории (всегда создаются рядом со скриптом)

REPO_PATH = SCRIPT_DIR / "Autosync_git"
REPO_PATH.mkdir(parents=True, exist_ok=True)

FAKE_PUSH_GIT = SCRIPT_DIR / "fake_git_temp"
FAKE_PUSH_GIT.mkdir(parents=True, exist_ok=True)

GIT_DIR = FAKE_PUSH_GIT

DELETED_TEMP = FAKE_PUSH_GIT / "deleted_temp"
DELETED_TEMP.mkdir(parents=True, exist_ok=True)

VERSIONS_DIR = SCRIPT_DIR / "Versions"
VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


# ────────────────────────────────────────────────────────────────
# Загрузка .env
# ────────────────────────────────────────────────────────────────

dotenv.load_dotenv()   # загружаем .env из текущей директории

GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "").strip('"')
GITHUB_REPO     = os.getenv("GITHUB_REPO",     "").strip('"')
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN",    "").strip('"')

# WATCHED_FOLDER — теперь берём из .env, если есть, иначе дефолт
watched_default = r""
WATCHED_FOLDER_STR = os.getenv("WATCHED_FOLDER", watched_default).strip('"')
WATCHED_FOLDER = Path(WATCHED_FOLDER_STR)
GITHUB_REPO_URL    = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}.git"
GITHUB_PROFILE_URL = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}"


def is_github_configured() -> bool:
    """
    True, если заданы логин, репозиторий и токен GitHub.
    Используется как предохранитель: без этих значений любые обращения к API
    уходят в /repos/// → 404, а pygit2 падает с 'failed to set credentials'.
    """
    return bool(GITHUB_USERNAME and GITHUB_REPO and GITHUB_TOKEN)


# Проверяем и создаём, если возможно
try:
    WATCHED_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception as e:
    log_main(f"[CONFIG] Не удалось создать/доступ к WATCHED_FOLDER: {e}")
    log_main(f"          Используется значение по умолчанию, но может не работать")
    WATCHED_FOLDER = Path(watched_default)
    WATCHED_FOLDER.mkdir(parents=True, exist_ok=True)


# ────────────────────────────────────────────────────────────────
# Debounce — поддержка минут и секунд
# ────────────────────────────────────────────────────────────────

# По умолчанию — 10 секунд (старое поведение)
DEFAULT_DEBOUNCE_SECONDS = 10

# Пытаемся прочитать DEBOUNCE_MINUTES из .env
debounce_minutes_str = os.getenv("DEBOUNCE_MINUTES", "").strip()

if debounce_minutes_str:
    try:
        minutes = float(debounce_minutes_str)
        if minutes > 0:
            DEBOUNCE_SECONDS = int(minutes * 60)
            log_soft(f"[CONFIG] Debounce задан в минутах: {minutes} мин → {DEBOUNCE_SECONDS} сек")
        else:
            DEBOUNCE_SECONDS = DEFAULT_DEBOUNCE_SECONDS
            log_main(f"[CONFIG] DEBOUNCE_MINUTES ≤ 0 → используется значение по умолчанию {DEBOUNCE_SECONDS} сек")
    except (ValueError, TypeError):
        log_main(f"[CONFIG] Некорректное значение DEBOUNCE_MINUTES='{debounce_minutes_str}' → используется {DEFAULT_DEBOUNCE_SECONDS} сек")
        DEBOUNCE_SECONDS = DEFAULT_DEBOUNCE_SECONDS
else:
    # Если DEBOUNCE_MINUTES не задан — смотрим старый DEBOUNCE_SECONDS
    DEBOUNCE_SECONDS = int(os.getenv("DEBOUNCE_SECONDS", DEFAULT_DEBOUNCE_SECONDS))
    log_soft(f"[CONFIG] DEBOUNCE_SECONDS = {DEBOUNCE_SECONDS} сек (из .env или по умолчанию)")


# ────────────────────────────────────────────────────────────────
# Retry-очередь отложенных пушей (outbox)
# ────────────────────────────────────────────────────────────────

# Интервал повторных попыток пуша, пока есть неотправленные изменения (минуты)
DEFAULT_RETRY_INTERVAL_MINUTES = 1.5
try:
    _retry_min = float((os.getenv("RETRY_INTERVAL_MINUTES", "").strip() or DEFAULT_RETRY_INTERVAL_MINUTES))
    RETRY_INTERVAL_SECONDS = int(_retry_min * 60) if _retry_min > 0 else int(DEFAULT_RETRY_INTERVAL_MINUTES * 60)
except (ValueError, TypeError):
    RETRY_INTERVAL_SECONDS = int(DEFAULT_RETRY_INTERVAL_MINUTES * 60)

# Сколько попыток подряд делать в одном цикле retry (по умолчанию 2)
DEFAULT_RETRY_ATTEMPTS = 2
try:
    RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "").strip() or DEFAULT_RETRY_ATTEMPTS)
    if RETRY_ATTEMPTS < 1:
        RETRY_ATTEMPTS = DEFAULT_RETRY_ATTEMPTS
except (ValueError, TypeError):
    RETRY_ATTEMPTS = DEFAULT_RETRY_ATTEMPTS

# ── Что пушим: флаг папок (в .env) + расширения файлов (в txt-файле) ────────────

# Реагировать ли на события ПАПОК (создание/удаление/переименование).
# Галочка в Settings → сохраняется в .env. По умолчанию включено.
TRACK_FOLDERS = os.getenv("TRACK_FOLDERS", "true").strip().lower() not in ("0", "false", "no", "off", "")

# Отслеживаемые расширения файлов хранятся в отдельном txt (по одному на строке),
# редактируется кнопкой «+» в Settings. По умолчанию — одна строка: md.
EXTENSIONS_FILE = SCRIPT_DIR / "push_extensions.txt"

_DEFAULT_EXTENSIONS_TXT = (
    "# write the file extension on a new line\n"
    "# пиши расширение файла с новой строки\n"
    "md\n"
)


def ensure_extensions_file() -> None:
    """Создаёт push_extensions.txt со значением по умолчанию, если его нет."""
    try:
        if not EXTENSIONS_FILE.exists():
            EXTENSIONS_FILE.write_text(_DEFAULT_EXTENSIONS_TXT, encoding="utf-8")
    except Exception as e:
        log_main(f"[CONFIG] Не удалось создать {EXTENSIONS_FILE.name}: {e}")


def _parse_extensions(text: str) -> tuple:
    """
    Парсит push_extensions.txt терпимо к «грязи»:
    - пустые строки и строки из одних пробелов игнорируются;
    - строки-комментарии (начинаются с #) игнорируются;
    - у строки берётся ТОЛЬКО первое слово (пробелы/хвост после расширения не мешают);
    - ведущие/хвостовые точки и регистр нормализуются: 'MD', '.md', ' md  x' → '.md'.
    """
    exts = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        token = line.split()[0].strip().lower().strip(".")  # первое слово, без точек/пробелов
        if not token:
            continue
        ext = "." + token
        if ext not in exts:
            exts.append(ext)
    return tuple(exts) or (".md",)


# Кэш с проверкой mtime: правки txt подхватываются без перезапуска приложения.
_ext_cache = {"mtime": None, "value": (".md",)}


def get_tracked_extensions() -> tuple:
    """Актуальные отслеживаемые расширения (перечитывает txt при изменении файла)."""
    ensure_extensions_file()
    try:
        mtime = EXTENSIONS_FILE.stat().st_mtime
        if _ext_cache["mtime"] != mtime:
            _ext_cache["value"] = _parse_extensions(EXTENSIONS_FILE.read_text(encoding="utf-8"))
            _ext_cache["mtime"] = mtime
    except Exception:
        pass
    return _ext_cache["value"]


ensure_extensions_file()
TRACKED_EXTENSIONS = get_tracked_extensions()   # снимок на старте (для констант-потребителей)

# Файл-очередь отложенных изменений — чистится ТОЛЬКО после успешного пуша
PENDING_CHANGES_FILE = SCRIPT_DIR / "pending_changes.json"

log_soft(f"[CONFIG] RETRY: интервал {RETRY_INTERVAL_SECONDS} сек, попыток {RETRY_ATTEMPTS}; "
         f"папки: {'вкл' if TRACK_FOLDERS else 'выкл'}; расширения: {TRACKED_EXTENSIONS}")

# ────────────────────────────────────────────────────────────────
# Debounce таймер и блокировка
# ────────────────────────────────────────────────────────────────

debounce_timer = None
push_lock = False

# ────────────────────────────────────────────────────────────────
# Игнорируемые директории
# ────────────────────────────────────────────────────────────────

IGNORED_DIRS = {
    ".obsidian",
    ".vscode",
    "__pycache__",
    ".git",
    "deleted",
    "deleted_temp",
    "push_comments",
}


# ────────────────────────────────────────────────────────────────
# Пути git-файлов и служебных папок
# ────────────────────────────────────────────────────────────────

GITIGNORE_PATH    = REPO_PATH / ".gitignore"
GITATTRIBUTES_PATH = REPO_PATH / ".gitattributes"

DELETED_DIR       = REPO_PATH / "deleted"
PUSH_COMMENTS_DIR = SCRIPT_DIR / "push_comments"

for path in [DELETED_DIR, PUSH_COMMENTS_DIR]:
    path.mkdir(parents=True, exist_ok=True)


# ────────────────────────────────────────────────────────────────
# Логи
# ────────────────────────────────────────────────────────────────

LOG_FILE        = SCRIPT_DIR / "logger.txt"
SOFTLOGGER_FILE = SCRIPT_DIR / "loggerm.txt"
COM_LOG_FILE    = SCRIPT_DIR / "comlogger.txt"


# ────────────────────────────────────────────────────────────────
# Lazy imports
# ────────────────────────────────────────────────────────────────

_parser = None
_cleaner = None


def get_parser_logger():
    global _parser
    if _parser is None:
        try:
            from sync.commit_description import parse_diff_lines
            _parser = parse_diff_lines
        except ImportError:
            def dummy_parse(*args, **kwargs):
                return []
            _parser = dummy_parse
    return _parser


def get_run_logger_clean():
    global _cleaner
    if _cleaner is None:
        try:
            from sync.commit_description import run_logger_clean
            _cleaner = run_logger_clean
        except ImportError:
            _cleaner = lambda: None
    return _cleaner


parser_logger = get_parser_logger
run_logger_clean = get_run_logger_clean


# ────────────────────────────────────────────────────────────────
# Settings объект (для GUI и других модулей)
# ────────────────────────────────────────────────────────────────

@dataclass
class Settings:
    watched_folder: Path
    repo_path: Path

    github_username: str
    github_repo: str
    github_token: str

    debounce_seconds: int

    log_file: Path
    softlogger_file: Path
    com_log_file: Path


# Создаём глобальный объект настроек
settings = Settings(
    watched_folder=WATCHED_FOLDER,
    repo_path=REPO_PATH,

    github_username=GITHUB_USERNAME,
    github_repo=GITHUB_REPO,
    github_token=GITHUB_TOKEN,

    debounce_seconds=DEBOUNCE_SECONDS,

    log_file=LOG_FILE,
    softlogger_file=SOFTLOGGER_FILE,
    com_log_file=COM_LOG_FILE,
)

# ────────────────────────────────────────────────────────────────
# Функция сохранения новой папки наблюдения в .env
# ────────────────────────────────────────────────────────────────

def save_watched_folder(new_path: Union[str, Path]) -> bool:
    """
    Сохраняет новую папку наблюдения в .env
    Возвращает True при успехе, False при ошибке
    """
    global WATCHED_FOLDER, settings

    new_path = Path(new_path).resolve()

    if not new_path.exists():
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log_main(f"[CONFIG] Не удалось создать папку {new_path}: {e}")
            return False

    if not os.access(new_path, os.W_OK):
        log_main(f"[CONFIG] Нет прав на запись в {new_path}")
        return False

    env_path = SCRIPT_DIR / ".env"

    lines = []
    found = False

    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_line = f'WATCHED_FOLDER="{new_path.as_posix()}"\n'

    for i, line in enumerate(lines):
        if line.strip().startswith("WATCHED_FOLDER="):
            lines[i] = new_line
            found = True
            break

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        WATCHED_FOLDER = new_path
        settings.watched_folder = new_path

        log_main(f"[CONFIG] WATCHED_FOLDER обновлён → {new_path}")
        log_soft("Папка наблюдения успешно сохранена в .env")
        return True

    except Exception as e:
        log_main(f"[CONFIG] Ошибка записи .env: {e}")
        return False


# ────────────────────────────────────────────────────────────────
# Проверка конфигурации при импорте
# ────────────────────────────────────────────────────────────────

def _validate_config():
    log_both("═" * 70)
    log_both("Конфигурация загружена успешно")
    log_both(f"GITHUB_USERNAME     : {settings.github_username}")
    log_both(f"GITHUB_REPO          : {settings.github_repo}")
    log_both(f"Token length         : {len(settings.github_token)}")
    log_both(f"WATCHED_FOLDER       : {settings.watched_folder}")
    log_both(f"REPO_PATH            : {settings.repo_path}")
    log_both(f"DEBOUNCE_SECONDS     : {settings.debounce_seconds} сек")
    if os.getenv("DEBOUNCE_MINUTES"):
        log_both(f"  (задано через DEBOUNCE_MINUTES)")
    log_both("═" * 70)


_validate_config()


# ────────────────────────────────────────────────────────────────
# Экспорт
# ────────────────────────────────────────────────────────────────

__all__ = [
    "SCRIPT_DIR",
    "WATCHED_FOLDER",
    "REPO_PATH",
    "FAKE_PUSH_GIT",
    "GIT_DIR",
    "VERSIONS_DIR",
    "DELETED_TEMP",
    "IGNORED_DIRS",
    "GITHUB_USERNAME",
    "GITHUB_REPO",
    "GITHUB_TOKEN",
    "GITHUB_REPO_URL",
    "GITHUB_PROFILE_URL",
    "is_github_configured",
    "RETRY_INTERVAL_SECONDS",
    "RETRY_ATTEMPTS",
    "TRACKED_EXTENSIONS",
    "get_tracked_extensions",
    "ensure_extensions_file",
    "EXTENSIONS_FILE",
    "TRACK_FOLDERS",
    "PENDING_CHANGES_FILE",
    "DEBOUNCE_SECONDS",
    "debounce_timer",
    "push_lock",
    "settings",
    "save_watched_folder",
    "parser_logger",
    "run_logger_clean",
]