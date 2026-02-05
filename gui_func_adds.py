"""
Вспомогательные функции для GUI: трей-иконка, обработка закрытия окна, кнопка Exit, всплывашка
"""
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox
import pystray
from PIL import Image, ImageDraw
import threading
from pathlib import Path
import time

from app_logger import log_main, log_soft, log_both, get_logger


def create_tray_icon():
    image = Image.new("RGB", (64, 64), "blue")
    dc = ImageDraw.Draw(image)
    dc.rectangle((0, 0, 64, 64), fill="blue")
    return image


def setup_tray_and_close_protocol(
    root: tk.Tk,
    stop_watcher,
    defense_instance,
    app_instance,
    hide_method_name="hide_to_tray",
    stop_tray_method_name="_stop_tray_icon"
):
    """
    Настраивает трей и протокол закрытия.
    Теперь quit_app_func сначала сворачивает в трей, а потом закрывает.
    """
    def on_close():
        # При обычном закрытии окна (крестик) — просто в трей
        getattr(app_instance, hide_method_name)()
        log_both("Закрытие окна → сворачивание в трей")

    root.protocol("WM_DELETE_WINDOW", on_close)
    log_soft("Протокол закрытия окна настроен (WM_DELETE_WINDOW → hide to tray)")

    def quit_app_func():
        log_main("Запущен полный выход из программы (quit_app_func)")

        # 1. Сначала сворачиваем в трей (визуальный отклик)
        try:
            getattr(app_instance, hide_method_name)()
            log_soft("Принудительно свернули в трей перед выходом")
            time.sleep(0.4)  # небольшой визуальный лаг, чтобы пользователь увидел
        except Exception as e:
            log_main(f"Не удалось свернуть в трей перед выходом: {e}")

        # 2. Теперь настоящая остановка
        try:
            stop_watcher()
            log_soft("Watcher остановлен")
        except Exception as e:
            log_main(f"Ошибка остановки watcher: {e}")

        try:
            logger = get_logger()
            if hasattr(logger, 'stop'):
                logger.stop()
                log_soft("Логгер остановлен")
        except Exception as e:
            log_main(f"Ошибка остановки логгера: {e}")

        if defense_instance:
            try:
                defense_instance.release()
                log_soft("SingleInstance: release выполнен")
            except Exception as e:
                log_main(f"Ошибка release single-instance: {e}")

        getattr(app_instance, stop_tray_method_name)()

        try:
            root.destroy()
        except Exception as e:
            log_main(f"Ошибка root.destroy: {e}")

        log_both("Программа завершена полностью")
        sys.exit(0)

    # Возвращаем две функции:
    #   - hide_to_tray (для сворачивания)
    #   - quit_app_func (для полного выхода — теперь с предварительным hide)
    return getattr(app_instance, hide_method_name), quit_app_func


def create_exit_button(switch_frame, quit_app_func, minecraft_font="Consolas"):
    def confirm_exit():
        if messagebox.askyesno("Выход", "Выйти из программы полностью?\n(сначала свернётся в трей)", icon="question"):
            log_main("Пользователь подтвердил полный выход")
            quit_app_func()   # ← теперь это функция, которая сначала hide → потом destroy

    exit_button = tk.Button(
        switch_frame,
        text="Exit",
        font=(minecraft_font, 10, "bold"),
        bg="#2E7D32",
        fg="white",
        activebackground="#1B5E20",
        activeforeground="white",
        width=6,
        relief="raised",
        bd=2,
        command=confirm_exit
    )
    exit_button.pack(side=tk.RIGHT, padx=8, pady=4)
    log_soft("Кнопка Exit создана")
    return exit_button


def show_duplicate_warning(block=True):
    try:
        root = tk.Tk()
        root.withdraw()

        notif = tk.Toplevel(root)
        notif.overrideredirect(True)
        notif.attributes("-topmost", True)
        notif.attributes("-alpha", 0.95)

        bg_color = "#2d3748"
        fg_color = "#e2e8f0"
        border_color = "#4a5568"

        frame = tk.Frame(notif, bg=bg_color, bd=1, relief="solid",
                         highlightbackground=border_color, highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        try:
            font = tkfont.Font(family="Minecraftia", size=12)
        except tk.TclError:
            font = tkfont.Font(family="Consolas", size=12)


        label = tk.Label(
            frame,
            text="Git Back уже запущен.\nПосмотрите в трее или в Диспетчере задач",
            bg=bg_color,
            fg=fg_color,
            font=font,
            padx=25,
            pady=15,
            justify="center"
        )
        label.pack()

        notif.update_idletasks()
        width = notif.winfo_reqwidth()
        height = notif.winfo_reqheight()
        x = (notif.winfo_screenwidth() // 2) - (width // 2)
        y = (notif.winfo_screenheight() // 2) - (height // 2) - 80
        notif.geometry(f"+{x}+{y}")

        def close_and_exit():
            notif.destroy()
            root.destroy()
            if block:
                sys.exit(0)

        notif.after(5000, close_and_exit)

        log_main("Показана всплывашка о дубле")
        root.mainloop()
    except Exception as e:
        log_main(f"Не удалось показать всплывашку: {e}")
        if block:
            sys.exit(0)

