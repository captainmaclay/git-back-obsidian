"""
app_logger.py — надёжный логгер с выводом в консоль + файлы + GUI (опционально)
Консольный вывод сохраняется всегда, даже при запуске GUI.
"""

import sys
import time
import queue
import threading
import os
import logging

class AppLogger:
    def __init__(self):
        self.running = True
        self.q = queue.Queue(maxsize=5000)

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.file_main  = os.path.join(BASE_DIR, "logger.txt")
        self.file_soft  = os.path.join(BASE_DIR, "loggerm.txt")
        self.file_debug = os.path.join(BASE_DIR, "syslog.txt")


        # Отладка создания логгера (только один раз)
        print("Логгер создан. Файлы будут в папке:", BASE_DIR)
        print("  → Основные:     ", self.file_main)
        print("  → Soft:         ", self.file_soft)
        print("  → Debug:        ", self.file_debug)


        # Настраиваем стандартный logging
        self.logger = logging.getLogger('app')
        self.logger.setLevel(logging.INFO)

        formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

        # 1. Всегда консоль (используем sys.__stdout__ — оригинальный, не перехваченный GUI)
        console_handler = logging.StreamHandler(sys.__stdout__)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)

        # 2. Файловые handlers
        main_handler = logging.FileHandler(self.file_main, encoding='utf-8')
        main_handler.setFormatter(formatter)
        self.logger.addHandler(main_handler)

        soft_handler = logging.FileHandler(self.file_soft, encoding='utf-8')
        soft_handler.setFormatter(formatter)
        soft_logger = logging.getLogger('soft')
        soft_logger.setLevel(logging.INFO)
        soft_logger.addHandler(soft_handler)

        debug_handler = logging.FileHandler(self.file_debug, encoding='utf-8')
        debug_handler.setFormatter(formatter)
        debug_logger = logging.getLogger('debug')
        debug_logger.setLevel(logging.DEBUG)
        debug_logger.addHandler(debug_handler)

        # Коллбеки для GUI (будут установлены позже)
        self.callback_main = None
        self.callback_soft = None
        self.callback_debug = None

        # Поток-обработчик очереди (для GUI-коллбеков и файлов)
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def _worker(self):
        while self.running or not self.q.empty():
            try:
                msg, log_type = self.q.get(timeout=0.4)
                line = msg.strip() + "\n"

                # Вывод в GUI через коллбеки
                if log_type in ("main", "both") and self.callback_main:
                    try:
                        self.callback_main(line)
                    except Exception as e:
                        print(f"Callback main error: {e}", file=sys.__stderr__)

                if log_type in ("soft", "both") and self.callback_soft:
                    try:
                        self.callback_soft(line)
                    except Exception as e:
                        print(f"Callback soft error: {e}", file=sys.__stderr__)

                if log_type == "debug" and self.callback_debug:
                    try:
                        self.callback_debug(line)
                    except Exception as e:
                        print(f"Callback debug error: {e}", file=sys.__stderr__)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"Logger worker error: {e}", file=sys.__stderr__)

    def log(self, msg: str, log_type: str = "main"):
        if not msg or not msg.strip():
            return
        if log_type not in ("main", "soft", "debug", "both"):
            log_type = "main"

        # Основной вывод через logging (консоль + файлы)
        if log_type == "main" or log_type == "both":
            self.logger.info(msg)
        elif log_type == "soft":
            logging.getLogger('soft').info(msg)
        elif log_type == "debug":
            logging.getLogger('debug').debug(msg)

        # Дополнительно кладём в очередь только для GUI-коллбеков
        try:
            self.q.put_nowait((msg, log_type))
        except queue.Full:
            print("[LOGGER FULL] Очередь переполнена, GUI не получит сообщение:", msg, file=sys.__stderr__)

    def set_callbacks(self, main=None, soft=None, debug=None):
        """Устанавливает коллбеки для GUI"""
        self.callback_main  = main
        self.callback_soft  = soft
        self.callback_debug = debug

    def stop(self):
        self.running = False
        try:
            self.worker.join(timeout=1.5)
        except:
            pass


# ────────────────────────────────────────────────
# Синглтон + защита от вызова до инициализации
# ────────────────────────────────────────────────

_logger_instance = None


def init_logger():
    """Вызвать ОДИН РАЗ в главном файле (main.py) в самом начале"""
    global _logger_instance
    if _logger_instance is not None:
        return _logger_instance
    _logger_instance = AppLogger()
    return _logger_instance


def get_logger():
    """Получить экземпляр логгера (после init_logger)"""
    global _logger_instance
    if _logger_instance is None:
        class FakeLogger:
            def log(self, msg, log_type="main"):
                print(f"[{log_type.upper()}] {msg}", file=sys.stderr)
            def set_callbacks(self, *args, **kwargs):
                pass
            def stop(self):
                pass
        return FakeLogger()
    return _logger_instance


def log_main(msg: str):
    get_logger().log(msg, "main")


def log_soft(msg: str):
    get_logger().log(msg, "soft")


def log_debug(msg: str):
    get_logger().log(msg, "debug")


def log_both(msg: str):
    get_logger().log(msg, "both")
