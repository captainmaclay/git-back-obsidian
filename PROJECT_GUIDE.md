# Obsidian Autosync — Project Guide / Гайд по проекту

> Документ двуязычный: сначала русская версия, ниже — English version.
> Bilingual document: Russian version first, English version below.

---
---

# 🇷🇺 Русская версия

Приложение автоматически синхронизирует локальное хранилище Obsidian с
репозиторием на GitHub: следит за изменениями `.md`/`.json` файлов, с задержкой
собирает изменения и отправляет их через GitHub REST API, а также даёт GUI для
просмотра истории пушей, переключения веток и восстановления любой версии.

Точка входа — `main.py` в корне. Запуск: `python main.py`.

## Структура пакетов

```
main.py                     — точка входа: bootstrap → single-instance → логгер → GUI → фоновый watcher
core/                       — инфраструктура (не знает про GUI и синхронизацию)
  config.py                 — все пути, загрузка .env, токены, объект settings, DEBOUNCE
  logger.py                 — потокобезопасный логгер (консоль + файлы + GUI-колбэки)
  single_instance.py        — защита от повторного запуска (Mutex / lock-файл + PID)
  bootstrap.py              — подготовка структуры папок/файлов + чистка .env при старте
  env_sanitizer.py          — срезает пробелы в начале/конце значений в .env
  log_trim.py               — обрезка разросшихся лог-файлов
sync/                       — движок синхронизации и работы с GitHub
  watcher.py                — watchdog-обработчик, debounce, bootstrap первой ветки, init-push
  observer.py               — управление watchdog-наблюдателем (start/stop/restart)
  file_copier.py            — умное копирование изменённых файлов во временную папку
  push.py                   — ГЛАВНЫЙ push: сбор изменений + REST API + force-guard
  commit_description.py     — генерация описания коммита и отправка комментария
gui/                        — интерфейс (Tkinter)
  app.py                    — главное окно, вкладки, трей, фоновые задачи
  main_tab.py               — вкладка «Главная»: список пушей, clone, копирование
  settings_tab.py           — вкладка «Settings»: токен, папка, частота, сохранение в .env
  tray.py                   — иконка в трее, протокол закрытия, кнопка Exit, окно-дубль
  branches.py               — текущая ветка, список веток, окно выбора ветки
  version_ops.py            — clone версии, fetch пушей/комментариев, копирование SHA
```

Импорты абсолютные (`from core.config import ...`). Каждый пакет содержит `__init__.py`.

## Поток запуска (`main.py`) — что за чем

1. `import core.bootstrap` — при импорте выполняется `initialize_app_structure()`:
   создаёт папки (`fake_git_temp`, `Versions`), файлы логов, `settings.ini`, `.env`,
   **и сразу чистит `.env`** через `env_sanitizer`. Это происходит **до** шага 2.
2. `from core import config` — грузит `.env` (`dotenv`), вычисляет пути, собирает `settings`.
   Так как `.env` уже очищен на шаге 1, в конфиг попадают значения без «хвостовых» пробелов.
3. `ensure_env_file()` в `main.py` — дополняет `.env` недостающими ключами (все пустые).
4. `SingleInstance.acquire()` — если приложение уже запущено, показывает предупреждение и выходит.
5. `log_trim.main()` — подрезает большие логи.
6. `init_logger()` — включает реальный логгер (до этого работает «заглушка»).
7. `tk.Tk()` + `GitVersionRestoreApp(root)` — строит GUI.
8. Фоновый поток `start_observation()` → `start_watcher()` + `initial_check_loop()`.
9. `root.mainloop()`.

## Поток синхронизации (изменение файла → пуш) — подробно

