# main.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import re
import sys

STUDIO_FILTERED_URL = (
    "https://studio.youtube.com/channel/UC9JODm8Vze3gdkL9x27eFwA/videos/upload"
    "?filter=%5B%7B%22name%22%3A%22VISIBILITY%22%2C%22value%22%3A%5B%22PRIVATE%22%5D%7D%5D"
    "&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D"
)
CHECK_INTERVAL = 300  # секунд между проверками (5 минут)
BROWSER_PROFILE_DIR = "./browser_profile"
LOG_FILE = "run.log"

_log_file = open(LOG_FILE, "w", encoding="utf-8", buffering=1)


def log(msg: str):
    """Вывод сообщения с временной меткой в консоль и файл run.log."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    _log_file.write(line + "\n")


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
    """Открывает редактор видео, переходит в Languages, ставит русский язык и сохраняет."""
    edit_url = f"https://studio.youtube.com/video/{video_id}/edit"

    try:
        log(f"[ФАКТ] До перехода, текущий URL: {page.url}")
        page.goto(edit_url)
        page.wait_for_load_state("networkidle", timeout=15000)
        log(f"[ФАКТ] После goto /edit, URL: {page.url}")
        page.wait_for_timeout(2000)

        translations_url = f"https://studio.youtube.com/video/{video_id}/translations"
        log(f"[ФАКТ] Перехожу на /translations: {translations_url}")
        page.goto(translations_url)
        page.wait_for_load_state("networkidle", timeout=15000)
        log(f"[ФАКТ] После goto /translations, URL: {page.url}")
        page.wait_for_timeout(2000)

        # Проверяем — язык уже Russian?
        language_header = page.locator("h2#default-language-title")
        log(f"[ФАКТ] h2#default-language-title найдено: {language_header.count()}")
        if language_header.count() > 0:
            header_text = language_header.text_content() or ""
            log(f"[ФАКТ] Текст заголовка языка: '{header_text.strip()}'")
            if "Russian" in header_text:
                log(f"Язык уже Russian для '{video_title}' — пропускаю")
                page.goto(STUDIO_FILTERED_URL)
                page.wait_for_load_state("networkidle", timeout=15000)
                log(f"[ФАКТ] Вернулись на список, URL: {page.url}")
                return True

        log(f"Язык не выставлен — нужно установить Russian для '{video_title}' (TODO)")
        page.goto(STUDIO_FILTERED_URL)
        page.wait_for_load_state("networkidle", timeout=15000)
        log(f"[ФАКТ] Вернулись на список, URL: {page.url}")
        return False

    except PlaywrightTimeoutError as e:
        log(f"ТАЙМАУТ при обработке '{video_title}': {e}")
        page.goto(STUDIO_FILTERED_URL)
        return False
    except Exception as e:
        log(f"ОШИБКА при обработке '{video_title}': {e}")
        page.goto(STUDIO_FILTERED_URL)
        return False


def main():
    """Основной цикл: мониторит видео и меняет язык каждые 5 минут."""
    processed_titles: set[str] = set()

    log("Запуск YouTube Studio Auto Language Setter")
    log(f"Интервал проверки: {CHECK_INTERVAL // 60} минут")

    with sync_playwright() as p:
        log("Запускаю браузер (через subprocess, чтобы обойти блокировку Google)...")
        import subprocess
        import os
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

        if all_pages:
            page = all_pages[0]
        else:
            page = context.new_page()

        log(f"[ФАКТ] Работаем с вкладкой: {page.url}")
        log("Перехожу на YouTube Studio (только Private видео)...")
        page.goto(STUDIO_FILTERED_URL)
        page.wait_for_load_state("networkidle", timeout=20000)
        log(f"[ФАКТ] URL после перехода на Studio: {page.url}")
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
