"""
Settings вкладка (полная версия)

 Start Minimized ON/OFF (синий стиль)
 PNG Copy/Paste без фона + бордовый контур
 ПКМ меню Copy/Paste/Cut/Select All
 Toast уведомления
 Save + Exit — сохраняет введённые значения в .env и закрывает приложение
 Поле GitHub Token с переключателем видимости
 Поля редактируются свободно, сохраняются именно введённые строки
 Git Folder — readonly + обновляется каждые 5 сек + кнопка Refresh
 Update Frequency (в минутах) — редактируемое поле, не перезаписывается во время ввода
"""



import tkinter as tk
from tkinter import messagebox, Menu, filedialog
import os
import sys
from pathlib import Path
from configparser import ConfigParser

from PIL import Image, ImageTk

from core.logger import log_main, log_soft
from core.config import settings, save_watched_folder


SETTINGS_FILE = Path(__file__).resolve().parents[1] / "settings.ini"
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


class SettingsTab:
    def __init__(self, parent_frame, app_instance):
        self.parent = parent_frame
        self.app = app_instance

        self.start_minimized_var = self.app.start_minimized_var

        self.github_username_var = tk.StringVar(value=settings.github_username)
        self.github_repo_var     = tk.StringVar(value=settings.github_repo)
        self.github_token_var    = tk.StringVar(value=settings.github_token or "")

        # Update Frequency в минутах — начальное значение
        self.update_freq_var = tk.StringVar(value=f"{settings.debounce_seconds / 60:.1f}")

        self.show_token_var = tk.BooleanVar(value=False)

        self.eye_closed_icon = None
        self.eye_open_icon   = None
        self.folder_icon     = None
        self.refresh_icon    = None

        self._load_icons()
        self._create_widgets()

        # Периодическое обновление только для readonly-поля Git Folder
        self._schedule_update_git_folder()

    def _load_icons(self):
        try:
            copy_img  = Image.open(ASSETS_DIR / "copy.png").resize((24, 24))
            paste_img = Image.open(ASSETS_DIR / "paste.png").resize((24, 24))
            self.copy_icon  = ImageTk.PhotoImage(copy_img)
            self.paste_icon = ImageTk.PhotoImage(paste_img)

            closed_img = Image.open(ASSETS_DIR / "eye_closed.png").resize((22, 22))
            open_img   = Image.open(ASSETS_DIR / "eye_open.png").resize((22, 22))
            self.eye_closed_icon = ImageTk.PhotoImage(closed_img)
            self.eye_open_icon   = ImageTk.PhotoImage(open_img)

            folder_img = Image.open(ASSETS_DIR / "folder.png").resize((24, 24))
            self.folder_icon = ImageTk.PhotoImage(folder_img)

            refresh_path = ASSETS_DIR / "refresh.png"
            refresh_img = Image.open(refresh_path).resize((20, 20)) if refresh_path.exists() else None
            self.refresh_icon = ImageTk.PhotoImage(refresh_img) if refresh_img else None

            log_soft("Все иконки загружены успешно")

        except Exception as e:
            log_main(f"Ошибка загрузки иконок: {e}")
            self.copy_icon = self.paste_icon = self.folder_icon = self.refresh_icon = None
            self.eye_closed_icon = self.eye_open_icon = None

    def show_toast(self, text: str):
        toast = tk.Toplevel(self.app.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)

        width, height = 280, 80
        x = self.app.root.winfo_screenwidth() - width - 30
        y = self.app.root.winfo_screenheight() - height - 90

        toast.geometry(f"{width}x{height}+{x}+{y}")

        frame = tk.Frame(toast, bg="#111827", bd=2, relief="ridge")
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=text,
            font=("Consolas", 13, "bold"),
            fg="white",
            bg="#111827"
        ).pack(expand=True)

        toast.after(4000, toast.destroy)

    def _copy_value(self, var):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(var.get())
        self.show_toast("📋 Скопировано!")

    def _paste_value(self, var):
        try:
            var.set(self.app.root.clipboard_get())
            self.show_toast("📥 Вставлено!")
        except tk.TclError:
            self.show_toast("Буфер обмена пуст")

    def _bind_entry_hotkeys(self, entry):
        menu = Menu(entry, tearoff=0)
        menu.add_command(label="Copy",       command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Paste",      command=lambda: entry.event_generate("<<Paste>>"))
        menu.add_command(label="Cut",        command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: entry.select_range(0, tk.END))

        entry.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        entry.bind("<Control-c>", lambda e: (entry.event_generate("<<Copy>>"),  "break"))
        entry.bind("<Control-v>", lambda e: (entry.event_generate("<<Paste>>"), "break"))
        entry.bind("<Control-x>", lambda e: (entry.event_generate("<<Cut>>"),   "break"))
        entry.bind("<Control-a>", lambda e: (entry.select_range(0, tk.END),     "break"))

    def _create_clipboard_buttons(self, container, var):
        bg_color = "#f8f9fa"

        tk.Button(
            container,
            image=self.copy_icon,
            bg=bg_color,
            activebackground=bg_color,
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground="#7f1d1d",
            command=lambda: self._copy_value(var)
        ).pack(side=tk.LEFT, padx=(8, 4))

        tk.Button(
            container,
            image=self.paste_icon,
            bg=bg_color,
            activebackground=bg_color,
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground="#7f1d1d",
            command=lambda: self._paste_value(var)
        ).pack(side=tk.LEFT, padx=(4, 12))

    def _select_watched_folder(self):
        folder = filedialog.askdirectory(
            title="Выберите папку для Git Backup",
            initialdir=str(settings.watched_folder),
            mustexist=False
        )
        if folder:
            folder_path = Path(folder).resolve()
            if save_watched_folder(folder_path):
                self.watched_folder_entry.config(state="normal")
                self.watched_folder_entry.delete(0, tk.END)
                self.watched_folder_entry.insert(0, str(folder_path))
                self.watched_folder_entry.config(state="readonly")
                self.show_toast("Папка Git обновлена")
            else:
                messagebox.showerror("Ошибка", "Не удалось сохранить папку\n(проверьте права доступа)")

    def _update_git_folder_only(self):
        """Обновляет ТОЛЬКО поле Git Folder каждые 5 секунд"""
        try:
            current_folder = str(settings.watched_folder)
            if self.watched_folder_entry.get() != current_folder:
                self.watched_folder_entry.config(state="normal")
                self.watched_folder_entry.delete(0, tk.END)
                self.watched_folder_entry.insert(0, current_folder)
                self.watched_folder_entry.config(state="readonly")
                log_soft(f"[GIT-FOLDER-UPDATE] Путь обновлён: {current_folder}")
        except Exception as e:
            log_main(f"[GIT-FOLDER-ERROR] {e}")

        self.parent.after(5000, self._update_git_folder_only)

    def _schedule_update_git_folder(self):
        self.parent.after(1000, self._update_git_folder_only)

    def _save_all_to_env(self):
        """Сохраняет ВСЕ введённые значения в .env"""
        try:
            env_path = Path(__file__).resolve().parents[1] / ".env"

            lines = []
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            new_values = {
                "GITHUB_USERNAME": self.github_username_var.get().strip(),
                "GITHUB_REPO": self.github_repo_var.get().strip(),
                "GITHUB_TOKEN": self.github_token_var.get().strip(),
                "WATCHED_FOLDER": settings.watched_folder.as_posix(),
            }

            # Обработка Update Frequency
            try:
                minutes_str = self.update_freq_var.get().strip()
                if minutes_str:
                    minutes = float(minutes_str)
                    if minutes > 0:
                        new_values["DEBOUNCE_MINUTES"] = f"{minutes:.2f}"  # сохраняем с двумя знаками
                        log_soft(f"[SETTINGS] DEBOUNCE_MINUTES сохранено: {minutes} мин")
                    else:
                        log_main("[SETTINGS] DEBOUNCE_MINUTES ≤ 0 — не сохраняем")
            except ValueError:
                log_main(f"[SETTINGS] Некорректное значение минут: '{minutes_str}' → не сохраняем")
                self.show_toast("Некорректное значение минут — не сохранено")

            new_lines = []
            keys_written = set()

            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    new_lines.append(line)
                    continue
                key = stripped.split('=', 1)[0].strip()
                if key in new_values:
                    new_lines.append(f'{key}="{new_values[key]}"\n')
                    keys_written.add(key)
                else:
                    new_lines.append(line)

            for key, value in new_values.items():
                if key not in keys_written:
                    new_lines.append(f'{key}="{value}"\n')

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            self.show_toast("Настройки сохранены в .env")

        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить .env\n{e}")

    def _create_widgets(self):
        cont = tk.Frame(self.parent, bg="#f8f9fa", bd=2, relief="groove")
        cont.pack(pady=40, padx=40, fill=tk.BOTH, expand=True)

        tk.Label(cont, text="Settings", font=("Consolas", 18, "bold"), bg="#f8f9fa").pack(pady=(20, 35))

        self._create_minimized_row(cont)

        # ── Git Folder (readonly) ───────────────────────────────────────
        watched_row = tk.Frame(cont, bg="#f8f9fa")
        watched_row.pack(fill=tk.X, pady=16, padx=10)

        tk.Label(watched_row, text="Git Folder", font=("Consolas", 12), bg="#f8f9fa", width=24, anchor="w").pack(side=tk.LEFT, padx=(12, 12))

        self.watched_folder_entry = tk.Entry(
            watched_row, font=("Consolas", 12), width=38, relief="solid", bd=1, readonlybackground="#ffffff"
        )
        self.watched_folder_entry.insert(0, str(settings.watched_folder))
        self.watched_folder_entry.config(state="readonly")
        self.watched_folder_entry.pack(side=tk.LEFT, padx=(8, 4), fill=tk.X, expand=True)

        tk.Button(watched_row, image=self.folder_icon, bg="#f8f9fa", relief="flat", bd=0,
                  command=self._select_watched_folder).pack(side=tk.LEFT, padx=(4, 4))

        # ── Update Frequency (minutes) ──────────────────────────────────
        freq_row = tk.Frame(cont, bg="#f8f9fa")
        freq_row.pack(fill=tk.X, pady=16, padx=10)

        tk.Label(freq_row, text="Update Frequency", font=("Consolas", 12), bg="#f8f9fa", width=24, anchor="w").pack(side=tk.LEFT, padx=(12, 12))

        self.update_freq_entry = tk.Entry(
            freq_row, textvariable=self.update_freq_var, font=("Consolas", 12), width=10, relief="solid", bd=1
        )
        self.update_freq_entry.pack(side=tk.LEFT, padx=(8, 4))

        tk.Label(freq_row, text="minutes", font=("Consolas", 12), bg="#f8f9fa").pack(side=tk.LEFT, padx=(4, 12))

        self._bind_entry_hotkeys(self.update_freq_entry)
        self._create_clipboard_buttons(freq_row, self.update_freq_var)
        self.update_freq_entry.bind("<FocusOut>", lambda e: self._save_all_to_env())

        # ── GitHub Username ─────────────────────────────────────────────
        username_row = tk.Frame(cont, bg="#f8f9fa")
        username_row.pack(fill=tk.X, pady=16, padx=10)

        tk.Label(username_row, text="GitHub Username", font=("Consolas", 12), bg="#f8f9fa", width=24, anchor="w").pack(side=tk.LEFT, padx=(12, 12))

        self.github_username_entry = tk.Entry(username_row, textvariable=self.github_username_var,
                                              font=("Consolas", 12), relief="solid", bd=1)
        self.github_username_entry.pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)
        self._bind_entry_hotkeys(self.github_username_entry)
        self._create_clipboard_buttons(username_row, self.github_username_var)
        self.github_username_entry.bind("<FocusOut>", lambda e: self._save_all_to_env())

        # ── Repository Name ─────────────────────────────────────────────
        repo_row = tk.Frame(cont, bg="#f8f9fa")
        repo_row.pack(fill=tk.X, pady=16, padx=10)

        tk.Label(repo_row, text="Repository Name", font=("Consolas", 12), bg="#f8f9fa", width=24, anchor="w").pack(side=tk.LEFT, padx=(12, 12))

        self.github_repo_entry = tk.Entry(repo_row, textvariable=self.github_repo_var,
                                          font=("Consolas", 12), relief="solid", bd=1)
        self.github_repo_entry.pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)
        self._bind_entry_hotkeys(self.github_repo_entry)
        self._create_clipboard_buttons(repo_row, self.github_repo_var)
        self.github_repo_entry.bind("<FocusOut>", lambda e: self._save_all_to_env())

        # ── GitHub Token ────────────────────────────────────────────────
        token_row = tk.Frame(cont, bg="#f8f9fa")
        token_row.pack(fill=tk.X, pady=16, padx=10)

        tk.Label(token_row, text="GitHub Token", font=("Consolas", 12), bg="#f8f9fa", width=24, anchor="w").pack(side=tk.LEFT, padx=(12, 12))

        token_container = tk.Frame(token_row, bg="#f8f9fa")
        token_container.pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)

        self.token_entry = tk.Entry(token_container, textvariable=self.github_token_var,
                                    font=("Consolas", 12), show="•", relief="solid", bd=1)
        self.token_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.eye_button = tk.Button(token_container, image=self.eye_closed_icon, bg="#f8f9fa",
                                    relief="flat", bd=0, command=self._toggle_token_visibility)
        self.eye_button.pack(side=tk.LEFT, padx=(4, 0))

        self._bind_entry_hotkeys(self.token_entry)
        self._create_clipboard_buttons(token_row, self.github_token_var)
        self.token_entry.bind("<FocusOut>", lambda e: self._save_all_to_env())

        # ── Save + Exit ─────────────────────────────────────────────────
        btn_frame = tk.Frame(cont, bg="#f8f9fa")
        btn_frame.pack(pady=50)

        tk.Button(
            btn_frame,
            text="Save + Exit",
            font=("Consolas", 13, "bold"),
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            relief="flat",
            bd=0,
            padx=28,
            pady=12,
            command=self._save_and_exit
        ).pack()

        self.sync_minimized_button_state()

    def _create_minimized_row(self, parent):
        row = tk.Frame(parent, bg="#f8f9fa")
        row.pack(fill=tk.X, pady=18)

        tk.Label(row, text="Start Minimized", font=("Consolas", 12), bg="#f8f9fa", width=20, anchor="w").pack(side=tk.LEFT, padx=12)

        self.minimized_button = tk.Button(
            row,
            text="OFF",
            width=9,
            font=("Consolas", 11, "bold"),
            relief="flat",
            bd=0,
            command=self.toggle_start_minimized
        )
        self.minimized_button.pack(side=tk.LEFT, padx=12)

    def sync_minimized_button_state(self):
        on = self.start_minimized_var.get()
        self.minimized_button.config(
            text="ON" if on else "OFF",
            bg="#2563eb" if on else "#d1d5db",
            fg="white" if on else "black",
            activebackground="#1d4ed8" if on else "#9ca3af"
        )

    def toggle_start_minimized(self):
        self.start_minimized_var.set(not self.start_minimized_var.get())
        self.sync_minimized_button_state()
        self._save_minimized()

    def _save_minimized(self):
        cfg = ConfigParser()
        cfg["Settings"] = {"start_minimized": str(self.start_minimized_var.get()).lower()}

        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

        log_soft("settings.ini обновлён (start_minimized)")

    def _toggle_token_visibility(self):
        if self.show_token_var.get():
            self.token_entry.config(show="")
            self.eye_button.config(image=self.eye_open_icon)
        else:
            self.token_entry.config(show="•")
            self.eye_button.config(image=self.eye_closed_icon)
        self.show_token_var.set(not self.show_token_var.get())


    def _save_and_exit(self):
        self._save_all_to_env()
        messagebox.showinfo("Сохранено", "Настройки сохранены.\nПриложение будет закрыто.")
        self.app.root.after(1000, self._exit_app)

    def _exit_app(self):
        log_soft("[EXIT] Закрытие приложения...")
        self.app.root.quit()
        self.app.root.destroy()
        sys.exit(0)


__all__ = ["SettingsTab", "SETTINGS_FILE"]