```
изменение файла в хранилище
        │  watchdog (sync/observer.py)
        ▼
ChangeHandler.on_any_event (sync/watcher.py)
        │  ① фильтр IGNORED_DIRS (.git/.obsidian/…)
        │  ② если пуш уже идёт (_push_in_progress) — выходим
        ▼
schedule_push  →  debounce Timer(DEBOUNCE_SECONDS)     ③ гасит «шторм» правок
        ▼
safe_do_push:
        │  _push_in_progress = True
        │  stop_observer()          ④ чтобы git-операции не запустили новый пуш
        ▼
do_push() (sync/push.py)
        │  1. push_lock / push.lock            ⑤ защита от параллельных пушей
        │  2. проверка «fake_git_temp в пути»  ⑥ не работать не с той папкой
        │  3. clear_temp_repo_content          — чистим песочницу
        │  4. sync_changed_files()             — копируем изменённые .md/.json из хранилища
        │  5. collect_changes()                — сравнение с GitHub → added/modified/deleted
        │  6. guard пустого пуша               ⑦ нет изменений → выходим
        │  7. populate deleted_files/          — тянем содержимое удалённых файлов с remote
        │  8. initialize_repository()          — одноразовый git-репо, HEAD=main, checkout
        │  9. build index + tree (REST blobs)
        │ 10. CommitAnalyzer → описание коммита
        │ 11. github_api_force_push_from_tree() ⑧ FORCE-GUARD (см. ниже)
        │ 12. отложенный комментарий к коммиту (GitHubCommenter, +10 сек)
        ▼
finally: очистка песочницы, снятие локов, start_observer(), обрезка логов
```

Первичная инициализация (`safe_ensure_repository_and_main_branch`, `sync/watcher.py`):
открывает/создаёт локальный `Autosync_git`; если удалённый репо пуст (409) —
одноразовый bootstrap-push через CLI; затем pygit2-push ветки `main` — **под force-guard**.

## Защита от force push (force-guard) — ядро безопасности

Одна проверка на всё: `is_force_push_allowed()` в `sync/push.py`.

- `github_api_main_commit_count()` узнаёт число коммитов в `main`;
- коммитов **≤ 1** (только initial) → `force = True` разрешён;
- коммитов **> 1** (уже были пуши) → `force = False`;
- не удалось определить (сеть/таймаут) → `force = False` (безопасный дефолт).

Три места force-push, все закрыты этой проверкой:

| # | Где | Что делает без защиты | Как защищено |
|---|-----|-----------------------|--------------|
| 1 | `sync/push.py` `github_api_force_push_from_tree` | REST-push при каждой синхронизации | `force=allow_force`; коммит с `parents=[HEAD]` = fast-forward, проходит и без force; при 422 push отменяется |
| 2 | `sync/watcher.py` `safe_ensure_repository_and_main_branch` | init pygit2-push `+refs/heads/main` при старте | если `is_force_push_allowed()` False → push **пропускается** с логом `[INIT PUSH] ПРОПУЩЕН` |
| 3 | `sync/watcher.py` `bootstrap_force_push_cli` | `git push --force` при пустом репо | запускается только при 409; `github_repo_is_empty()` при сетевой ошибке возвращает `False` |

Смысл: force используется ровно один раз — на первом пуше в свежий репозиторий.
Как только в `main` появляется история, любой force блокируется, а обычная
синхронизация продолжает работать через fast-forward.

## Какой модуль от чего предохраняет (карта предохранителей)

| Риск / проблема | Что защищает | Где |
|-----------------|--------------|-----|
| Второй запуск приложения | `SingleInstance` (Mutex на Windows / lock-файл + проверка PID) | `core/single_instance.py` |
| Перезапись истории на сервере force-пушем | `is_force_push_allowed` / `github_api_main_commit_count` (≤1 коммита) | `sync/push.py` |
| Force init-push при старте на непустой репо | тот же guard в `safe_ensure_repository_and_main_branch` | `sync/watcher.py` |
| Force-bootstrap из-за сетевого сбоя | `github_repo_is_empty()` → `False` при ошибке | `sync/watcher.py` |
| Невидимые пробелы в `.env` ломают авторизацию | `sanitize_env_file` (при старте и после GUI-сохранения) | `core/env_sanitizer.py` |
| Параллельные пуши | `push_lock` (флаг) + `push.lock` (файл) + `_push_in_progress` | `sync/push.py`, `sync/watcher.py` |
| «Шторм» правок → лавина пушей | debounce `Timer(DEBOUNCE_SECONDS)` | `sync/watcher.py` |
| Петля: git-операции сами триггерят watcher | `stop_observer()` на время пуша + изоляция в `fake_git_temp` + `IGNORED_DIRS` | `sync/watcher.py`, `sync/observer.py` |
| Работа не с той папкой | guard `"fake_git_temp" not in path` → аварийный выход | `sync/push.py` |
| Плохие/обходные пути (`..`, `.git`, control-символы) | `is_malformed_path` / `normalize_path` | `sync/push.py` |
| Пустой/бессмысленный пуш | guard `not added and not modified and not deleted`; `added_count == 0` | `sync/push.py` |
| Битый репозиторий в песочнице | `initialize_repository` ловит `GitError`, удаляет `.git`, переинициализирует | `sync/push.py` |
| Временные сбои пуша (сеть/pygit2) | `PushRecoveryHandler` — повтор с задержкой | `sync/push.py` |
| Бесконтрольный рост логов | обрезка `>600 KB → ~400 KB` | `core/log_trim.py` |
| Нет структуры/`.env` на чистом окружении | `initialize_app_structure` | `core/bootstrap.py` |
| Наблюдатель «упал» | `watcher_loop` каждые 60 сек перезапускает | `sync/watcher.py` |

