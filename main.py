# main.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import re
import sys
import os
import glob

STUDIO_FILTERED_URL = (
    "https://studio.youtube.com/channel/UC9JODm8Vze3gdkL9x27eFwA/videos/upload"
    "?filter=%5B%7B%22name%22%3A%22VISIBILITY%22%2C%22value%22%3A%5B%22PRIVATE%22%5D%7D%5D"
    "&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D"
)
CHECK_INTERVAL = 300  # секунд между проверками (5 минут)
BROWSER_PROFILE_DIR = "./browser_profile"
LOG_FILE = "run.log"
DOWNLOADS_DIR = r"C:\Users\VibeCodeBlogger\Downloads"
MAX_DOWNLOAD_ATTEMPTS = 5

_log_file = open(LOG_FILE, "w", encoding="utf-8", buffering=1)


def log(msg: str):
    """Вывод сообщения с временной меткой в консоль и файл run.log."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    _log_file.write(line + "\n")


def snapshot_transcripts() -> dict[str, float]:
    """Возвращает словарь {полный_путь: mtime} для всех transcript*.txt в Downloads."""
    result = {}
    for path in glob.glob(os.path.join(DOWNLOADS_DIR, "transcript*.txt")):
        try:
            result[path] = os.path.getmtime(path)
        except OSError:
            pass
    return result


def wait_for_new_transcript(snapshot_before: dict[str, float], timeout_sec: int = 30) -> str | None:
    """Ждёт нового или изменённого transcript*.txt. Возвращает имя файла или None."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2)
        for path in glob.glob(os.path.join(DOWNLOADS_DIR, "transcript*.txt")):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            # Новый файл или существующий с изменённым mtime (перезапись)
            if path not in snapshot_before or mtime != snapshot_before[path]:
                return os.path.basename(path)
    return None


def find_private_videos(page) -> list[dict]:
    """Сканирует страницу и возвращает список найденных Private видео."""
    try:
        # Ждем загрузки хотя бы одной ссылки на редактирование видео
        page.wait_for_selector("a[href*='/video/'][href*='/edit']", timeout=15000)
    except PlaywrightTimeoutError:
        log("ПРЕДУПРЕЖДЕНИЕ: видео не найдены — страница ещё грузится или список пуст")
        return []

    # Ищем все ссылки редактирования на странице
    edit_links = page.query_selector_all("a[href*='/video/'][href*='/edit']")

    # Дедублируем по video_id: один video_id → запись с самым длинным title
    # (ссылка на превью даёт duration "1:39:30", ссылка на заголовок — реальное название)
    best: dict[str, dict] = {}
    for link in edit_links:
        href = link.get_attribute("href") or ""
        match = re.search(r"/video/([^/]+)/edit", href)
        if not match:
            continue

        video_id = match.group(1)
        title = link.inner_text().strip() or video_id

        if video_id not in best or len(title) > len(best[video_id]["title"]):
            best[video_id] = {"title": title, "video_id": video_id}

    videos = list(best.values())
    log(f"[ФАКТ] Уникальных видео после дедупликации: {len(videos)}")
    for v in videos:
        log(f"[ФАКТ]   id={v['video_id']} title='{v['title']}'")
    return videos


def wait_for_save_confirmation(page) -> bool:
    """Ждет подтверждения успешного сохранения изменений на странице."""
    # Вариант 1: появляется toast/snackbar
    try:
        # notification-action-renderer is used for success toast on Studio
        page.wait_for_selector(
            "ytcp-notification-action-renderer",
            timeout=10000
        )
        return True
    except PlaywrightTimeoutError:
        pass

    # Вариант 2: кнопка Save стала disabled (нечего сохранять — всё сохранено)
    try:
        page.wait_for_selector(
            "#save-button[disabled], button:has-text('Save')[disabled]",
            timeout=5000
        )
        return True
    except PlaywrightTimeoutError:
        pass

    # Вариант 3: ждем сообщения "Изменения сохранены" или аналога в snackbar
    try:
        page.wait_for_selector(
            "tp-yt-paper-toast[text*='saved']",
            timeout=5000
        )
        return True
    except PlaywrightTimeoutError:
        pass

    log("ПРЕДУПРЕЖДЕНИЕ: не удалось подтвердить сохранение — нужно уточнить селектор")
    return False


