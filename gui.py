# gui.py — основной GUI-интерфейс приложения GitHub Auto-Sync & Version Restore

import time
import configparser
import tkinter as tk
from tkinter import scrolledtext, Menu, messagebox, Toplevel
import tkinter.font as tkfont
import tkinter.ttk as ttk
from pathlib import Path
import threading
import os
import sys
import traceback

from app_logger import log_main, log_soft, log_both, get_logger
from config import GITHUB_PROFILE_URL
from defense import SingleInstance
from gui_func_adds import setup_tray_and_close_protocol, create_exit_button, create_tray_icon
from gui_watcher import start_watcher, stop_watcher, initial_check_loop
from gui_func_tables import get_current_branch
from gui_settings import SettingsTab, SETTINGS_FILE

# Импортируем новую вкладку
from gui_main_page import MainTab


class GitVersionRestoreApp:
    """
    Главный класс приложения — управляет GUI, состоянием и фоновыми задачами.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Git Autosync & Version Restore")
        self.root.geometry("900x750")
        self.root.minsize(780, 620)

        # Переменные состояния
        self.watcher_var = tk.BooleanVar(value=True)
        self.auto_on_var = tk.BooleanVar(value=True)
        self.start_minimized_var = tk.BooleanVar(value=False)

        self.current_branch_var = tk.StringVar(value=get_current_branch())

        # Tray
        self.tray_icon = None
        self.tray_thread: threading.Thread | None = None
        self.hidden_to_tray = False

        # Инициализация
        self._load_settings()
        self._setup_singleton()

        if self.start_minimized_var.get():
            log_main("Start Minimized = ON → окно не показываем вообще")
            self.hidden_to_tray = True
            self.root.withdraw()

        self._setup_tray_and_close_protocol()

        # Создание GUI
        self._setup_gui()

        self._bind_global_clipboard_hotkeys()
        self._bind_events_and_loggers()

        self.root.after(0, self._start_background_tasks)

    # ───────────────────────────────────────────────────────────────
    # Настройки
    # ───────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        parser = configparser.ConfigParser()

        if SETTINGS_FILE.exists():
            try:
                parser.read(SETTINGS_FILE)
                val = parser.getboolean("Settings", "start_minimized", fallback=False)
                self.start_minimized_var.set(val)
                log_main(f"Настройка загружена: start_minimized = {val}")
            except Exception as e:
                log_main(f"Ошибка чтения settings.ini: {e}")
        else:
            log_main("settings.ini не найден → значения по умолчанию")

    # ───────────────────────────────────────────────────────────────
    # Singleton
    # ───────────────────────────────────────────────────────────────

    def _setup_singleton(self) -> None:
        self.singleton = SingleInstance("GitAutoSyncRestoreApp_v2026")
        if not self.singleton.acquire():
            log_main("Другой экземпляр уже запущен → завершение")
            sys.exit(0)

    # ───────────────────────────────────────────────────────────────
    # Tray + WM_DELETE_WINDOW
    # ───────────────────────────────────────────────────────────────

    def _setup_tray_and_close_protocol(self) -> None:
        self.hide_to_tray, self.quit_app = setup_tray_and_close_protocol(
            root=self.root,
            stop_watcher=stop_watcher,
            defense_instance=self.singleton,
            app_instance=self,
            hide_method_name="hide_to_tray",
            stop_tray_method_name="_stop_tray_icon"
        )

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        if self.start_minimized_var.get():
            log_main("Start Minimized: запуск сразу в трей")
            self.root.after(300, self._minimize_to_tray_at_startup)
            return

        log_main("Обычный запуск → окно отображается")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

        self.root.after(800, self._force_show_if_hidden)

    def _minimize_to_tray_at_startup(self) -> None:
        try:
            self.hidden_to_tray = True
            self.hide_to_tray()
        except Exception as e:
            log_main(f"Ошибка стартового сворачивания: {e}")
            self.hidden_to_tray = False
            self.root.deiconify()

    def _force_show_if_hidden(self) -> None:
        if self.hidden_to_tray:
            return
        if not self.root.winfo_viewable():
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            log_main("[FORCE] Окно восстановлено (не tray-hide)")

    def on_closing(self) -> None:
        self.hide_to_tray()
        log_both("Закрытие окна → сворачивание в трей")

    def _stop_tray_icon(self) -> None:
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception as e:
                log_main(f"[TRAY] Ошибка остановки: {e}")
            self.tray_icon = None
        self.tray_thread = None

    def hide_to_tray(self) -> None:
        log_soft("Сворачиваем окно в трей")
        self.hidden_to_tray = True
        self.root.withdraw()
        self._stop_tray_icon()

        from pystray import Icon, Menu as pystray_Menu, MenuItem

        def show_window(icon, item):
            self.root.after(0, self._restore_window)

        def quit_from_tray(icon, item):
            log_main("Выход через трей")
            self._stop_tray_icon()
            self.quit_app()

        self.tray_icon = Icon(
            "GitHubRestore",
            create_tray_icon(),
            "GitHub Version Restore",
            menu=pystray_Menu(
                MenuItem("Open", show_window),
                MenuItem("Quit", quit_from_tray)
            )
        )

        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()
        log_soft("[TRAY] Иконка запущена")

    def _restore_window(self) -> None:
        self.hidden_to_tray = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        log_main("Окно восстановлено из трея")

    def _bind_global_clipboard_hotkeys(self) -> None:
        log_soft("[HOTKEYS] Горячие клавиши Ctrl+C/V/X/A подключены (заглушка)")

    # ───────────────────────────────────────────────────────────────
    # GUI структура
    # ───────────────────────────────────────────────────────────────

    def _setup_gui(self) -> None:
        try:
            self._create_tab_switcher()
            self._create_exit_button()

            self.main_frame = tk.Frame(self.root)
            self.softlogger_frame = tk.Frame(self.root)
            self.settings_frame = tk.Frame(self.root)

            # Главная вкладка теперь — отдельный класс
            self.main_tab = MainTab(self.main_frame, self)

            self._create_softlogger_tab()
            self._create_settings_tab()

            self.show_main()

        except Exception as e:
            log_main(f"Критическая ошибка построения GUI: {e}")
            traceback.print_exc()
            messagebox.showerror("Ошибка запуска", f"Не удалось создать интерфейс:\n{str(e)}")
            sys.exit(1)

    def _create_tab_switcher(self) -> None:
        self.switch = tk.Frame(self.root)
        self.switch.pack(fill=tk.X, padx=6, pady=4)

        for text, cmd in [
            ("Главная", self.show_main),
            ("SoftLogger", self.show_softlogger),
            ("Settings", self.show_settings),
        ]:
            tk.Button(self.switch, text=text, command=cmd, width=12)\
                .pack(side=tk.LEFT, padx=4)

    def _create_exit_button(self) -> None:
        font_name = "Minecraftia" if "Minecraftia" in tkfont.families() else "Consolas"
        create_exit_button(self.switch, self.quit_app, font_name)

    # ───────────────────────────────────────────────────────────────
    # SoftLogger вкладка
    # ───────────────────────────────────────────────────────────────

    def _create_softlogger_tab(self) -> None:
        f = self.softlogger_frame
        fr = tk.Frame(f)
        fr.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.log_box_soft = scrolledtext.ScrolledText(
            fr, height=16, state=tk.DISABLED, bg="#f0fff0", font=("Consolas", 9))
        self.log_box_soft.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Button(fr, text="→", width=2,
                  command=lambda: self.open_log_file("loggerm.txt"))\
            .pack(side=tk.RIGHT, padx=6)

        tk.Button(f, text="Назад", command=self.show_main, width=12)\
            .pack(pady=8)

    # ───────────────────────────────────────────────────────────────
    # Settings вкладка
    # ───────────────────────────────────────────────────────────────

    def _create_settings_tab(self) -> None:
        SettingsTab(self.settings_frame, self)

    # ───────────────────────────────────────────────────────────────
    # Переключение вкладок
    # ───────────────────────────────────────────────────────────────

    def show_main(self) -> None:
        self._hide_all_tabs()
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        log_soft("→ вкладка Главная")

    def show_softlogger(self) -> None:
        self._hide_all_tabs()
        self.softlogger_frame.pack(fill=tk.BOTH, expand=True)
        log_soft("→ вкладка SoftLogger")

    def show_settings(self) -> None:
        self._hide_all_tabs()
        self.settings_frame.pack(fill=tk.BOTH, expand=True)
        log_soft("→ вкладка Settings")

    def _hide_all_tabs(self) -> None:
        for frame in (self.main_frame, self.softlogger_frame, self.settings_frame):
            frame.pack_forget()

    # ───────────────────────────────────────────────────────────────
    # Логгеры, контекстные меню, listbox
    # ───────────────────────────────────────────────────────────────

    def _bind_events_and_loggers(self) -> None:
        self._bind_loggers()
        self._bind_context_menus()
        # bind listbox selection теперь внутри MainTab

    def _bind_loggers(self) -> None:
        def append_to_main(text: str):
            widget = self.main_tab.log_box_main
            if not widget or not widget.winfo_exists():
                return
            try:
                widget.config(state="normal")
                widget.insert(tk.END, text + "\n")
                widget.see(tk.END)
                widget.config(state="disabled")
            except:
                pass

        def append_to_soft(text: str):
            if not hasattr(self, "log_box_soft") or not self.log_box_soft.winfo_exists():
                return
            try:
                self.log_box_soft.config(state="normal")
                self.log_box_soft.insert(tk.END, text + "\n")
                self.log_box_soft.see(tk.END)
                self.log_box_soft.config(state="disabled")
            except:
                pass

        try:
            logger = get_logger()
            logger.set_callbacks(main=append_to_main, soft=append_to_soft)
            log_main("Логгер успешно привязан к GUI")
        except Exception as e:
            log_main(f"Не удалось привязать логгер к GUI: {e}")

        log_main("GUI инициализирован")
        log_soft("GUI инициализирован")
        log_both("GUI инициализирован — тест обоих каналов")

    def _bind_context_menus(self) -> None:
        menu_main = Menu(self.root, tearoff=0)
        menu_main.add_command(label="Копировать",
                              command=lambda: self._copy_from_widget(self.main_tab.log_box_main))

        menu_soft = Menu(self.root, tearoff=0)
        menu_soft.add_command(label="Копировать",
                              command=lambda: self._copy_from_widget(self.log_box_soft))

        self.main_tab.log_box_main.bind("<Button-3>", lambda e: self._show_popup(e, menu_main))
        self.log_box_soft.bind("<Button-3>", lambda e: self._show_popup(e, menu_soft))

    def _show_popup(self, event, menu) -> None:
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_from_widget(self, widget) -> None:
        state = widget.cget("state")
        try:
            widget.config(state="normal")
            widget.event_generate("<<Copy>>")
        finally:
            widget.config(state=state)

    # ───────────────────────────────────────────────────────────────
    # Watcher & Auto-ON
    # ───────────────────────────────────────────────────────────────

    def toggle_watcher(self) -> None:
        if self.watcher_var.get():
            start_watcher()
            self.main_tab.watcher_status_label.config(text="Git-Watcher: Active")
            log_main("Git-Watcher запущен")
        else:
            stop_watcher()
            self.main_tab.watcher_status_label.config(text="Git-Watcher: Paused")
            log_main("Git-Watcher остановлен")

    def toggle_auto_on(self) -> None:
        state = "включён" if self.auto_on_var.get() else "выключен"
        log_main(f"Auto-ON теперь {state}")

    # ───────────────────────────────────────────────────────────────
    # Фоновые задачи
    # ───────────────────────────────────────────────────────────────

    def _start_background_tasks(self) -> None:
        threading.Thread(target=self.main_tab.load_pushes, daemon=True).start()

        if self.watcher_var.get():
            self.toggle_watcher()

        threading.Thread(target=initial_check_loop, daemon=True).start()

        self.root.after(12000, self._periodic_push_refresh)
        self.root.after(25000, self._periodic_branch_check)

    def _periodic_push_refresh(self) -> None:
        self.main_tab.load_pushes()
        self.root.after(15000, self._periodic_push_refresh)

    def _periodic_branch_check(self) -> None:
        current = get_current_branch()
        if current and current != self.current_branch_var.get():
            self.current_branch_var.set(current)
            self.main_tab.load_pushes(force_refresh=True)
            log_soft(f"Обнаружена смена ветки → {current}")
        self.root.after(30000, self._periodic_branch_check)

    # ───────────────────────────────────────────────────────────────
    # Утилиты
    # ───────────────────────────────────────────────────────────────

    def open_log_file(self, filename: str) -> None:
        path = Path(__file__).parent / filename
        if path.exists():
            os.startfile(path)
        else:
            log_main(f"Лог-файл не найден: {filename}")

    def _create_notification(self, message: str, duration_ms: int = 1400) -> None:
        notif = Toplevel(self.root)
        notif.overrideredirect(True)
        notif.attributes("-topmost", True)
        notif.attributes("-alpha", 0.93)

        fr = tk.Frame(notif, bg="#1e293b", bd=1, relief="solid")
        fr.pack()

        tk.Label(fr, text=message, bg="#1e293b", fg="#e2e8f0",
                 font=("Segoe UI", 11, "bold"), padx=20, pady=12).pack()

        self.root.update_idletasks()
        x = self.root.winfo_screenwidth() - notif.winfo_reqwidth() - 32
        y = self.root.winfo_screenheight() - notif.winfo_reqheight() - 64
        notif.geometry(f"+{x}+{y}")
        notif.after(duration_ms, notif.destroy)


if __name__ == "__main__":
    root = tk.Tk()
    app = GitVersionRestoreApp(root)
    root.mainloop()