## Рабочие/служебные папки

- `fake_git_temp/` — временная песочница пуша: туда копируются изменённые файлы,
  собирается git-tree, лежит `deleted_files/`. Чистится до и после каждого пуша.
  По ней же GUI определяет текущую ветку. **Не мёртвая — центральная.**
- `Versions/` — клоны прошлых версий (кнопка Clone в GUI сохраняет сюда).
- `Autosync_git/` — локальный git-репозиторий для init-push при старте.
- `push_comments/` — служебная папка комментариев.

## Конфигурация (`core/config.py` + `.env`)

Ключи `.env`: `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN`, `WATCHED_FOLDER`,
`DEBOUNCE_MINUTES` (или `DEBOUNCE_SECONDS`).

Корень проекта = `Path(__file__).resolve().parents[1]` (на уровень выше `core/`) —
от него строятся все пути. Токен и логин **не захардкожены**: читаются из `.env`
через `os.getenv`, а в GUI приходят через `settings`.

## Справочник модулей

| Модуль | Ключевые символы | Кто использует |
|--------|------------------|----------------|
| `core/logger.py` | `init_logger`, `get_logger`, `log_main/soft/both` | все |
| `core/config.py` | `settings`, `GITHUB_*`, `WATCHED_FOLDER`, пути, `DEBOUNCE_SECONDS` | почти все |
| `core/single_instance.py` | `SingleInstance` | `main.py`, `gui/app.py` |
| `core/bootstrap.py` | `initialize_app_structure` (авто при импорте) | `main.py` |
| `core/env_sanitizer.py` | `sanitize_env_file` | `core/bootstrap.py`, `gui/settings_tab.py` |
| `core/log_trim.py` | `main()` (обрезка логов) | `main.py` |
| `sync/watcher.py` | `start_watcher`, `stop_watcher`, `initial_check_loop`, `ChangeHandler`, `safe_ensure_repository_and_main_branch` | `main.py`, `gui/app.py`, `gui/main_tab.py`, `sync/observer.py` |
| `sync/observer.py` | `start_observer`, `stop_observer`, `is_observer_running`, `restart_observer` | `sync/push.py`, `sync/watcher.py`, `main.py` |
| `sync/file_copier.py` | `SmartSyncCopier`, `sync_changed_files` | `sync/push.py` |
| `sync/push.py` | `do_push`, `is_force_push_allowed`, `github_api_*` | `sync/watcher.py` |
| `sync/commit_description.py` | `CommitAnalyzer`, `GitHubCommenter` | `sync/push.py` |
| `gui/app.py` | `GitVersionRestoreApp` | `main.py` |
| `gui/main_tab.py` | `MainTab` | `gui/app.py` |
| `gui/settings_tab.py` | `SettingsTab`, `SETTINGS_FILE` | `gui/app.py` |
| `gui/tray.py` | `setup_tray_and_close_protocol`, `create_exit_button`, `create_tray_icon`, `show_duplicate_warning` | `gui/app.py`, `main.py` |
| `gui/branches.py` | `get_current_branch`, `get_remote_branches`, `change_branch`, `create_branch_selector_button` | `gui/app.py`, `gui/main_tab.py` |
| `gui/version_ops.py` | `clone_version`, `open_versions`, `fetch_pushes`, `fetch_commit_comment`, `copy_push_sha` | `gui/main_tab.py` |

