"""
gui/theme.py — светлая/тёмная тема для Tkinter-интерфейса.

Тема применяется РЕКУРСИВНО ко всем виджетам окна (`apply_theme(root)`): у каждого
виджета выставляются цвета по его классу (Frame/Label/Button/Entry/Checkbutton/Listbox/
Text/Canvas/Menu/Toplevel). Для ttk-виджетов (PanedWindow/Treeview/Combobox) настраивается
ttk.Style. Выбор темы сохраняется в settings.ini (`[Settings] theme = dark|light`).

Акцентные кнопки (Save+Exit — синяя, Exit — зелёная) сохраняют свой цвет в обеих темах.
"""

import sys
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from configparser import ConfigParser

_SETTINGS_FILE = Path(__file__).resolve().parents[1] / "settings.ini"

LIGHT = {
    "bg":        "#f8f9fa",
    "fg":        "#1e293b",
    "entry_bg":  "#ffffff",
    "entry_fg":  "#1e293b",
    "select_bg": "#2563eb",
    "select_fg": "#ffffff",
    "button_bg": "#e6e6ef",
    "button_fg": "#1e293b",
    "log_bg":    "#f9fafb",
}

DARK = {
    "bg":        "#1e1e24",
    "fg":        "#e2e8f0",
    "entry_bg":  "#2a2a33",
    "entry_fg":  "#e6e6ef",
    "select_bg": "#3b82f6",
    "select_fg": "#ffffff",
    "button_bg": "#33333d",
    "button_fg": "#e2e8f0",
    "log_bg":    "#17171c",
}

# Кнопки-акценты — их цвет НЕ перекрашиваем (остаются брендовыми в обеих темах)
_ACCENT_BG = {"#2563eb", "#1d4ed8", "#2E7D32", "#1B5E20"}

_current = "light"


# ── состояние / сохранение ──────────────────────────────────────────────────

def current() -> str:
    return _current


def is_dark() -> bool:
    return _current == "dark"


def palette() -> dict:
    return DARK if _current == "dark" else LIGHT


def set_current(name: str) -> None:
    global _current
    _current = "dark" if str(name).strip().lower() == "dark" else "light"


def load_saved() -> str:
    try:
        cfg = ConfigParser()
        cfg.read(_SETTINGS_FILE, encoding="utf-8")
        return "dark" if cfg.get("Settings", "theme", fallback="light").strip().lower() == "dark" else "light"
    except Exception:
        return "light"


def save(name: str) -> None:
    try:
        cfg = ConfigParser()
        cfg.read(_SETTINGS_FILE, encoding="utf-8")
        if not cfg.has_section("Settings"):
            cfg.add_section("Settings")
        cfg.set("Settings", "theme", "dark" if name == "dark" else "light")
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
    except Exception:
        pass


def toggle() -> str:
    set_current("light" if is_dark() else "dark")
    save(_current)
    return _current


# ── применение темы ─────────────────────────────────────────────────────────

def _cfg(widget, **opts) -> None:
    for key, val in opts.items():
        try:
            widget.configure(**{key: val})
        except Exception:
            pass


def _apply_one(w, t: dict) -> None:
    cls = w.winfo_class()

    if cls in ("Frame", "Labelframe", "Toplevel", "Canvas"):
        _cfg(w, bg=t["bg"])
    elif cls == "Label":
        _cfg(w, bg=t["bg"], fg=t["fg"])
    elif cls == "Button":
        cur = ""
        try:
            cur = str(w.cget("bg"))
        except Exception:
            pass
        if cur not in _ACCENT_BG:
            _cfg(w, bg=t["button_bg"], fg=t["button_fg"],
                 activebackground=t["select_bg"], activeforeground=t["select_fg"])
    elif cls in ("Checkbutton", "Radiobutton"):
        _cfg(w, bg=t["bg"], fg=t["fg"], selectcolor=t["entry_bg"],
             activebackground=t["bg"], activeforeground=t["fg"])
    elif cls == "Entry":
        _cfg(w, bg=t["entry_bg"], fg=t["entry_fg"], insertbackground=t["fg"],
             readonlybackground=t["entry_bg"], disabledbackground=t["entry_bg"])
    elif cls == "Listbox":
        _cfg(w, bg=t["entry_bg"], fg=t["entry_fg"],
             selectbackground=t["select_bg"], selectforeground=t["select_fg"])
    elif cls == "Text":
        _cfg(w, bg=t["log_bg"], fg=t["fg"], insertbackground=t["fg"])
    elif cls == "Menu":
        _cfg(w, bg=t["bg"], fg=t["fg"],
             activebackground=t["select_bg"], activeforeground=t["select_fg"])

    for child in w.winfo_children():
        _apply_one(child, t)


def _apply_ttk(root, t: dict) -> None:
    try:
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=t["bg"])
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure("TPanedwindow", background=t["bg"])
        style.configure("Treeview",
                        background=t["entry_bg"], fieldbackground=t["entry_bg"], foreground=t["fg"])
        style.map("Treeview",
                  background=[("selected", t["select_bg"])], foreground=[("selected", t["select_fg"])])
        style.configure("Treeview.Heading", background=t["button_bg"], foreground=t["fg"])
        style.configure("TCombobox",
                        fieldbackground=t["entry_bg"], background=t["button_bg"], foreground=t["fg"])
    except Exception:
        pass


def _apply_titlebar(root, dark: bool) -> None:
    """
    Тёмная/светлая нативная шапка окна на Windows 10/11 через DWM API
    (DWMWA_USE_IMMERSIVE_DARK_MODE). На других ОС — ничего не делает.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        # 20 — Windows 11 и свежие сборки Win10; 19 — более старые сборки Win10
        for attr in (20, 19):
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
            if res == 0:
                break
        # мягкий перерисов заголовка, чтобы цвет применился сразу
        try:
            root.withdraw()
            root.deiconify()
        except Exception:
            pass
    except Exception:
        pass


def apply_theme(root) -> None:
    """Применяет текущую тему ко всему окну root и его потомкам."""
    t = palette()
    _cfg(root, bg=t["bg"])
    _apply_ttk(root, t)
    for child in root.winfo_children():
        _apply_one(child, t)
    _apply_titlebar(root, is_dark())


def theme_menu(menu) -> None:
    """Отдельно темизирует контекстное меню (меню не входят в winfo_children фреймов)."""
    _apply_one(menu, palette())
