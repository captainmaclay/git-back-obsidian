# Obsidian Autosync — Project Guide / Гайд по проекту

---

# 🇬🇧 English version

## 1. Purpose and applicability

**What it is.** A desktop app with a convenient GUI for quickly setting up
**auto-pushes of Obsidian notes from a folder (including a network/cloud folder —
OneDrive, Google Drive, etc.) to GitHub**. You configure token, repository and vault
folder once in the GUI; the app then watches `.md`/`.json` changes and pushes them to
GitHub with meaningful commits and comments.

**Problem it solves.** Obsidian stores notes locally; manual git backup is inconvenient
(remembering add/commit/push, knowing git, tracking branches). This app turns any notes
folder into an automatically versioned GitHub repository — **without a single git command
from the user**.

**Who it's for.**
- Obsidian users who want automatic backup and version history of notes.
- Those whose vault lives in a **network/cloud folder** (OneDrive, etc.) — the app handles
  cloud-sync latency well (operations are parallelized).
- Anyone who wants to **roll back to any previous version** of their notes.

**Key features.**
- Automatic folder watching (watchdog) with edit-storm protection (debounce).
- Push to GitHub via **REST API with a token** (no local git required).
- **GUI configuration**: token (hidden), login, repo name, vault folder, check frequency —
  saved to `.env`.
- **Empty-repository initialization** with a first commit (see §6) — works even on a
  brand-new empty repo.
- Push list, commit comment view, **version restore** (clone), branch selection.
- Tray minimize, start-minimized, single-instance protection.
- History safety: **force-push allowed only for a fresh repo** (see §7).