## Известные особенности

- `core/config.py` лениво импортирует `parse_diff_lines`/`run_logger_clean` из
  `sync/commit_description.py`, где их нет → штатный fallback на no-op (унаследовано).
- В `config.py` остались мёртвые записи `GIT_DIR` (алиас) и `DELETED_TEMP`
  (папка `fake_git_temp/deleted_temp` больше не используется — `do_push` работает с
  `deleted_files`). Создаются, но не читаются; можно убрать.
- Удалён мёртвый код: `main_core.py`, `main_func.py`, `main_func2.py`, пакет
  `filters/`, а также старая REST-реализация push из `git_gui_utils.py`.

---
---

# 🇬🇧 English version

The app automatically syncs a local Obsidian vault with a GitHub repository: it
watches `.md`/`.json` files, debounces edits, sends changes via the GitHub REST
API, and provides a GUI to browse push history, switch branches, and restore any
version.

Entry point — `main.py` at the root. Run: `python main.py`.

## Package structure

```
main.py                     — entry point: bootstrap → single-instance → logger → GUI → background watcher
core/                       — infrastructure (unaware of GUI and syncing)
  config.py                 — all paths, .env loading, tokens, settings object, DEBOUNCE
  logger.py                 — thread-safe logger (console + files + GUI callbacks)
  single_instance.py        — protection against a second launch (Mutex / lock-file + PID)
  bootstrap.py              — prepares folder/file structure + sanitizes .env on startup
  env_sanitizer.py          — strips leading/trailing spaces from .env values
  log_trim.py               — trims oversized log files
sync/                       — sync engine and GitHub integration
  watcher.py                — watchdog handler, debounce, first-branch bootstrap, init-push
  observer.py               — watchdog observer control (start/stop/restart)
  file_copier.py            — smart copy of changed files into the scratch folder
  push.py                   — MAIN push: change collection + REST API + force-guard
  commit_description.py     — commit description generation + comment posting
gui/                        — interface (Tkinter)
  app.py                    — main window, tabs, tray, background tasks
  main_tab.py               — "Main" tab: push list, clone, copy
  settings_tab.py           — "Settings" tab: token, folder, frequency, save to .env
  tray.py                   — tray icon, close protocol, Exit button, duplicate warning
  branches.py               — current branch, branch list, branch picker window
  version_ops.py            — clone version, fetch pushes/comments, copy SHA
```

Imports are absolute (`from core.config import ...`). Each package has `__init__.py`.

## Startup flow (`main.py`) — step by step

1. `import core.bootstrap` — on import runs `initialize_app_structure()`: creates
   folders (`fake_git_temp`, `Versions`), log files, `settings.ini`, `.env`, **and
   immediately sanitizes `.env`** via `env_sanitizer`. This happens **before** step 2.
2. `from core import config` — loads `.env` (`dotenv`), computes paths, builds
   `settings`. Because `.env` is already cleaned, config gets space-free values.
3. `ensure_env_file()` in `main.py` — appends any missing keys (all empty).
4. `SingleInstance.acquire()` — if the app is already running, shows a warning and exits.
5. `log_trim.main()` — trims large logs.
6. `init_logger()` — enables the real logger (a stub is used before that).
7. `tk.Tk()` + `GitVersionRestoreApp(root)` — builds the GUI.
8. Background thread `start_observation()` → `start_watcher()` + `initial_check_loop()`.
9. `root.mainloop()`.

## Sync flow (file change → push) — in detail

