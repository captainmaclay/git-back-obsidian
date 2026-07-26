# Obsidian Autosync — навигация по проекту

Приложение автоматически синхронизирует локальное хранилище Obsidian с
репозиторием на GitHub: следит за изменениями файлов, с задержкой (debounce)
собирает изменения и пушит их через GitHub REST API, а также даёт GUI для
просмотра истории пушей и восстановления любой версии.

Точка входа — `main.py` в корне. Запуск: `python main.py`.

---

## Структура пакетов

```
main.py                     — точка входа: .env, single-instance, логгер, GUI, фоновый watcher
core/                       — инфраструктура (не знает про GUI и синхронизацию)
  config.py                 — все пути, .env, токены, объект settings, DEBOUNCE
  logger.py                 — потокобезопасный логгер (консоль + файлы + GUI-колбэки)
  single_instance.py        — защита от повторного запуска (Mutex / lock-файл)
  bootstrap.py              — подготовка структуры папок/файлов при старте
  log_trim.py               — обрезка разросшихся лог-файлов
sync/                       — движок синхронизации и работы с GitHub
  watcher.py                — watchdog-обработчик, debounce, bootstrap первой ветки
  observer.py               — управление watchdog-наблюдателем (start/stop/restart)
  file_copier.py            — умное копирование изменённых файлов во временную папку
  push.py                   — ГЛАВНЫЙ push: сбор изменений + REST API + force-guard
  commit_description.py     — генерация описания коммита и отправка комментария
gui/                        — интерфейс (Tkinter)
  app.py                    — главное окно, вкладки, трей, фоновые задачи
  main_tab.py               — вкладка «Главная»: список пушей, clone, копирование
  settings_tab.py           — вкладка «Settings»: токен, папка, частота, .env
  tray.py                   — иконка в трее, протокол закрытия, кнопка Exit
  branches.py               — текущая ветка, список веток, окно выбора ветки
  version_ops.py            — clone версии, fetch пушей/комментариев, копирование SHA
```

Каждый пакет содержит `__init__.py`. Импорты — абсолютные (`from core.config import ...`).

---

## Поток запуска (`main.py`)

1. `import core.bootstrap` — создаёт нужные папки и файлы (побочный эффект импорта).
2. `import core.config` — грузит `.env`, вычисляет пути, создаёт объект `settings`.
3. `ensure_env_file()` — дополняет `.env` недостающими ключами.
4. `SingleInstance.acquire()` — если уже запущено, показывает предупреждение и выходит.
5. `log_trim.main()` — подрезает большие логи.
6. `init_logger()` — включает реальный логгер.
7. `tk.Tk()` + `GitVersionRestoreApp(root)` — строит GUI.
8. Фоновый поток `start_observation()` → `start_watcher()` + `initial_check_loop()`.
9. `root.mainloop()`.

---

## Поток синхронизации (изменение файла → пуш)

```
изменение файла в хранилище
        │  (watchdog)
        ▼
sync/watcher.py  ChangeHandler.on_any_event
        │  фильтр игнора + debounce (DEBOUNCE_SECONDS)
        ▼
sync/watcher.py  schedule_push → safe_do_push
        │  stop_observer()  (чтобы push не ловил сам себя)
        ▼
sync/push.py  do_push()
        │  1. sync_changed_files()  (sync/file_copier.py) → временная папка
        │  2. collect_changes()     — сравнение с GitHub (added/modified/deleted)
        │  3. заполнение deleted_files содержимым с remote
        │  4. сборка git tree через GitHub REST API (blobs → tree)
        │  5. CommitAnalyzer.generate_commit_description()  (sync/commit_description.py)
        │  6. push_with_retry() → github_api_force_push_from_tree()   ← FORCE-GUARD
        │  7. отложенная отправка комментария (GitHubCommenter.post_to_commit)
        ▼
   start_observer()  (наблюдение возобновляется)
```

Первая инициализация (`safe_ensure_repository_and_main_branch` в `sync/watcher.py`):
если репозиторий на GitHub пуст (ответ 409) — выполняется одноразовый bootstrap-push
через CLI (`git init/add/commit/branch -M main/push --force`), далее работает pygit2/REST.

---

## Защита от force push (force-guard)

