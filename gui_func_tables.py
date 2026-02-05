"""
gui_func_tables.py — логика работы с ветками и таблицей выбора веток для GUI
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pygit2
from pathlib import Path

from app_logger import log_main, log_soft, log_both

from config import FAKE_PUSH_GIT, GITHUB_USERNAME, GITHUB_REPO, GITHUB_TOKEN



def get_current_branch(repo_path=FAKE_PUSH_GIT):
    """Возвращает имя текущей ветки"""
    try:
        repo = pygit2.Repository(str(repo_path))
        return repo.head.shorthand
    except Exception as e:
        log_main(f"Ошибка получения текущей ветки: {e}")
        return "unknown"





def get_remote_branches(github_user=GITHUB_USERNAME, github_repo=GITHUB_REPO, token=GITHUB_TOKEN):
    """
    Получает список всех веток репозитория через GitHub API
    Возвращает список строк с именами веток, отсортированных по алфавиту
    """
    import requests

    url = f"https://api.github.com/repos/{github_user}/{github_repo}/branches"
    headers = {"Authorization": f"token {token}"}

    log_soft(f"Запрашиваем список веток через GitHub API: {url}")

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            branches = [branch["name"] for branch in resp.json()]
            branches.sort()
            log_soft(f"Получено {len(branches)} веток")
            return branches
        else:
            log_main(f"GitHub API ошибка: {resp.status_code} - {resp.text[:200]}")
            return []
    except Exception as e:
        log_main(f"Ошибка запроса веток: {type(e).__name__}: {e}")
        return []


def change_branch(branch_name, repo_path=FAKE_PUSH_GIT):
    """Переключает репозиторий на указанную ветку"""
    try:
        repo = pygit2.Repository(str(repo_path))
        if branch_name in repo.branches.remote:
            repo.checkout(f'refs/remotes/origin/{branch_name}')
            log_both(f"Переключено на ветку: {branch_name}")
        elif branch_name in repo.branches.local:
            repo.checkout(f'refs/heads/{branch_name}')
            log_both(f"Переключено на локальную ветку: {branch_name}")
        else:
            log_main(f"Ветка {branch_name} не найдена")
            return False
        return True
    except Exception as e:
        log_main(f"Ошибка переключения на ветку {branch_name}: {e}")
        return False


class BranchSelectorWindow(tk.Toplevel):
    """Всплывающее окно с таблицей всех веток и пагинацией"""

    def __init__(self, parent, on_select_callback):
        super().__init__(parent)
        self.title("Выбор ветки")
        self.geometry("600x500")
        self.resizable(True, True)
        self.on_select = on_select_callback

        self.branches = get_remote_branches()
        if not self.branches:
            messagebox.showerror("Ошибка", "Не удалось загрузить список веток")
            self.destroy()
            return

        self.page_size = 30
        self.current_page = 0
        self.total_pages = (len(self.branches) + self.page_size - 1) // self.page_size

        self._create_widgets()
        self._update_table()


    def _create_widgets(self):
        # Таблица
        columns = ("№", "Ветка")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=15)
        self.tree.heading("№", text="№")
        self.tree.heading("Ветка", text="Ветка")
        self.tree.column("№", width=50, anchor="center")
        self.tree.column("Ветка", width=400)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Выбор страницы
        page_frame = tk.Frame(self)
        page_frame.pack(fill=tk.X, pady=5)

        tk.Label(page_frame, text="Страница:").pack(side=tk.LEFT, padx=5)

        self.page_var = tk.StringVar(value="1")
        self.page_combo = ttk.Combobox(page_frame, textvariable=self.page_var, width=10, state="readonly")
        self.page_combo['values'] = list(range(1, self.total_pages + 1))
        self.page_combo.pack(side=tk.LEFT)
        self.page_combo.bind("<<ComboboxSelected>>", lambda e: self._update_table())

        tk.Label(page_frame, text=f"из {self.total_pages}").pack(side=tk.LEFT, padx=5)

        # Кнопка OK
        self.ok_btn = tk.Button(self, text="OK", width=10, state="disabled", command=self._select_branch)
        self.ok_btn.pack(pady=10)

        # Привязка выбора строки
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _update_table(self):
        self.tree.delete(*self.tree.get_children())

        page = int(self.page_var.get()) - 1
        start = page * self.page_size
        end = start + self.page_size
        page_branches = self.branches[start:end]

        for i, branch in enumerate(page_branches, start=start + 1):
            self.tree.insert("", tk.END, values=(i, branch))

    def _on_tree_select(self, event):
        selected = self.tree.selection()
        self.ok_btn.config(state="normal" if selected else "disabled")

    def _select_branch(self):
        selected = self.tree.selection()
        if selected:
            item = self.tree.item(selected[0])
            branch_name = item["values"][1]
            self.on_select(branch_name)
            self.destroy()


def create_branch_selector_button(parent_frame, current_branch_var: tk.StringVar, refresh_callback):
    """
    Создаёт кнопку-селектор веток над списком пушей.

    Аргументы:
    - parent_frame: куда помещать кнопку
    - current_branch_var: tk.StringVar с текущей веткой
    - refresh_callback: функция, которая обновляет список пушей после смены ветки
    """

    def show_branch_menu(event):
        menu = tk.Menu(parent_frame, tearoff=0)

        # Последние 15 веток (локально + удалённые)
        branches = get_remote_branches()[:15]
        for branch in branches:
            menu.add_command(
                label=branch,
                command=lambda b=branch: select_branch(b)
            )

        menu.add_separator()
        menu.add_command(label="Show More...", command=show_all_branches_window)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def select_branch(branch_name):
        if change_branch(branch_name):
            current_branch_var.set(branch_name)
            refresh_callback()  # обновляем список пушей
            log_both(f"Переключено на ветку: {branch_name}")

    def show_all_branches_window():
        BranchSelectorWindow(parent_frame, select_branch)

    # Сама кнопка
    branch_btn = tk.Button(
        parent_frame,
        textvariable=current_branch_var,
        compound=tk.RIGHT,
        width=20,
        relief="raised",
        bg="#e0e0ff",
        activebackground="#d0d0ff"
    )
    branch_btn.pack(pady=5, padx=10)

    # Добавляем стрелку ↑
    branch_btn.config(text=f"{current_branch_var.get()} ↑")

    # Привязываем меню
    branch_btn.bind("<Button-1>", show_branch_menu)

    # Обновляем текст кнопки при смене переменной
    def update_button(*args):
        branch_btn.config(text=f"{current_branch_var.get()} ↑")

    current_branch_var.trace("w", update_button)

    return branch_btn