def set_language_russian(page, video_title: str, video_id: str) -> bool:
    """Открывает /translations, читает заголовок языка из DOM, пропускает если Russian."""
    translations_url = f"https://studio.youtube.com/video/{video_id}/translations"

    try:
        log(f"Перехожу на /translations для '{video_title}'")
        page.goto(translations_url)

        # Ждём реальный элемент из DOM — без него страница не считается загруженной
        try:
            page.wait_for_selector("h2#default-language-title", timeout=5000)
        except PlaywrightTimeoutError:
            log(f"ОШИБКА: h2#default-language-title не появился за 5 сек на {page.url} — страница не загрузилась")
            return False

        # Читаем реальный текст из DOM
        header_text = page.locator("h2#default-language-title").text_content() or ""
        log(f"[DOM] Заголовок языка: '{header_text.strip()}' (страница: {page.url})")

        if not header_text.strip():
            log(f"ОШИБКА: заголовок языка пустой — не можем определить язык для '{video_title}'")
            return False

        if "Russian" not in header_text:
            log(f"Язык не Russian для '{video_title}' — нужно установить (TODO)")
            page.goto(STUDIO_FILTERED_URL)
            return False

        log(f"Язык Russian для '{video_title}' — начинаю скачивание субтитров")

        downloaded_file = None
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            log(f"Попытка {attempt}/{MAX_DOWNLOAD_ATTEMPTS}: скачиваю субтитры для '{video_title}'")

            # Переходим на /translations (при повторных попытках — с нуля)
            page.goto(translations_url)
            try:
                page.wait_for_selector("ytcp-button#m2-editor-button", timeout=5000)
            except PlaywrightTimeoutError:
                log(f"ОШИБКА: кнопка Edit subtitles не появилась (попытка {attempt})")
                continue

            page.locator("ytcp-button#m2-editor-button").click()
            log(f"[DOM] Кликнул Edit subtitles — ждём 20 сек загрузки субтитров")
            page.wait_for_timeout(20000)

            # Снимок папки Downloads ДО клика
            files_before = snapshot_transcripts()
            log(f"[DOM] Файлов transcript в Downloads до клика: {len(files_before)}, mtime: {list(files_before.values())}")

            # Ждём кнопку Options (три точки)
            try:
                page.wait_for_selector("#more-actions-menu > yt-icon > span > div", timeout=5000)
            except PlaywrightTimeoutError:
                log(f"ОШИБКА: Options не появился за 5 сек (попытка {attempt})")
                continue

            page.locator("#more-actions-menu > yt-icon > span > div").click()
            log(f"[DOM] Кликнул Options")

            # Ждём пункт Download subtitles
            try:
                page.wait_for_selector("yt-formatted-string.item-text:text-is('Download subtitles')", timeout=5000)
            except PlaywrightTimeoutError:
                log(f"ОШИБКА: пункт Download subtitles не появился (попытка {attempt})")
                continue

            page.locator("yt-formatted-string.item-text:text-is('Download subtitles')").click()
            log(f"[DOM] Кликнул Download subtitles — жду появления файла (до 30 сек)")

            # Ждём новый файл в Downloads
            new_file = wait_for_new_transcript(files_before, timeout_sec=30)
            if new_file:
                log(f"[DOM] Файл субтитров скачан: {new_file}")
                downloaded_file = new_file
                break
            else:
                log(f"ПРЕДУПРЕЖДЕНИЕ: файл не появился за 30 сек (попытка {attempt})")

        # Возвращаемся на список
        page.goto(STUDIO_FILTERED_URL)
        try:
            page.wait_for_selector("a[href*='/video/'][href*='/edit']", timeout=5000)
        except PlaywrightTimeoutError:
            log(f"ОШИБКА: список видео не загрузился за 5 сек после возврата (URL: {page.url})")
            return False

        actual_count = len(page.query_selector_all("a[href*='/video/'][href*='/edit']"))
        log(f"[DOM] Вернулись на список. Ссылок на видео найдено: {actual_count} (URL: {page.url})")

        if not downloaded_file:
            log(f"ОШИБКА: не удалось скачать субтитры за {MAX_DOWNLOAD_ATTEMPTS} попыток")
            return False

        return True

    except PlaywrightTimeoutError as e:
        log(f"ТАЙМАУТ при обработке '{video_title}': {e}")
        return False
    except Exception as e:
        log(f"ОШИБКА при обработке '{video_title}': {e}")
        return False