```
file change in the vault
        │  watchdog (sync/observer.py)
        ▼
ChangeHandler.on_any_event (sync/watcher.py)
        │  ① IGNORED_DIRS filter (.git/.obsidian/…)
        │  ② if a push is already running (_push_in_progress) — return
        ▼
schedule_push  →  debounce Timer(DEBOUNCE_SECONDS)     ③ absorbs edit "storms"
        ▼
safe_do_push:
        │  _push_in_progress = True
        │  stop_observer()          ④ so git operations don't trigger a new push
        ▼
do_push() (sync/push.py)
        │  1. push_lock / push.lock            ⑤ guards against concurrent pushes
        │  2. "fake_git_temp in path" check    ⑥ never operate on the wrong folder
        │  3. clear_temp_repo_content          — wipe the scratch folder
        │  4. sync_changed_files()             — copy changed .md/.json from the vault
        │  5. collect_changes()                — diff vs GitHub → added/modified/deleted
        │  6. empty-push guard                 ⑦ no changes → return
        │  7. populate deleted_files/          — fetch deleted files' content from remote
        │  8. initialize_repository()          — throwaway git repo, HEAD=main, checkout
        │  9. build index + tree (REST blobs)
        │ 10. CommitAnalyzer → commit description
        │ 11. github_api_force_push_from_tree() ⑧ FORCE-GUARD (see below)
        │ 12. deferred commit comment (GitHubCommenter, +10 s)
        ▼
finally: wipe scratch, release locks, start_observer(), trim logs
```

First-time init (`safe_ensure_repository_and_main_branch`, `sync/watcher.py`):
opens/creates the local `Autosync_git`; if the remote repo is empty (409) — a
one-off CLI bootstrap push; then a pygit2 push of `main` — **under the force-guard**.

## Force-push protection (force-guard) — the safety core

One check for everything: `is_force_push_allowed()` in `sync/push.py`.

- `github_api_main_commit_count()` reads the number of commits on `main`;
- **≤ 1** commit (initial only) → `force = True` allowed;
- **> 1** commits (history exists) → `force = False`;
- undetermined (network/timeout) → `force = False` (safe default).

Three force-push sites, all covered by this check:

| # | Where | Unprotected behavior | How it is protected |
|---|-------|----------------------|---------------------|
| 1 | `sync/push.py` `github_api_force_push_from_tree` | REST push on every sync | `force=allow_force`; commit has `parents=[HEAD]` = fast-forward, passes even without force; on 422 the push is cancelled |
| 2 | `sync/watcher.py` `safe_ensure_repository_and_main_branch` | init pygit2 push `+refs/heads/main` on startup | if `is_force_push_allowed()` is False → push is **skipped** with `[INIT PUSH] SKIPPED` log |
| 3 | `sync/watcher.py` `bootstrap_force_push_cli` | `git push --force` on empty repo | runs only on 409; `github_repo_is_empty()` returns `False` on network error |

Meaning: force is used exactly once — the very first push into a fresh repo. Once
`main` has history, any force is blocked, while normal syncing keeps working via
fast-forward.

## What each module protects against (safety map)

| Risk / problem | Protector | Where |
|----------------|-----------|-------|
| Second app launch | `SingleInstance` (Windows Mutex / lock-file + PID check) | `core/single_instance.py` |
| Overwriting remote history via force | `is_force_push_allowed` / `github_api_main_commit_count` (≤1 commit) | `sync/push.py` |
| Force init-push on a non-empty repo at startup | same guard in `safe_ensure_repository_and_main_branch` | `sync/watcher.py` |
| Force-bootstrap due to a network glitch | `github_repo_is_empty()` → `False` on error | `sync/watcher.py` |
| Invisible spaces in `.env` breaking auth | `sanitize_env_file` (startup + after GUI save) | `core/env_sanitizer.py` |
| Concurrent pushes | `push_lock` (flag) + `push.lock` (file) + `_push_in_progress` | `sync/push.py`, `sync/watcher.py` |
| Edit "storm" → push avalanche | debounce `Timer(DEBOUNCE_SECONDS)` | `sync/watcher.py` |
| Loop: git ops re-trigger the watcher | `stop_observer()` during push + `fake_git_temp` isolation + `IGNORED_DIRS` | `sync/watcher.py`, `sync/observer.py` |
| Operating on the wrong folder | guard `"fake_git_temp" not in path` → abort | `sync/push.py` |
| Bad/traversal paths (`..`, `.git`, control chars) | `is_malformed_path` / `normalize_path` | `sync/push.py` |
| Empty/meaningless push | guard `not added and not modified and not deleted`; `added_count == 0` | `sync/push.py` |
| Corrupt scratch repo | `initialize_repository` catches `GitError`, deletes `.git`, re-inits | `sync/push.py` |
| Transient push failures (network/pygit2) | `PushRecoveryHandler` — retry with delay | `sync/push.py` |
| Unbounded log growth | trim `>600 KB → ~400 KB` | `core/log_trim.py` |
| Missing structure/`.env` on a clean environment | `initialize_app_structure` | `core/bootstrap.py` |
| Observer "died" | `watcher_loop` restarts it every 60 s | `sync/watcher.py` |

