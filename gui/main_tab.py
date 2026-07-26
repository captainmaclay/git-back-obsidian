# gui_main_page.py
"""
Логика и виджеты вкладки «Главная»
"""

import tkinter as tk
from tkinter import scrolledtext, ttk
import threading
import requests
import tkinter.messagebox as messagebox

from core.logger import log_main, log_soft
from core.config import GITHUB_USERNAME, GITHUB_REPO, GITHUB_TOKEN, GITHUB_PROFILE_URL
from gui.version_ops import clone_version, open_versions, fetch_pushes
from gui.branches import create_branch_selector_button
from sync.watcher import safe_ensure_repository_and_main_branch


class MainTab:
    """
    Класс, отвечающий за содержимое вкладки "Главная"
    """

    def __init__(self, parent_frame: tk.Frame, app):
        self.parent = parent_frame
        self.app = app

        # Виджеты, к которым нужен доступ извне
        self.push_listbox = None
        self.commit_entry = None
        self.comment_box = None
        self.log_box_main = None
        self.watcher_status_label = None
        self.branch_button = None

        # Данные
        self.pushes: list[dict] = []
        self.selected_sha: str | None = None

        self._build_ui()
        self._bind_events()

    def _build_ui(self):
        f = self.parent

        top = tk.Frame(f)
        top.pack(fill=tk.X, padx=12, pady=(12, 6))

        # Выбор ветки
        branch_f = tk.Frame(top)
        branch_f.pack(fill=tk.X)

        self.branch_button = create_branch_selector_button(
            branch_f,
            self.app.current_branch_var,
            self.load_pushes
        )

        # Поле SHA
        tk.Label(top, text="Версия (commit SHA):").pack(anchor="w", pady=(8, 2))

        entry_f = tk.Frame(top)
        entry_f.pack(fill=tk.X)

        self.commit_entry = tk.Entry(entry_f, width=60)
        self.commit_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Кнопки действий
        btn_f = tk.Frame(top)
        btn_f.pack(fill=tk.X, pady=8)

        tk.Button(btn_f, text="Clone", width=16, command=self.clone_selected_version)\
            .pack(side=tk.LEFT, padx=(0, 12))

        tk.Button(btn_f, text="Open Versions", width=16, command=open_versions)\
            .pack(side=tk.LEFT, padx=12)

        # Кнопки копирования
        copy_f = tk.Frame(btn_f)
        copy_f.pack(side=tk.LEFT, padx=(20, 0))

        tk.Button(copy_f, text="📋", width=3, command=self.copy_selected_sha,
                  font=("Arial", 13)).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(copy_f, text="🔗", width=3, command=self.copy_profile_url,
                  font=("Arial", 13)).pack(side=tk.LEFT)

        # Чекбоксы управления
        chk_f = tk.Frame(top)
        chk_f.pack(fill=tk.X, pady=10)

        tk.Checkbutton(chk_f, text="Git-Watcher", variable=self.app.watcher_var,
                       command=self.app.toggle_watcher)\
            .pack(side=tk.LEFT, padx=(0, 24))

        self.watcher_status_label = tk.Label(
            chk_f, text="Git-Watcher: Active", width=20, anchor="w")
        self.watcher_status_label.pack(side=tk.LEFT)

        tk.Checkbutton(chk_f, text="Auto-ON", variable=self.app.auto_on_var,
                       command=self.app.toggle_auto_on)\
            .pack(side=tk.LEFT, padx=(40, 0))

        # Разделители (paned windows)
        paned_v = ttk.PanedWindow(f, orient=tk.VERTICAL)
        paned_v.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        paned_h = ttk.PanedWindow(paned_v, orient=tk.HORIZONTAL)
        paned_v.add(paned_h, weight=5)

        # Список коммитов слева
        left = tk.Frame(paned_h)
        paned_h.add(left, weight=1)

        sb = tk.Scrollbar(left)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.push_listbox = tk.Listbox(
            left, yscrollcommand=sb.set, font=("Consolas", 10))
        self.push_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.push_listbox.yview)

        # Комментарий к коммиту справа
        right = tk.Frame(paned_h)
        paned_h.add(right, weight=3)

        self.comment_box = scrolledtext.ScrolledText(
            right, state=tk.DISABLED, wrap=tk.WORD, font=("Segoe UI", 10))
        self.comment_box.pack(fill=tk.BOTH, expand=True)

        # Нижний лог
        log_bottom = tk.Frame(paned_v)
        paned_v.add(log_bottom, weight=4)

        log_f = tk.Frame(log_bottom)
        log_f.pack(fill=tk.BOTH, expand=True)

        self.log_box_main = scrolledtext.ScrolledText(
            log_f, height=10, state=tk.DISABLED,
            bg="#f9fafb", font=("Consolas", 9))
        self.log_box_main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        tk.Button(
            log_f, text="→", width=2,
            command=lambda: self.app.open_log_file("logger.txt")
        ).pack(side=tk.RIGHT, padx=4)

    def _bind_events(self):
        self.push_listbox.bind("<<ListboxSelect>>", self.on_select_commit)

    # ───────────────────────────────────────────────
    # Методы главной вкладки
    # ───────────────────────────────────────────────

    def load_pushes(self, force_refresh: bool = False) -> None:
        try:
            fresh = fetch_pushes(GITHUB_USERNAME, GITHUB_REPO, GITHUB_TOKEN)

            if fresh != self.pushes or force_refresh:
                self.pushes = fresh
                self.push_listbox.delete(0, tk.END)

                for commit in self.pushes[:60]:
                    msg = commit["commit"]["message"].splitlines()[0][:90]
                    self.push_listbox.insert(tk.END, f"{commit['sha'][:8]} | {msg}")

                log_soft(f"Список пушей обновлён: {len(self.pushes)} коммитов")

        except Exception as e:
            if "409" in str(e) and "empty" in str(e).lower():
                log_main("Репозиторий пустой (409) → инициализация")
                safe_ensure_repository_and_main_branch()
                self.load_pushes(force_refresh=True)
            else:
                log_main(f"Ошибка загрузки пушей: {e}")

    def on_select_commit(self, event):
        sel = self.push_listbox.curselection()
        if not sel:
            return

        idx = sel[0]
        self.selected_sha = self.pushes[idx]["sha"]

        self.commit_entry.delete(0, tk.END)
        self.commit_entry.insert(0, self.selected_sha)

        self._load_commit_comment_async(self.selected_sha)

    def _load_commit_comment_async(self, sha: str):
        self.comment_box.config(state="normal")
        self.comment_box.delete("1.0", tk.END)
        self.comment_box.insert(tk.END, "Загрузка комментария...\n")
        self.comment_box.config(state="disabled")

        def fetch_task():
            try:
                url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/commits/{sha}/comments"
                headers = {"Accept": "application/vnd.github+json"}
                if GITHUB_TOKEN:
                    headers["Authorization"] = f"token {GITHUB_TOKEN}"

                r = requests.get(url, headers=headers, timeout=10)
                r.raise_for_status()
                comments = r.json()

                self.comment_box.config(state="normal")
                self.comment_box.delete("1.0", tk.END)

                if not comments:
                    self.comment_box.insert(tk.END, "Комментариев к этому коммиту нет.\n")
                else:
                    c = comments[-1]
                    user = c.get("user", {}).get("login", "—")
                    date = c.get("created_at", "—")
                    body = c.get("body", "(пусто)")
                    link = c.get("html_url", "—")
                    self.comment_box.insert(tk.END, f"@{user} ({date})\n\n{body}\n\n→ {link}\n")

                self.comment_box.config(state="disabled")
                self.comment_box.see(tk.END)

            except Exception as e:
                msg = f"Ошибка загрузки комментария: {e}"
                self.comment_box.config(state="normal")
                self.comment_box.delete("1.0", tk.END)
                self.comment_box.insert(tk.END, msg + "\n")
                self.comment_box.config(state="disabled")
                log_main(msg)

        threading.Thread(target=fetch_task, daemon=True).start()

    def copy_selected_sha(self):
        if self.selected_sha:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(self.selected_sha)
            self.app._create_notification("SHA скопирован ✓")
            log_soft("SHA скопирован в буфер")
        else:
            log_main("Нет выбранного коммита")

    def copy_profile_url(self):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(GITHUB_PROFILE_URL)
        self.app._create_notification("Ссылка на профиль ✓")
        log_soft("Ссылка на профиль скопирована")

    def clone_selected_version(self):
        sha = self.commit_entry.get().strip()
        if not sha:
            messagebox.showwarning("Ошибка", "Введите SHA коммита")
            return
        clone_version(sha, GITHUB_USERNAME, GITHUB_REPO, GITHUB_TOKEN)