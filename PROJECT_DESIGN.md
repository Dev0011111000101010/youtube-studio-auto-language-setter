# YouTube Studio Auto Language Setter - Project Design Document

**Дата создания:** 2026-03-13
**Версия:** 0.1
**Назначение:** Карта проекта для AI навигации

---

> ⛔ **AI: БЛОК НИЖЕ (до следующего `---`) — ПОСТОЯННАЯ ИНСТРУКЦИЯ. НЕ УДАЛЯТЬ, НЕ СОКРАЩАТЬ, НЕ ПРЕДЛАГАТЬ УДАЛИТЬ.** Обновляется только раздел после закрывающего `---`.

## 🤖 ИНСТРУКЦИЯ: КАК ПОСТРОЕН ЭТОТ ДОКУМЕНТ

**Назначение:** INDEX/TABLE OF CONTENTS — быстрая навигация по проекту (не энциклопедия!)
**Целевая аудитория:** AI в первую очередь, человек во вторую (читаемость сохранена)

### ✅ ЧТО СОДЕРЖИТ этот документ:

1. **Полные пути к файлам**
   - Относительные от корня проекта
   - Пример: `backend/core/scripts/take_full_screenshot.py`

2. **Назначение файла**
   - Краткое описание (1-2 предложения)

3. **Импорты**
   - Все import в файле (внешние + внутренние)
   - Показывает взаимозависимости

4. **Список функций (def) и классов — AI-оптимизированный формат**
   - **Простые функции (1-2 параметра):** `func(param: type, default=value)` — описание
   - **Сложные функции (3+ параметра):** Заголовок + сигнатура с типами + описание + пример вызова
   - **Типы параметров:** Указаны в сигнатуре (str, bool, int, None, etc.)
   - **Примеры вызова:** Только для сложных функций

5. **Указатели на детали**
   - Где искать детальную информацию

### ❌ ЧТО НЕ СОДЕРЖИТ (детали остаются в коде):

- Детальные примеры кода
- Константы (COLORS = {...}, CONFIG = {...})
- Большие словари/списки
- Примеры JSON структур
- Пошаговые инструкции с кодом
- Секции "Параметры:", "Возвращает:" (избыточно для AI)

### 📐 Формат описания файла:

```
### Номер. путь/к/файлу.py
**Назначение:** Что делает (1-2 предложения)

**Импорты:**
```python
import библиотека
from модуль import функция
```

**Функции (def):**
- `func(param: type)` — описание

**Детали:** см. файл.py
```

### 🔄 Правило для AI при обновлении:

**При создании или изменении любого файла** → обновить этот документ.

---

## ОБЗОР ПРОЕКТА

**Назначение:** Playwright-демон, который мониторит YouTube Studio, находит видео со статусом **Private** и автоматически выставляет им язык **Russian**.

**Стек:** Python 3.12 + Playwright (sync API) + Chromium (headless=False)

**Запуск:** `.venv/Scripts/python main.py`

**Канал:** `https://studio.youtube.com/channel/UC9JODm8Vze3gdkL9x27eFwA/videos/upload`

---

## СТРУКТУРА ФАЙЛОВ

```
youtube-studio-auto-language-setter/
│
├── main.py                 Основной демон — точка входа
├── debug_dump.py           Утилита: дампит 3 страницы в dumps/ для анализа DOM
├── requirements.txt        Зависимости (playwright)
├── run.log                 Лог текущего запуска (перезаписывается при старте)
├── README.md               Логика проекта и контекст для нового агента
├── CLAUDE_INSTRUCTIONS.md  Контракт: правила взаимодействия с AI
├── PROJECT_DESIGN.md       Карта проекта (этот файл)
│
├── dumps/                  HTML дампы страниц (video_list, edit_page, translations_page)
├── browser_profile/        Сохранённый профиль Chrome (сессия Google) — в .gitignore
└── .venv/                  Python virtual environment
```

---

## КЛЮЧЕВЫЕ КОМПОНЕНТЫ

### main.py
**Назначение:** Бесконечный loop: каждые 5 минут проверяет YouTube Studio на наличие новых Private видео, проверяет язык на странице /translations, пропускает если Russian уже стоит, иначе устанавливает (TODO).

**Импорты:**
```python
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time, re, sys, subprocess, os, urllib.request
```

**Константы:**
- `STUDIO_FILTERED_URL` — URL списка видео канала (фильтр Private + сортировка по дате)
- `CHECK_INTERVAL = 300` — интервал проверки в секундах
- `BROWSER_PROFILE_DIR = "./browser_profile"` — профиль Chrome с сохранённой сессией
- `LOG_FILE = "run.log"` — лог текущего запуска (перезаписывается)

**Функции (def):**
- `log(msg: str)` — вывод в консоль + запись в run.log с временной меткой
- `find_private_videos(page) -> list[dict]` — ищет ссылки `a[href*='/video/'][href*='/edit']`, дедуплицирует по video_id (берёт запись с самым длинным title), возвращает `[{title, video_id}]`
- `wait_for_save_confirmation(page) -> bool` — ждёт toast/disabled Save кнопки (TODO: не используется пока)
- `set_language_russian(page, video_title: str, video_id: str) -> bool` — goto /edit → goto /translations → проверяет `h2#default-language-title`, если Russian — пропускает; иначе TODO
- `main()` — запускает Chrome через subprocess + CDP, логирует все вкладки, держит `processed_titles: set[str]` (video_id), управляет loop

**In-memory state:**
- `processed_titles: set[str]` — video_id обработанных видео в текущей сессии. При перезапуске — чистый старт.

**Детали:** см. main.py

---

### debug_dump.py
**Назначение:** Утилита для разового дампа DOM трёх страниц YouTube Studio в папку dumps/ — для анализа селекторов.

**Импорты:**
```python
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import subprocess, os, time, urllib.request
```

**Константы:**
- `DUMPS_DIR = "./dumps"` — папка для HTML дампов
- `OUTPUT_VIDEO_LIST`, `OUTPUT_LINKS`, `OUTPUT_EDIT`, `OUTPUT_TRANSLATIONS` — пути файлов

**Функции (def):**
- `log(msg: str)` — вывод с временной меткой
- `save_html(page, path: str)` — сохраняет page.content() в файл (перезапись)
- `connect_to_chrome(p) -> page` — запускает Chrome если не запущен (порт 9222), подключается по CDP
- `main()` — дампит: список видео → video_list.html + links.txt, /edit первого → edit_page.html, /translations первого → translations_page.html

**Детали:** см. debug_dump.py

---

**Версия:** 0.1
**Последнее обновление:** 2026-03-13
