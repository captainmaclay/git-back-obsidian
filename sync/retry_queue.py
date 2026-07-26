"""
sync/retry_queue.py — фоновая очередь повторных попыток пуша.

Это ОТДЕЛЬНАЯ от update-frequency (debounce) очередь. Запускается на старте программы
и работает так:

- если outbox пуст → ждём RETRY_INTERVAL_SECONDS и проверяем снова
  (новые изменения обрабатывает debounce-очередь — её реализацию не трогаем);
- если outbox непустой (прошлый пуш не удался / есть неотправленные изменения) →
  делаем до RETRY_ATTEMPTS попыток пуша с паузой RETRY_INTERVAL_SECONDS между ними,
  пока не получится (при успехе do_push сам очистит outbox) либо не кончатся попытки;
- если попытки кончились, а изменения остались → ждём интервал и цикл повторяется
  (то есть насовсем ничего не теряется — файл-очередь переживает и перезапуск программы).

do_push уже сериализуется через push_lock, поэтому одновременный пуш с debounce-очередью
невозможен — второй вызов просто пропускается.
"""

import time
import threading

from core.logger import log_main, log_soft
from core.config import RETRY_INTERVAL_SECONDS, RETRY_ATTEMPTS
from sync import outbox

_thread = None
_running = False


def _attempt_push() -> None:
    # Ленивый импорт: do_push при успехе сам вызывает outbox.clear()
    from sync.push import do_push
    do_push()


def _loop() -> None:
    log_main(f"[RETRY-QUEUE] Запущена (интервал {RETRY_INTERVAL_SECONDS} сек, попыток {RETRY_ATTEMPTS})")

    while _running:
        if not outbox.has_pending():
            time.sleep(RETRY_INTERVAL_SECONDS)
            continue

        log_soft(f"[RETRY-QUEUE] Есть отложенные изменения ({outbox.count()}) → пробуем отправить")
        pushed = False

        for attempt in range(1, RETRY_ATTEMPTS + 1):
            if not _running:
                return
            if not outbox.has_pending():
                pushed = True
                break

            log_main(f"[RETRY-QUEUE] Попытка {attempt}/{RETRY_ATTEMPTS}")
            try:
                _attempt_push()
            except Exception as e:
                log_main(f"[RETRY-QUEUE] Ошибка при пуше: {type(e).__name__}: {e}")

            if not outbox.has_pending():
                pushed = True
                log_main("[RETRY-QUEUE] Успех — очередь очищена")
                break

            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_INTERVAL_SECONDS)

        if not pushed:
            log_main(f"[RETRY-QUEUE] Попытки исчерпаны ({RETRY_ATTEMPTS}) — "
                     f"ждём {RETRY_INTERVAL_SECONDS} сек и повторим (изменения сохранены)")
            time.sleep(RETRY_INTERVAL_SECONDS)


def start_retry_queue() -> None:
    global _thread, _running
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="retry-queue")
    _thread.start()


def stop_retry_queue() -> None:
    global _running
    _running = False