def main():
    """Основной цикл: мониторит видео и меняет язык каждые 5 минут."""
    processed_titles: set[str] = set()

    log("Запуск YouTube Studio Auto Language Setter")
    log(f"Интервал проверки: {CHECK_INTERVAL // 60} минут")

    with sync_playwright() as p:
        log("Запускаю браузер (через subprocess, чтобы обойти блокировку Google)...")
        import subprocess
        import urllib.request
        
        profile_path = os.path.abspath(BROWSER_PROFILE_DIR)
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        
        if not os.path.exists(chrome_path):
            log(f"ОШИБКА: Chrome не найден по пути {chrome_path}")
            return
            
        cmd = [
            chrome_path,
            f"--remote-debugging-port=9222",
            f"--user-data-dir={profile_path}",
            f"--download-default-directory={DOWNLOADS_DIR}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        
        process = subprocess.Popen(cmd)
        
        log("Ждем запуска Chrome и открытия порта 9222...")
        connected = False
        for _ in range(15):
            try:
                urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1)
                connected = True
                break
            except Exception:
                time.sleep(1)
                
        if not connected:
            log("ОШИБКА: не удалось дождаться порта 9222 от Chrome.")
            return
            
        log("Подключаюсь к браузеру через CDP...")
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]

        all_pages = context.pages
        log(f"[ФАКТ] Открытых вкладок в браузере: {len(all_pages)}")
        for i, p_ in enumerate(all_pages):
            log(f"[ФАКТ]   вкладка[{i}]: {p_.url}")

        # Берём первую нормальную вкладку (http/https), не служебную chrome:// страницу
        page = next(
            (p_ for p_ in all_pages if p_.url.startswith("http")),
            None
        )
        if page is None:
            log("[ФАКТ] Нет http-вкладок — создаю новую")
            page = context.new_page()

        # Принудительно направляем загрузки в Downloads — переопределяем Playwright CDP-перехват
        cdp_session = context.new_cdp_session(page)
        cdp_session.send("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": DOWNLOADS_DIR
        })
        log(f"[ФАКТ] Download папка установлена: {DOWNLOADS_DIR}")

        log(f"[ФАКТ] Работаем с вкладкой: {page.url}")
        log("Перехожу на YouTube Studio (только Private видео)...")
        page.goto(STUDIO_FILTERED_URL)

        # Ждём реальный элемент — ссылку на видео в DOM
        try:
            page.wait_for_selector("a[href*='/video/'][href*='/edit']", timeout=10000)
            actual = len(page.query_selector_all("a[href*='/video/'][href*='/edit']"))
            log(f"[DOM] Studio загружена. Ссылок на видео в DOM: {actual} (URL: {page.url})")
        except PlaywrightTimeoutError:
            log(f"ОШИБКА: ссылки на видео не появились за 10 сек — список пуст или страница не загрузилась (URL: {page.url})")
        page.wait_for_timeout(2000)

        try:
            while True:
                log("Проверяю Private видео...")

                private_videos = find_private_videos(page)
                log(f"Найдено Private видео: {len(private_videos)}")

                new_videos = [v for v in private_videos if v["video_id"] not in processed_titles]
                log(f"Новых (не обработанных): {len(new_videos)}")

                for video in new_videos:
                    title = video["title"]
                    video_id = video["video_id"]
                    log(f"Обрабатываю: {title} (id={video_id})")

                    success = set_language_russian(page, title, video_id)

                    if success:
                        processed_titles.add(video_id)
                        log(f"УСПЕХ: '{title}' (id={video_id}) → язык Russian установлен")
                    else:
                        log(f"ОШИБКА: '{title}' (id={video_id}) — попробую в следующем цикле")

                log(f"Обработано в этой сессии: {len(processed_titles)}")
                log(f"Следующая проверка через {CHECK_INTERVAL // 60} мин. Ctrl+C для остановки.")

                time.sleep(CHECK_INTERVAL)

                page.goto(STUDIO_FILTERED_URL)
                page.wait_for_selector("table[aria-label='Video list']", timeout=15000)

        except KeyboardInterrupt:
            log("Остановлено пользователем (Ctrl+C)")
        finally:
            context.close()
            _log_file.close()


if __name__ == "__main__":
    main()
