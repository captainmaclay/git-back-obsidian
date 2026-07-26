# Obsidian Git Sync GUI

A Python desktop app with a simple GUI that **automatically backs up and version-controls
your notes on GitHub**. Point it at a folder (an **Obsidian vault**, including one stored in
a cloud folder like OneDrive) — it watches for changes and pushes them to GitHub on its own,
with meaningful commits and per-commit change comments. **No git commands required.**

![screenshot](https://i.imgur.com/T4riv4Z.png)

> 📖 **Full documentation:** see
> [PROJECT_GUIDE.md](https://github.com/captainmaclay/git-back-obsidian/blob/main/PROJECT_GUIDE.md)
> for the complete description of everything the app can do (architecture, flows, safety
> guards, every setting).

## Features

- **Automatic push** of a watched folder to GitHub via the **REST API with a token** — no
  local git installation needed.
- **Configurable file types.** By default tracks `.md`; extensions are edited in a simple
  `push_extensions.txt` (one per line) via a `+` button in Settings and applied live.
- **Folder events** (create / delete / rename) can be toggled on or off with a checkbox.
- **Empty‑repository bootstrap:** the first commit and the `main` branch are created for you
  (via the GitHub Contents API), so a brand‑new empty repo just works.
- **Offline resilience.** Changes are written to a persistent queue that is cleared **only
  after a successful push**. If a push fails or the app is closed, the changes are **not
  lost** — a background **retry queue** re‑sends them (configurable interval & attempts) and
  pushes them right on the next startup.
- **History safety:** a **force‑guard** allows a force‑push only for a fresh repository, so
  existing history can’t be accidentally overwritten.
- **Fast on cloud folders:** file copying and GitHub blob uploads run **in parallel**.
- **Version restore:** browse the push history, read the commit comment, and **clone/restore
  any previous version**.
- **Convenience:** system‑tray minimize, start‑minimized, single‑instance protection, hidden
  token field, fault‑tolerant push list (retries + cache).

## GUI configuration

Through the **Settings** tab you can set:

- **Git Folder** — the folder to watch (e.g. your Obsidian vault)
- **Files** — tracked file extensions (`+` opens `push_extensions.txt`)
- **Folders** — react to folder create / delete / rename (on by default)
- **GitHub Username**, **Repository Name**, **GitHub Token** (hidden, with show toggle)
- **Update Frequency** — debounce before pushing edits
- **Retry Interval** / **Retry Attempts** — for re‑sending pending changes

![settings](https://i.imgur.com/ed07yNG.png)

## Installation and running

### 1. Clone the repository
```bash
git clone git@github.com:captainmaclay/git-back-obsidian.git
cd git-back-obsidian
```

### 2. Create a virtual environment
```bash
python -m venv .venv
```

### 3. (Windows PowerShell only) Temporarily allow script execution
Required if PowerShell blocks running `Activate.ps1`:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 4. Activate the virtual environment
```powershell
.venv\Scripts\Activate.ps1
```
Verify `pip` belongs to the venv:
```bash
python -m pip --version
```

### 5. Install project dependencies
```bash
pip install -r requirements.txt
```

### 6. Prepare the `.env` file and project structure
```bash
python -c "import core.bootstrap"
```
Then fill in `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN` (needs `repo` scope) and
`WATCHED_FOLDER` — in `.env` or in the **Settings** tab.

### 7. Launch the GUI application
```bash
python main.py
```

---

# Obsidian Git Sync GUI (Русский)

Настольное приложение на Python с простым GUI, которое **автоматически делает бэкап и
версионирование ваших заметок на GitHub**. Указываете папку (**хранилище Obsidian**, в том
числе в облачной папке вроде OneDrive) — оно само отслеживает изменения и пушит их на GitHub
с осмысленными коммитами и комментариями к изменениям. **Никаких git‑команд не требуется.**

![скриншот](https://i.imgur.com/T4riv4Z.png)

> 📖 **Полное описание:** см.
> [PROJECT_GUIDE.md](https://github.com/captainmaclay/git-back-obsidian/blob/main/PROJECT_GUIDE.md)
> — там подробно всё, что умеет программа (архитектура, потоки данных, предохранители, каждая
> настройка).

## Возможности

- **Автоматический пуш** отслеживаемой папки на GitHub через **REST API с токеном** — без
  установленного git.
- **Настраиваемые типы файлов.** По умолчанию отслеживается `.md`; расширения задаются в
  простом `push_extensions.txt` (по одному на строку) через кнопку `+` в Settings и
  применяются на лету.
- **События папок** (создание / удаление / переименование) включаются/выключаются галочкой.
- **Инициализация пустого репозитория:** первый коммит и ветка `main` создаются автоматически
  (через GitHub Contents API) — свежесозданный пустой репозиторий сразу работает.
- **Отказоустойчивость.** Изменения пишутся в персистентную очередь, которая очищается
  **только после успешного пуша**. Если пуш не удался или программу закрыли — изменения **не
  теряются**: фоновая **retry‑очередь** досылает их (интервал и число попыток настраиваются)
  и отправляет сразу при следующем запуске.
- **Защита истории:** **force‑guard** разрешает force‑push только для свежего репозитория,
  поэтому существующую историю нельзя случайно перезаписать.
- **Быстро на облачных папках:** копирование файлов и загрузка blob’ов на GitHub идут
  **параллельно**.
- **Восстановление версий:** просмотр истории пушей, чтение комментария коммита и
  **клонирование/восстановление любой прошлой версии**.
- **Удобство:** сворачивание в трей, запуск в свёрнутом виде, защита от повторного запуска,
  скрытое поле токена, отказоустойчивый список пушей (ретраи + кэш).

## Настройки в GUI

Во вкладке **Settings** можно задать:

- **Git Folder** — папку для слежения (например, хранилище Obsidian)
- **Files** — отслеживаемые расширения (`+` открывает `push_extensions.txt`)
- **Folders** — реагировать на создание / удаление / переименование папок (по умолчанию вкл)
- **GitHub Username**, **Repository Name**, **GitHub Token** (скрытый, с переключателем показа)
- **Update Frequency** — задержка (debounce) перед пушем правок
- **Retry Interval** / **Retry Attempts** — для досыла отложенных изменений

![настройки](https://i.imgur.com/ed07yNG.png)

## Установка и запуск

### 1. Клонировать репозиторий
```bash
git clone git@github.com:captainmaclay/git-back-obsidian.git
cd git-back-obsidian
```

### 2. Создать виртуальное окружение
```bash
python -m venv .venv
```

### 3. (Только Windows PowerShell) Временно разрешить запуск скриптов
Нужно, если PowerShell блокирует `Activate.ps1`:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 4. Активировать виртуальное окружение
```powershell
.venv\Scripts\Activate.ps1
```
Проверить, что `pip` из venv:
```bash
python -m pip --version
```

### 5. Установить зависимости
```bash
pip install -r requirements.txt
```

### 6. Подготовить `.env` и структуру проекта
```bash
python -c "import core.bootstrap"
```
Затем заполнить `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN` (нужен scope `repo`) и
`WATCHED_FOLDER` — в `.env` или во вкладке **Settings**.

### 7. Запустить приложение
```bash
python main.py
```