## Working / service folders

- `fake_git_temp/` — the push scratch sandbox: changed files are copied here, the
  git tree is assembled, `deleted_files/` lives here. Wiped before and after every
  push. The GUI also reads the current branch from it. **Not dead — central.**
- `Versions/` — clones of previous versions (the GUI Clone button saves here).
- `Autosync_git/` — local git repo used for the startup init-push.
- `push_comments/` — service folder for comments.

## Configuration (`core/config.py` + `.env`)

`.env` keys: `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN`, `WATCHED_FOLDER`,
`DEBOUNCE_MINUTES` (or `DEBOUNCE_SECONDS`).

Project root = `Path(__file__).resolve().parents[1]` (one level above `core/`) —
all paths derive from it. Token and login are **not hardcoded**: read from `.env`
via `os.getenv`, and reach the GUI through `settings`.

## Module reference

| Module | Key symbols | Used by |
|--------|-------------|---------|
| `core/logger.py` | `init_logger`, `get_logger`, `log_main/soft/both` | everyone |
| `core/config.py` | `settings`, `GITHUB_*`, `WATCHED_FOLDER`, paths, `DEBOUNCE_SECONDS` | almost everyone |
| `core/single_instance.py` | `SingleInstance` | `main.py`, `gui/app.py` |
| `core/bootstrap.py` | `initialize_app_structure` (auto on import) | `main.py` |
| `core/env_sanitizer.py` | `sanitize_env_file` | `core/bootstrap.py`, `gui/settings_tab.py` |
| `core/log_trim.py` | `main()` (log trimming) | `main.py` |
| `sync/watcher.py` | `start_watcher`, `stop_watcher`, `initial_check_loop`, `ChangeHandler`, `safe_ensure_repository_and_main_branch` | `main.py`, `gui/app.py`, `gui/main_tab.py`, `sync/observer.py` |
| `sync/observer.py` | `start_observer`, `stop_observer`, `is_observer_running`, `restart_observer` | `sync/push.py`, `sync/watcher.py`, `main.py` |
| `sync/file_copier.py` | `SmartSyncCopier`, `sync_changed_files` | `sync/push.py` |
| `sync/push.py` | `do_push`, `is_force_push_allowed`, `github_api_*` | `sync/watcher.py` |
| `sync/commit_description.py` | `CommitAnalyzer`, `GitHubCommenter` | `sync/push.py` |
| `gui/app.py` | `GitVersionRestoreApp` | `main.py` |
| `gui/main_tab.py` | `MainTab` | `gui/app.py` |
| `gui/settings_tab.py` | `SettingsTab`, `SETTINGS_FILE` | `gui/app.py` |
| `gui/tray.py` | `setup_tray_and_close_protocol`, `create_exit_button`, `create_tray_icon`, `show_duplicate_warning` | `gui/app.py`, `main.py` |
| `gui/branches.py` | `get_current_branch`, `get_remote_branches`, `change_branch`, `create_branch_selector_button` | `gui/app.py`, `gui/main_tab.py` |
| `gui/version_ops.py` | `clone_version`, `open_versions`, `fetch_pushes`, `fetch_commit_comment`, `copy_push_sha` | `gui/main_tab.py` |

## Known quirks

- `core/config.py` lazily imports `parse_diff_lines`/`run_logger_clean` from
  `sync/commit_description.py`, where they don't exist → a built-in no-op fallback
  (inherited behavior).
- `config.py` still has dead entries `GIT_DIR` (alias) and `DELETED_TEMP` (the
  `fake_git_temp/deleted_temp` folder is no longer used — `do_push` works with
  `deleted_files`). They are created but never read; can be removed.
- Removed dead code: `main_core.py`, `main_func.py`, `main_func2.py`, the `filters/`
  package, and the old REST push implementation from `git_gui_utils.py`.