Единственный рабочий push — `sync/push.py`. Обновление ветки `main` делает
`github_api_force_push_from_tree()`. Флаг `force` теперь вычисляется, а не захардкожен:

- `github_api_main_commit_count()` считает коммиты в `main`;
- `is_force_push_allowed()` разрешает `force=True` **только если коммитов ≤ 1**
  (то есть в ветке лишь initial commit);
- при наличии других пушей `force=False` — GitHub отклонит любое не-fast-forward
  обновление и история не будет перезаписана;
- если число коммитов определить не удалось (сеть) — `force` запрещается.

Обычная работа не страдает: новый коммит всегда создаётся с `parents=[current_head]`,
то есть это fast-forward и он проходит даже без force.

В проекте есть **три** места, где происходит force-push, и все закрыты одной проверкой
`is_force_push_allowed()` (или её гейтом):

1. `sync/push.py` — основной REST-push при каждой синхронизации.
2. `sync/watcher.py`, `safe_ensure_repository_and_main_branch()` — init-push через
   pygit2 (`+refs/heads/main:...`) при старте. Теперь если в `main` уже есть пуши —
   этот init force-push **пропускается** (раньше выполнялся всегда).
3. `sync/watcher.py`, `bootstrap_force_push_cli()` — одноразовый `git push --force`
   только для пустого репозитория. Функция `github_repo_is_empty()` при сетевой ошибке
   теперь возвращает `False` (не запускает force-bootstrap, если не уверена).

---

## Конфигурация (`core/config.py` + `.env`)

Ключи `.env`: `GITHUB_USERNAME`, `GITHUB_REPO`, `GITHUB_TOKEN`, `WATCHED_FOLDER`,
`DEBOUNCE_MINUTES` (или `DEBOUNCE_SECONDS`).

`core/config.py` определяет корень проекта как `Path(__file__).resolve().parents[1]`
(на уровень выше пакета `core/`) и от него строит все пути: `Autosync_git/`,
`fake_git_temp/`, `Versions/`, логи и т.д. Объект `settings` и функция
`save_watched_folder()` используются в GUI.

---

## Справочник модулей (ключевые символы)

| Модуль | Ключевые символы | Кто использует |
|--------|------------------|----------------|
| `core/logger.py` | `init_logger`, `get_logger`, `log_main/soft/both` | все |
| `core/config.py` | `settings`, `GITHUB_*`, `WATCHED_FOLDER`, пути, `DEBOUNCE_SECONDS` | почти все |
| `core/single_instance.py` | `SingleInstance` | `main.py`, `gui/app.py` |
| `core/bootstrap.py` | `initialize_app_structure` (авто при импорте) | `main.py` |
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

---

## Что удалено при рефакторинге

Мёртвый код (нигде не импортировался): `main_core.py`, `main_func.py`,
`main_func2.py`, пакет `filters/` целиком, а также альтернативная REST-реализация
push внутри бывшего `git_gui_utils.py` (`do_push_with_fake_git`, `_force_push_tree`,
`_create_tree_from_folder`). Осталась одна ветка синхронизации — `sync/push.py`.

Переименования файлов (старое → новое): `app_logger.py→core/logger.py`,
`defense.py→core/single_instance.py`, `require_utils.py→core/bootstrap.py`,
`mem.py→core/log_trim.py`, `do_push.py→sync/push.py`, `copy_item.py→sync/file_copier.py`,
`observer_manager.py→sync/observer.py`, `gui_watcher.py→sync/watcher.py`,
`make_description.py→sync/commit_description.py`, `gui.py→gui/app.py`,
`gui_main_page.py→gui/main_tab.py`, `gui_settings.py→gui/settings_tab.py`,
`gui_func_adds.py→gui/tray.py`, `gui_func_tables.py→gui/branches.py`,
`git_gui_utils.py→gui/version_ops.py`. Имена функций и классов сохранены без
изменений, чтобы гарантировать корректность всех вызовов.

---

## Известные особенности (не трогались рефакторингом)

- `core/config.py` лениво импортирует `parse_diff_lines` и `run_logger_clean`
  из `sync/commit_description.py`, но там их нет — срабатывает штатный fallback на
  «пустышку» (no-op). Поведение унаследовано и сохранено как было.
- `sync/watcher.py` носил префикс `gui_`, хотя относится к синхронизации, а не к GUI —
  поэтому перенесён в пакет `sync/`.
