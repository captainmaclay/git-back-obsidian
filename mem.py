"""
mem.py — Контроль размера лог-файлов

✔ Следит за logger.txt / logger_clean.txt / loggerm.txt
✔ Если файл > 600 KB → удаляет старые строки сверху
✔ Оставляет примерно 400 KB
✔ Безопасная перезапись через временный файл
"""

import os
from pathlib import Path


# ============================
# Настройки диапазона
# ============================

MAX_SIZE_KB = 600   # если файл больше → чистим
TARGET_SIZE_KB = 400  # после чистки оставляем примерно столько

LOG_FILES = [
    "logger.txt",
    "logger_clean.txt",
    "loggerm.txt",
]


# ============================
# Основная функция очистки
# ============================

def trim_log_file(path: Path):
    """
    Обрезает лог сверху, если он слишком большой.
    """

    if not path.exists():
        print(f"[SKIP] Нет файла: {path.name}")
        return

    size_kb = path.stat().st_size / 1024

    # Если файл маленький — ничего не делаем
    if size_kb <= MAX_SIZE_KB:
        print(f"[OK] {path.name}: {int(size_kb)} KB")
        return

    print(f"[TRIM] {path.name}: {int(size_kb)} KB → чистим...")

    try:
        # Читаем все строки
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # Если файл пустой
        if not lines:
            return

        # Будем оставлять строки с конца
        kept_lines = []
        current_size = 0

        # Идём снизу вверх
        for line in reversed(lines):
            line_size = len(line.encode("utf-8"))

            if current_size + line_size > TARGET_SIZE_KB * 1024:
                break

            kept_lines.append(line)
            current_size += line_size

        # Возвращаем нормальный порядок строк
        kept_lines.reverse()

        # Запись через временный файл
        temp_path = path.with_suffix(".tmp")

        with open(temp_path, "w", encoding="utf-8") as f:
            f.writelines(kept_lines)

        # Заменяем оригинал
        os.replace(temp_path, path)

        new_size_kb = path.stat().st_size / 1024
        print(f"[DONE] {path.name} → теперь {int(new_size_kb)} KB")

    except Exception as e:
        print(f"[ERROR] Ошибка очистки {path.name}: {e}")


# ============================
# Запуск проверки всех файлов
# ============================

def main():
    folder = Path(__file__).parent

    print("=== LOG MEMORY CONTROL START ===")


    for filename in LOG_FILES:
        trim_log_file(folder / filename)

    print("=== DONE ===")

if __name__ == "__main__":
    main()