**Boundaries.**
- Only `.md`/`.json` files are tracked (plus deleted files' content).
- Not a full git client; auto-push works on the `main` branch.
- Requires a GitHub Personal Access Token with `repo` scope.

## 2. How to run

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
pip install -r requirements.txt
python -c "import core.bootstrap"     # creates .env and folder structure
python main.py
```

Fill in `.env` (or the **Settings** tab): `GITHUB_USERNAME`, `GITHUB_REPO`,
`GITHUB_TOKEN`, `WATCHED_FOLDER`. `start.bat` also works
(`cd /d "%~dp0"` + `.venv\Scripts\pythonw.exe main.py`).

## 3. Package structure

```
main.py                     — entry: bootstrap → single-instance → logger → GUI → background watcher
core/                       — infrastructure (unaware of GUI and syncing)
  config.py                 — paths, .env loading, tokens, settings, DEBOUNCE, is_github_configured()
  logger.py                 — thread-safe logger (console + files + GUI callbacks)
  single_instance.py        — second-launch protection (Mutex / lock-file + PID)
  bootstrap.py              — prepares structure + sanitizes .env on startup
  env_sanitizer.py          — strips leading/trailing spaces from .env values
  log_trim.py               — trims oversized logs
sync/                       — sync engine and GitHub integration
  watcher.py                — watchdog handler, debounce; lightweight init (REST prepares the repo)
  observer.py               — watchdog observer control (start/stop/restart)
  file_copier.py            — PARALLEL copy of changed files into the scratch folder
  push.py                   — MAIN push: empty-repo init + change collection + REST + force-guard
  commit_description.py     — commit description generation + comment posting
gui/                        — interface (Tkinter)
  app.py                    — main window, tabs, tray, background tasks
  main_tab.py               — "Main" tab: push list, clone, copy
  settings_tab.py           — "Settings" tab: token, folder, frequency, save to .env
  tray.py                   — tray icon, close protocol, Exit button, duplicate warning
  branches.py               — current branch, branch list, branch picker window
  version_ops.py            — clone version, fetch pushes/comments, copy SHA
```

## 4. Startup flow (`main.py`) — step by step

1. `import core.bootstrap` — runs `initialize_app_structure()`: creates folders
   (`fake_git_temp`, `Versions`), log files, `settings.ini`, `.env`, and **immediately
   sanitizes `.env`**. Happens **before** step 2.
2. `from core import config` — loads `.env`, computes paths from project root
   (`parents[1]`), builds `settings`. Values are already space-free.
3. `ensure_env_file()` in `main.py` — appends missing keys (all empty).
4. `SingleInstance.acquire()` — exits with a warning if already running.
5. `log_trim.main()` — trims large logs.
6. `init_logger()` — enables the real logger (a stub is used before that).
7. `tk.Tk()` + `GitVersionRestoreApp(root)` — builds the GUI.
8. Background thread `start_observation()` → `start_watcher()` + `initial_check_loop()`.
9. `root.mainloop()`.

## 5. Sync flow (file change → push)

```
file change in the vault
        │  watchdog (sync/observer.py)
        ▼
ChangeHandler.on_any_event (sync/watcher.py)
        │  ① IGNORED_DIRS filter        ② skip if a push is already running
        ▼
schedule_push → debounce Timer(DEBOUNCE_SECONDS)    ③ absorbs edit storms
        ▼
safe_do_push: _push_in_progress=True; stop_observer()   ④ git ops don't re-trigger
        ▼
do_push() (sync/push.py)
        │  1. is_github_configured()                 ⑤ not configured → clear log, return
        │  2. github_api_ensure_repo_initialized()   ⑥ empty repo → first commit (Contents API)
        │  3. push_lock / push.lock                  ⑦ concurrent-push guard
        │  4. "fake_git_temp in path" check          ⑧ never operate on the wrong folder
        │  5. sync_changed_files()                   — PARALLEL copy of .md/.json into scratch
        │  6. collect_changes()                      — diff vs GitHub → added/modified/deleted
        │  7. empty-push guard                        ⑨ no changes → return
        │  8. populate deleted_files/                 — fetch deleted files' content from remote
        │  9. CommitAnalyzer → commit description
        │ 10. github_api_create_tree_from_folder()    — PARALLEL blob upload → tree
        │ 11. github_api_force_push_from_tree()        ⑩ FORCE-GUARD (see §7)
        │ 12. deferred commit comment (+10 s)
        ▼
finally: wipe scratch, release locks, start_observer(), trim logs
```

## 6. Empty-repository initialization (key case)

**Problem.** GitHub's low-level **Git Data API** (`/git/blobs`, `/git/trees`,
`/git/commits`) **does not work on a repository with zero commits** — it returns
`409 "Git Repository is empty"`. Moreover, `/git/ref/heads/main` on an empty repo also
returns `409` (sometimes `404`). So you cannot build a tree and push into a freshly
created empty repository directly.

**Solution (`sync/push.py`).**
- `github_api_main_ref()` reports `main` state:
  `exists` / `absent` (404 **or 409** = empty) / `unknown` (network).
- `github_api_ensure_repo_initialized()` runs in `do_push` **before** building the tree:
  - `exists` → does nothing;
  - `absent` → creates the **first commit via Contents API** (`PUT /contents/.gitkeep`) —
    the only endpoint that works on an empty repo; it creates the commit and branch `main`;
  - `unknown` → returns `False`, push is cancelled (no risk on a network blip).
- Afterwards the repo is non-empty and the normal blobs/trees/commit flow works.
  The `.gitkeep` placeholder is replaced by the full file tree in the second commit.

Result: auto-push works even on a brand-new empty repo — no manual
`git init … git push -u origin main` needed.

## 7. Force-push protection (force-guard)

One check for everything: `is_force_push_allowed()` in `sync/push.py`.

- `github_api_main_commit_count()` reads the number of commits on `main`;
- **≤ 1** commit → `force = True` allowed; **> 1** → `force = False`;
- undetermined (network) → `force = False` (safe default).

Force is used exactly once — the first push into a fresh repo. Once `main` has history,
any force is blocked while normal syncing works via fast-forward (a new commit always has
`parents=[current_head]`). On a non-fast-forward update GitHub returns `422` and the push
is cancelled without overwriting history.

## 8. Parallelism (speedup)

Two heavy stages use `ThreadPoolExecutor` (both I/O-bound):

- **Copy into scratch** (`sync/file_copier.py`): all files are copied/hashed at once.
  Small win on a local SSD; on a cloud folder (OneDrive) the speedup is roughly the
  number of threads.
- **Blob upload to GitHub** (`sync/push.py`, `github_api_create_tree_from_folder`): each
  file uploads in its own thread (`BLOB_UPLOAD_WORKERS = 8`) with a light retry. This is
  the main push-time win on large file sets (~7–8× in tests).

## 9. What each module protects against (safety map)

| Risk / problem | Protector | Where |
|----------------|-----------|-------|
| Second app launch | `SingleInstance` (Mutex / lock-file + PID) | `core/single_instance.py` |
| GitHub not configured → 404 /repos/// and cryptic errors | `is_github_configured()` guard | `core/config.py`, `sync/push.py`, `sync/watcher.py` |
| Empty repo (Git Data API returns 409) | `github_api_ensure_repo_initialized()` (Contents API) | `sync/push.py` |
| Overwriting history via force | `is_force_push_allowed()` (≤1 commit) | `sync/push.py` |
| Force due to a network glitch | `main_ref`='unknown' → cancel; `ensure`=False | `sync/push.py` |
| Invisible spaces in `.env` breaking auth | `sanitize_env_file` | `core/env_sanitizer.py` |
| Concurrent pushes | `push_lock` + `push.lock` + `_push_in_progress` | `sync/push.py`, `sync/watcher.py` |
| Edit storm → push avalanche | debounce `Timer(DEBOUNCE_SECONDS)` | `sync/watcher.py` |
| Loop: git ops re-trigger the watcher | `stop_observer()` during push + scratch + `IGNORED_DIRS` | `sync/watcher.py`, `sync/observer.py` |
| Operating on the wrong folder | guard `"fake_git_temp" not in path` | `sync/push.py` |
| Bad/traversal paths (`..`, `.git`) | `is_malformed_path` / `normalize_path` | `sync/push.py` |
| Empty/meaningless push | guard `not added and not modified and not deleted` | `sync/push.py` |
| Corrupt scratch repo | `initialize_repository` (catches `GitError`, re-inits) | `sync/push.py` |
| Transient network failures on push | `PushRecoveryHandler` + blob retries | `sync/push.py` |
| Unbounded log growth | trim `>600 KB → ~400 KB` | `core/log_trim.py` |
| Missing structure/`.env` on a clean env | `initialize_app_structure` | `core/bootstrap.py` |
| Observer "died" | `watcher_loop` restarts it every 60 s | `sync/watcher.py` |

## 10. Detailed module reference (by file and case)

### core/logger.py
Thread-safe logger. `init_logger()` once in `main`; `get_logger()` returns a stub before
init (prints to stderr). `log_main/soft/both/debug` write to console + files and, via a
queue, to GUI callbacks. Case: logs from background threads reach the GUI safely.

### core/config.py
Single source of paths and settings. Project root = `parents[1]` of `core/`. Loads `.env`.
Exports `settings`, `GITHUB_*`, `WATCHED_FOLDER`, `DEBOUNCE_SECONDS`, paths.
**`is_github_configured()`** — the guard (login/repo/token all set).
`save_watched_folder()` — persists the folder to `.env`.

### core/single_instance.py
`SingleInstance` — prevents a second instance: Windows global Mutex; Linux/macOS lock-file
+ PID check (psutil) + TTL for stale locks.

### core/bootstrap.py
`initialize_app_structure()` (auto on import) — creates folders/logs/`settings.ini`/`.env`
and **sanitizes `.env`** before `config` loads. Case: clean install.

### core/env_sanitizer.py
`sanitize_env_file(path)` — strips leading/trailing spaces from keys and values (including
inside quotes), preserving inner spaces (paths) and comments. Case: a trailing space in the
token used to break auth; now cleaned on startup and after GUI save.

### core/log_trim.py
`trim_log_file` / `main()` — if a log exceeds 600 KB, trims from the top to ~400 KB via a
temp file. Case: logs don't grow forever.

### sync/observer.py
watchdog observer control: `start_observer`/`stop_observer`/`is_observer_running`/
`restart_observer`. `ChangeHandler` is imported locally (breaks the cycle with `watcher`).
Case: a push stops the observer to avoid catching its own writes, then restarts it.

### sync/watcher.py
- `ChangeHandler.on_any_event` — reacts to changes, filters ignores, won't push over a push.
- `schedule_push` — debounce timer; `safe_do_push` — `stop_observer → do_push → start_observer`.
- `watcher_loop` — restarts a dead observer every 60 s.
- `safe_ensure_repository_and_main_branch` — **lightweight** (config check only): real
  empty-repo init moved to REST (`sync/push.py`). No more CLI bootstrap or pygit2 init-push
  (the latter caused `failed to set credentials`).
- `initial_check_loop` — reports watcher/observer/GitHub status after 25 s.

### sync/file_copier.py
`SmartSyncCopier` — smart **parallel** copy from vault to scratch: only new/changed files
(size + hash + mtime), preserving folder structure. `sync_changed_files` — the wrapper
called from `do_push`. Case: a cloud folder with hundreds of files is copied concurrently.

### sync/push.py (core)
- `do_push()` — orchestrates the whole push (steps in §5).
- `github_api_main_ref()` — `main` state: exists/absent(404/409)/unknown.
- `github_api_ensure_repo_initialized()` — first commit of an empty repo via Contents API.
- `collect_changes()` — diff scratch vs remote → added/modified/deleted.
- `github_api_create_tree_from_folder()` + `_upload_single_blob()` — **parallel** blob
  upload and tree assembly.
- `github_api_force_push_from_tree()` — commit + `main` update under the **force-guard**.
- `is_force_push_allowed()` / `github_api_main_commit_count()` — the force rule.
- `initialize_repository()` — local throwaway repo in scratch (pygit2).
- `is_malformed_path` / `normalize_path` / `should_include_in_tree_and_index` — path filters.
- `PushRecoveryHandler` — recovery from recoverable errors.

### sync/commit_description.py
`CommitAnalyzer.generate_commit_description` — builds a human-readable commit description
(only actually changed lines, with diff). `GitHubCommenter.post_to_commit` — posts it as a
commit comment. Case: GitHub history shows exactly what changed.

### gui/app.py
`GitVersionRestoreApp` — main window: tabs (Main/SoftLogger/Settings), tray, single-instance,
logger-to-GUI binding, background tasks (periodic push-list refresh and branch-change check).

### gui/main_tab.py
`MainTab` — "Main" tab: push list (`fetch_pushes`), commit selection and comment view,
`clone_selected_version` (version restore), copy SHA/profile, branch selector. Case: view
history and restore any version.

### gui/settings_tab.py
`SettingsTab` — token (hidden), login, repo, folder (dialog), frequency (minutes). Saving
writes everything to `.env` and **calls the sanitizer**. "Start Minimized" toggle. Case:
quick setup without editing files.

### gui/tray.py
`setup_tray_and_close_protocol`, `create_tray_icon`, `create_exit_button`,
`show_duplicate_warning` — tray, close-to-tray, full exit, duplicate-launch popup.

### gui/branches.py
`get_current_branch` (reads scratch HEAD), `get_remote_branches` (via API), `change_branch`,
`BranchSelectorWindow`, `create_branch_selector_button`. Case: switch/view branches from GUI.

### gui/version_ops.py
`clone_version` (clone a version into `Versions/`), `open_versions`, `fetch_pushes`
(commit list; **409 = empty repo** handled quietly), `fetch_commit_comment`, `copy_push_sha`.

## 11. Scenarios (cases), step by step

1. **Clean install / first launch.** `core/bootstrap` creates folders, `.env`,
   `settings.ini`; logger starts; GUI opens; watcher starts. While `.env` is empty,
   `is_github_configured()` = False and pushes are skipped with a clear message.
2. **Configure in GUI.** In Settings, enter login/repo/token/folder → saved to `.env` +
   spaces cleaned. The next file change triggers a push.
3. **Empty repo → first commit.** First file change: `do_push` sees `main` = absent (409)
   → `PUT /contents/.gitkeep` creates the first commit and branch → then the normal flow
   uploads all files.
4. **Normal edit.** Edit a `.md` → debounce → copy into scratch → diff vs GitHub → parallel
   blob upload → commit on top of `main` (fast-forward) → description comment.
5. **Many files / cloud folder.** Copy and upload run in parallel — push time is far lower
   than sequential.
6. **File deletion.** `collect_changes` sees the file missing locally → fetches its content
   from remote into `deleted_files/` (for the description) and records the deletion in the tree.
7. **Divergence / overwrite attempt.** If `main` already has history, force is disallowed; a
   non-fast-forward push is rejected (422) — history stays intact.
8. **No network.** `main_ref` = unknown or timeouts → push is cancelled cleanly, with retries;
   no erroneous force/bootstrap.
9. **GitHub not configured.** Every API path is gated by `is_github_configured()` — one clear
   log instead of 404 spam.
10. **Branch switch in GUI.** `branches` switches the scratch branch; the push list refreshes
    for the selected branch.
11. **Version restore.** In "Main", pick a SHA → `clone_version` clones that version into
    `Versions/`.
12. **Second launch.** `SingleInstance` blocks a second instance — popup and exit.

## 12. Configuration (`.env`)

Keys: `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN`, `WATCHED_FOLDER`,
`DEBOUNCE_MINUTES` (or `DEBOUNCE_SECONDS`). Login/repo/token are **not hardcoded** — read
from `.env` via `os.getenv`. The token needs `repo` scope.

## 13. Working / service folders

- `fake_git_temp/` — the push scratch sandbox (file copy, tree assembly, `deleted_files/`);
  wiped before/after each push; the GUI also reads the current branch from it.
- `Versions/` — clones of previous versions (Clone button).
- `Autosync_git/` — a local git repo (leftover from the older scheme; not needed for REST push).
- `push_comments/` — a service folder.

## 14. Known quirks

- `core/config.py` lazily imports `parse_diff_lines`/`run_logger_clean` from
  `sync/commit_description.py`, where they don't exist → a built-in no-op fallback (inherited).
- `config.py` still has formally dead `GIT_DIR` and `DELETED_TEMP` (unused).
- The local pygit2 index work in `do_push` (`initialize_repository`) is now mostly idle: the
  GitHub tree is rebuilt from files, not from the index.
- Removed dead code: `main_core.py`, `main_func*.py`, the `filters/` package, the old CLI
  bootstrap and pygit2 init-push.


---
---

# 🇷🇺 Русская версия

## 1. Назначение и применимость

**Что это.** Настольное приложение с удобным графическим интерфейсом для быстрой
настройки **авто-пушей заметок Obsidian из папки (в том числе сетевой/облачной —
OneDrive, Google Drive и т.п.) на GitHub**. Пользователь один раз указывает в GUI
токен, репозиторий и папку хранилища — дальше приложение само отслеживает изменения
`.md`/`.json` и отправляет их на GitHub с осмысленными коммитами и комментариями.

**Какую проблему решает.** Obsidian хранит заметки локально; ручной бэкап через git
неудобен (нужно помнить про add/commit/push, знать git, следить за ветками). Это
приложение превращает любую папку с заметками в автоматически версионируемое
хранилище на GitHub — **без единой git-команды со стороны пользователя**.

**Для кого.**
- Пользователи Obsidian, желающие автоматический бэкап и историю версий заметок.
- Те, у кого vault лежит в **сетевой/облачной папке** (OneDrive и пр.) — приложение
  корректно работает с задержками облачной синхронизации (операции распараллелены).
- Кому нужна возможность **откатиться к любой прошлой версии** заметок.

**Ключевые возможности.**
- Автоматическое отслеживание выбранной папки (watchdog) с защитой от «шторма» правок
  (debounce).
- Пуш на GitHub через **REST API токеном** (без установленного git на машине).
- **GUI-настройка**: токен (со скрытием), логин, имя репозитория, папка хранилища,
  частота проверки — всё сохраняется в `.env`.
- **Инициализация пустого репозитория** первым коммитом (см. раздел 6) — работает даже
  на только что созданном пустом репо.
- Список пушей, просмотр комментария коммита, **восстановление любой версии** (clone),
  выбор ветки.
- Свёртывание в системный трей, автозапуск в свёрнутом виде, защита от повторного
  запуска.
- Защита истории: **force-push разрешён только для свежего репозитория** (см. раздел 7).

**Границы применимости.**
- Отслеживаются только файлы `.md` и `.json` (и содержимое удалённых из них).
- Это не полноценный git-клиент; авто-пуш работает с веткой `main`.
- Для отправки нужен GitHub Personal Access Token со scope `repo`.

## 2. Как запустить

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
pip install -r requirements.txt
python -c "import core.bootstrap"     # создаёт .env и структуру папок
python main.py
```

Заполнить `.env` (или вкладку **Settings** в GUI): `GITHUB_USERNAME`, `GITHUB_REPO`,
`GITHUB_TOKEN`, `WATCHED_FOLDER`. Запуск также возможен через `start.bat`
(`cd /d "%~dp0"` + `.venv\Scripts\pythonw.exe main.py`).

## 3. Структура пакетов

```
main.py                     — точка входа: bootstrap → single-instance → логгер → GUI → фоновый watcher
core/                       — инфраструктура (не знает про GUI и синхронизацию)
  config.py                 — пути, загрузка .env, токены, settings, DEBOUNCE, is_github_configured()
  logger.py                 — потокобезопасный логгер (консоль + файлы + GUI-колбэки)
  single_instance.py        — защита от повторного запуска (Mutex / lock-файл + PID)
  bootstrap.py              — подготовка структуры папок/файлов + чистка .env при старте
  env_sanitizer.py          — срезает пробелы в начале/конце значений в .env
  log_trim.py               — обрезка разросшихся лог-файлов
sync/                       — движок синхронизации и работы с GitHub
  watcher.py                — watchdog-обработчик, debounce; лёгкий init (репо готовит REST)
  observer.py               — управление watchdog-наблюдателем (start/stop/restart)
  file_copier.py            — ПАРАЛЛЕЛЬНОЕ копирование изменённых файлов в песочницу
  push.py                   — ГЛАВНЫЙ push: init пустого репо + сбор изменений + REST + force-guard
  commit_description.py     — генерация описания коммита и отправка комментария
gui/                        — интерфейс (Tkinter)
  app.py                    — главное окно, вкладки, трей, фоновые задачи
  main_tab.py               — вкладка «Главная»: список пушей, clone, копирование
  settings_tab.py           — вкладка «Settings»: токен, папка, частота, сохранение в .env
  tray.py                   — иконка в трее, протокол закрытия, кнопка Exit, окно-дубль
  branches.py               — текущая ветка, список веток, окно выбора ветки
  version_ops.py            — clone версии, fetch пушей/комментариев, копирование SHA
```

## 4. Поток запуска (`main.py`) — что за чем

1. `import core.bootstrap` — при импорте выполняется `initialize_app_structure()`:
   создаёт папки (`fake_git_temp`, `Versions`), файлы логов, `settings.ini`, `.env`,
   **и сразу чистит `.env`** через `env_sanitizer`. Это происходит **до** шага 2.
2. `from core import config` — грузит `.env` (`dotenv`), вычисляет пути от корня проекта
   (`Path(__file__).resolve().parents[1]`), собирает `settings`. Значения уже без пробелов.
3. `ensure_env_file()` в `main.py` — дополняет `.env` недостающими ключами (все пустые).
4. `SingleInstance.acquire()` — если приложение уже запущено, показывает предупреждение и выходит.
5. `log_trim.main()` — подрезает большие логи.
6. `init_logger()` — включает реальный логгер (до этого работает «заглушка»).
7. `tk.Tk()` + `GitVersionRestoreApp(root)` — строит GUI.
8. Фоновый поток `start_observation()` → `start_watcher()` + `initial_check_loop()`.
9. `root.mainloop()`.

## 5. Поток синхронизации (изменение файла → пуш)

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
safe_do_push:  _push_in_progress=True; stop_observer()  ④ git-операции не триггерят пуш
        ▼
do_push() (sync/push.py)
        │  1. is_github_configured()                  ⑤ нет токена/репо → выходим с понятным логом
        │  2. github_api_ensure_repo_initialized()    ⑥ пустой репо → первый коммит (Contents API)
        │  3. push_lock / push.lock                   ⑦ защита от параллельных пушей
        │  4. проверка «fake_git_temp в пути»         ⑧ не работать не с той папкой
        │  5. sync_changed_files()                    — ПАРАЛЛЕЛЬНОЕ копирование .md/.json в песочницу
        │  6. collect_changes()                       — сравнение с GitHub → added/modified/deleted
        │  7. guard пустого пуша                       ⑨ нет изменений → выходим
        │  8. populate deleted_files/                  — тянем содержимое удалённых файлов с remote
        │  9. CommitAnalyzer → описание коммита
        │ 10. github_api_create_tree_from_folder()     — ПАРАЛЛЕЛЬНАЯ заливка blob'ов → tree
        │ 11. github_api_force_push_from_tree()         ⑩ FORCE-GUARD (см. раздел 7)
        │ 12. отложенный комментарий к коммиту (GitHubCommenter, +10 сек)
        ▼
finally: очистка песочницы, снятие локов, start_observer(), обрезка логов
```

## 6. Инициализация пустого репозитория (важный кейс)

**Проблема.** Низкоуровневый **Git Data API** GitHub (`/git/blobs`, `/git/trees`,
`/git/commits`) **не работает на репозитории без единого коммита** — возвращает
`409 "Git Repository is empty"`. Более того, `/git/ref/heads/main` на пустом репо тоже
отдаёт `409` (иногда `404`). Поэтому «в лоб» собрать дерево и запушить в свежесозданный
пустой репозиторий нельзя.

**Решение (в `sync/push.py`).**
- `github_api_main_ref()` определяет состояние ветки `main`:
  `exists` (есть коммит) / `absent` (404 **или 409** → репо пуст) / `unknown` (сеть).
- `github_api_ensure_repo_initialized()` вызывается в `do_push` **до** сборки дерева:
  - `exists` → ничего не делает;
  - `absent` → создаёт **первый коммит через Contents API** (`PUT /contents/.gitkeep`) —
    это единственный эндпоинт, работающий на пустом репо; он создаёт коммит и ветку `main`;
  - `unknown` → возвращает `False`, и push отменяется (не рискуем на обрыве сети).
- После этого репозиторий непустой, и обычный поток blobs/trees/commit работает.
  Плейсхолдер `.gitkeep` заменяется полным деревом файлов уже вторым коммитом.

Итог: авто-пуш работает даже на только что созданном пустом репозитории — отдельная
ручная последовательность `git init … git push -u origin main` не нужна.

## 7. Защита от force push (force-guard)

Одна проверка на всё: `is_force_push_allowed()` в `sync/push.py`.

- `github_api_main_commit_count()` узнаёт число коммитов в `main`;
- коммитов **≤ 1** (только initial) → `force = True` разрешён;
- коммитов **> 1** → `force = False`;
- не удалось определить (сеть) → `force = False` (безопасный дефолт).

Смысл: force используется ровно один раз — на первом пуше в свежий репозиторий. Как
только в `main` появляется история, любой force блокируется, а обычная синхронизация
продолжает работать через fast-forward (новый коммит всегда создаётся с
`parents=[current_head]`). При не-fast-forward обновлении GitHub вернёт `422`, и push
отменяется, не перезаписывая историю.

## 8. Параллелизм (ускорение)

Две тяжёлые стадии распараллелены через `ThreadPoolExecutor` (обе I/O-bound):

- **Копирование в песочницу** (`sync/file_copier.py`, `SmartSyncCopier`): все файлы
  копируются/хэшируются одновременно. На локальном SSD выигрыш небольшой, на облачной
  папке (OneDrive) — кратный числу потоков.
- **Заливка blob'ов на GitHub** (`sync/push.py`, `github_api_create_tree_from_folder`):
  каждый файл льётся отдельным потоком (`BLOB_UPLOAD_WORKERS = 8`) с лёгким ретраем.
  Это главный выигрыш по времени пуша на больших наборах файлов (в тестах ×7–8).

## 9. Какой модуль от чего предохраняет (карта предохранителей)

| Риск / проблема | Что защищает | Где |
|-----------------|--------------|-----|
| Второй запуск приложения | `SingleInstance` (Mutex / lock-файл + PID) | `core/single_instance.py` |
| GitHub не настроен (пустые креды) → 404 /repos/// и криптоошибки | `is_github_configured()` guard | `core/config.py`, `sync/push.py`, `sync/watcher.py` |
| Пустой репозиторий (Git Data API даёт 409) | `github_api_ensure_repo_initialized()` (Contents API) | `sync/push.py` |
| Перезапись истории force-пушем | `is_force_push_allowed()` (≤1 коммита) | `sync/push.py` |
| Force из-за сетевого сбоя | `main_ref`='unknown' → отмена; `ensure`=False | `sync/push.py` |
| Невидимые пробелы в `.env` ломают авторизацию | `sanitize_env_file` | `core/env_sanitizer.py` |
| Параллельные пуши | `push_lock` + `push.lock` + `_push_in_progress` | `sync/push.py`, `sync/watcher.py` |
| «Шторм» правок → лавина пушей | debounce `Timer(DEBOUNCE_SECONDS)` | `sync/watcher.py` |
| Петля: git-операции триггерят watcher | `stop_observer()` на время пуша + песочница + `IGNORED_DIRS` | `sync/watcher.py`, `sync/observer.py` |
| Работа не с той папкой | guard `"fake_git_temp" not in path` | `sync/push.py` |
| Плохие/обходные пути (`..`, `.git`) | `is_malformed_path` / `normalize_path` | `sync/push.py` |
| Пустой/бессмысленный пуш | guard `not added and not modified and not deleted` | `sync/push.py` |
| Битый локальный репозиторий песочницы | `initialize_repository` (ловит `GitError`, пересоздаёт) | `sync/push.py` |
| Временные сбои сети при пуше | `PushRecoveryHandler` + ретраи blob'ов | `sync/push.py` |
| Бесконтрольный рост логов | обрезка `>600 KB → ~400 KB` | `core/log_trim.py` |
| Нет структуры/`.env` на чистом окружении | `initialize_app_structure` | `core/bootstrap.py` |
| Наблюдатель «упал» | `watcher_loop` перезапускает каждые 60 сек | `sync/watcher.py` |

## 10. Подробный справочник модулей (по файлам и кейсам)

### core/logger.py
Потокобезопасный логгер. `init_logger()` — один раз в `main`; `get_logger()` — до
инициализации возвращает «заглушку» (печатает в stderr). `log_main/soft/both/debug` —
пишут в консоль + файлы (`logger.txt`, `loggerm.txt`, `syslog.txt`), а через очередь —
в GUI-колбэки. Кейс: логи из фоновых потоков (пуш, копирование) безопасно попадают в GUI.

### core/config.py
Единый источник путей и настроек. Корень проекта = `parents[1]` от `core/`. Загружает
`.env` через `dotenv`. Экспортирует `settings`, `GITHUB_*`, `WATCHED_FOLDER`,
`DEBOUNCE_SECONDS`, пути. **`is_github_configured()`** — предохранитель (все три:
логин/репо/токен заданы). `save_watched_folder()` — сохраняет папку в `.env`.

### core/single_instance.py
`SingleInstance` — не даёт запустить второй экземпляр: Windows — глобальный Mutex,
Linux/macOS — lock-файл + проверка PID (psutil) + TTL для «зависших» локов.

### core/bootstrap.py
`initialize_app_structure()` (авто при импорте) — создаёт папки/логи/`settings.ini`/`.env`
и **чистит `.env`** санитайзером ещё до загрузки `config`. Кейс: чистая установка.

### core/env_sanitizer.py
`sanitize_env_file(path)` — срезает пробелы в начале/конце имён и значений (в т.ч. внутри
кавычек), сохраняя пробелы внутри значений (пути) и комментарии. Кейс: случайный пробел
в конце токена ломал авторизацию — теперь чистится при старте и после сохранения в GUI.

### core/log_trim.py
`trim_log_file` / `main()` — если лог > 600 KB, обрезает сверху до ~400 KB через временный
файл. Кейс: логи не растут бесконечно.

### sync/observer.py
Управление watchdog-наблюдателем: `start_observer` / `stop_observer` /
`is_observer_running` / `restart_observer`. `ChangeHandler` импортируется локально (разрыв
цикла с `watcher`). Кейс: пуш останавливает наблюдателя, чтобы не поймать собственные
изменения, и запускает заново.

### sync/watcher.py
- `ChangeHandler.on_any_event` — реагирует на изменения, фильтрует игнор, не запускает
  пуш поверх идущего.
- `schedule_push` — debounce-таймер; `safe_do_push` — `stop_observer → do_push → start_observer`.
- `watcher_loop` — каждые 60 сек поднимает упавший наблюдатель.
- `safe_ensure_repository_and_main_branch` — **лёгкая** (только проверка конфигурации):
  реальная инициализация пустого репо ушла в REST (`sync/push.py`). Здесь больше нет
  CLI-bootstrap и pygit2 init-push (последний давал `failed to set credentials`).
- `initial_check_loop` — через 25 сек рапортует статус watcher/observer/GitHub.

### sync/file_copier.py
`SmartSyncCopier` — умное **параллельное** копирование из хранилища в песочницу: копирует
только новые/изменённые (по размеру + хэшу + mtime), сохраняет структуру папок.
`sync_changed_files` — обёртка, вызываемая из `do_push`. Кейс: облачная папка с сотнями
файлов копируется одновременно, а не по одному.

### sync/push.py (ядро)
- `do_push()` — оркестратор всего пуша (шаги из раздела 5).
- `github_api_main_ref()` — состояние `main`: exists/absent(404/409)/unknown.
- `github_api_ensure_repo_initialized()` — первый коммит пустого репо через Contents API.
- `collect_changes()` — сравнение песочницы с remote → added/modified/deleted.
- `github_api_create_tree_from_folder()` + `_upload_single_blob()` — **параллельная**
  заливка blob'ов и сборка дерева.
- `github_api_force_push_from_tree()` — коммит + обновление `main` под **force-guard**.
- `is_force_push_allowed()` / `github_api_main_commit_count()` — правило force.
- `initialize_repository()` — локальный одноразовый репо в песочнице (pygit2).
- `is_malformed_path` / `normalize_path` / `should_include_in_tree_and_index` — фильтры путей.
- `PushRecoveryHandler` — восстановление после recoverable-ошибок.

### sync/commit_description.py
`CommitAnalyzer.generate_commit_description` — строит человекочитаемое описание коммита
(только реально изменившиеся строки, с diff). `GitHubCommenter.post_to_commit` — постит
это описание комментарием к коммиту. Кейс: в истории GitHub видно, что именно поменялось.

### gui/app.py
`GitVersionRestoreApp` — главное окно: вкладки (Главная/SoftLogger/Settings), трей,
single-instance, привязка логгера к GUI, фоновые задачи (периодическое обновление списка
пушей и проверка смены ветки).

### gui/main_tab.py
`MainTab` — вкладка «Главная»: список пушей (`fetch_pushes`), выбор коммита и показ его
комментария, `clone_selected_version` (восстановление версии), копирование SHA/профиля,
селектор ветки. Кейс: посмотреть историю и восстановить любую версию.

### gui/settings_tab.py
`SettingsTab` — поля токена (со скрытием), логина, репозитория, папки (выбор через диалог),
частоты (минуты). Сохранение пишет всё в `.env` и **вызывает санитайзер**. Тумблер
«Start Minimized». Кейс: быстрая настройка без правки файлов.

### gui/tray.py
`setup_tray_and_close_protocol`, `create_tray_icon`, `create_exit_button`,
`show_duplicate_warning` — трей, «крестик» сворачивает в трей, полный выход, всплывашка о
повторном запуске.

### gui/branches.py
`get_current_branch` (читает HEAD песочницы), `get_remote_branches` (список веток через
API), `change_branch`, `BranchSelectorWindow`, `create_branch_selector_button`. Кейс:
переключение/просмотр веток из GUI.

### gui/version_ops.py
`clone_version` (клон нужной версии в `Versions/`), `open_versions`, `fetch_pushes`
(список коммитов; **409 = пустой репо** обрабатывается тихо), `fetch_commit_comment`,
`copy_push_sha`.

## 11. Сценарии (кейсы) пошагово

1. **Чистая установка / первый запуск.** `core/bootstrap` создаёт папки, `.env`,
   `settings.ini`; логгер стартует; GUI открывается; watcher запускается. Пока `.env`
   пустой — `is_github_configured()` = False, пуши пропускаются с понятным сообщением.
2. **Настройка в GUI.** Во вкладке Settings вводятся логин/репо/токен/папка → сохранение
   в `.env` + чистка пробелов. После следующего изменения файла пойдёт пуш.
3. **Пустой репозиторий → первый коммит.** Первое изменение файла: `do_push` видит
   `main` = absent (409) → `PUT /contents/.gitkeep` создаёт первый коммит и ветку → затем
   обычный поток заливает все файлы.
4. **Обычное изменение.** Правка `.md` → debounce → копирование в песочницу → diff с
   GitHub → параллельная заливка blob'ов → коммит поверх `main` (fast-forward) →
   комментарий с описанием.
5. **Много файлов / облачная папка.** Копирование и заливка идут параллельно — время
   пуша кратно меньше, чем при последовательной обработке.
6. **Удаление файла.** `collect_changes` замечает отсутствие файла локально → тянет его
   содержимое с remote в `deleted_files/` (для описания) и фиксирует удаление в дереве.
7. **Расхождение / попытка перезаписать.** Если `main` уже имеет историю, force запрещён;
   не-fast-forward пуш отклоняется (422) — история цела.
8. **Нет сети.** `main_ref` = unknown или таймауты → push аккуратно отменяется, ретраи;
   ошибочный force/bootstrap не выполняется.
9. **GitHub не настроен.** Любой путь к API закрыт `is_github_configured()` — один
   понятный лог вместо спама 404.
10. **Смена ветки в GUI.** `branches` переключает ветку песочницы; список пушей
    обновляется под выбранную ветку.
11. **Восстановление версии.** В «Главной» выбирается SHA → `clone_version` клонирует
    нужную версию в `Versions/`.
12. **Повторный запуск.** `SingleInstance` не даёт запустить второй экземпляр — всплывашка
    и выход.

## 12. Конфигурация (`.env`)

Ключи: `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN`, `WATCHED_FOLDER`,
`DEBOUNCE_MINUTES` (или `DEBOUNCE_SECONDS`). Логин/репо/токен **не захардкожены** —
читаются из `.env` через `os.getenv`. Токену нужен scope `repo`.

## 13. Рабочие / служебные папки

- `fake_git_temp/` — временная песочница пуша (копия файлов, сборка tree, `deleted_files/`);
  чистится до/после каждого пуша; из неё же GUI читает текущую ветку.
- `Versions/` — клоны прошлых версий (кнопка Clone).
- `Autosync_git/` — локальный git-репозиторий (осталось от прежней схемы; для REST-пуша
  не требуется).
- `push_comments/` — служебная папка.

## 14. Известные особенности

- `core/config.py` лениво импортирует `parse_diff_lines`/`run_logger_clean` из
  `sync/commit_description.py`, где их нет → штатный fallback на no-op (унаследовано).
- В `config.py` остались формально мёртвые `GIT_DIR` и `DELETED_TEMP` (не используются).
- Локальная работа с pygit2-индексом в `do_push` (`initialize_repository`) сейчас почти
  вхолостую: дерево на GitHub собирается заново из файлов, а не из индекса.
- Удалён мёртвый код: `main_core.py`, `main_func*.py`, пакет `filters/`, старый CLI-bootstrap
  и pygit2 init-push.

---
