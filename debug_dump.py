# debug_dump.py
import sys
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import subprocess
import os
import time
import urllib.request

STUDIO_FILTERED_URL = (
    "https://studio.youtube.com/channel/UC9JODm8Vze3gdkL9x27eFwA/videos/upload"
    "?filter=%5B%7B%22name%22%3A%22VISIBILITY%22%2C%22value%22%3A%5B%22PRIVATE%22%5D%7D%5D"
    "&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D"
)
BROWSER_PROFILE_DIR = "./browser_profile"
DUMPS_DIR = "./dumps"
OUTPUT_VIDEO_LIST   = f"{DUMPS_DIR}/video_list.html"
OUTPUT_LINKS        = f"{DUMPS_DIR}/video_list_links.txt"
OUTPUT_EDIT         = f"{DUMPS_DIR}/edit_page.html"
OUTPUT_TRANSLATIONS = f"{DUMPS_DIR}/translations_page.html"
DEBUG_PAUSE = 2.0


def log(msg: str):
    """Вывод сообщения с временной меткой."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def save_html(page, path: str):
    """Сохранить page.content() в файл (перезапись)."""
    html = page.content()
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Дамп сохранён → {path} ({len(html)} байт)")
    return html


def connect_to_chrome(p):
    """Запустить Chrome если не запущен, вернуть (browser, page)."""
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    profile_path = os.path.abspath(BROWSER_PROFILE_DIR)

    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1)
        log("Chrome уже запущен на порту 9222")
    except Exception:
        log("Запускаю Chrome...")
        subprocess.Popen([
            chrome_path,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile_path}",
            "--no-first-run",
            "--no-default-browser-check",
        ])
        for _ in range(15):
            try:
                urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1)
                break
            except Exception:
                time.sleep(1)

    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    return page


def main():
    """Дампит три страницы: список видео, /edit первого, /translations первого."""
    os.makedirs(DUMPS_DIR, exist_ok=True)
    with sync_playwright() as p:
        page = connect_to_chrome(p)

        # 1. Список видео
        log("Открываю список Private видео...")
        page.goto(STUDIO_FILTERED_URL)
        try:
            page.wait_for_selector("table[aria-label='Video list']", timeout=5000)
            log("Таблица найдена")
        except PlaywrightTimeoutError:
            log("Таблица не появилась — сохраняю что есть")
        time.sleep(DEBUG_PAUSE)
        save_html(page, OUTPUT_VIDEO_LIST)

        # Извлекаем ссылки /edit
        results = page.evaluate("""() => {
            const links = document.querySelectorAll("a[href*='/video/'][href*='/edit']");
            return Array.from(links).map(a => {
                const row = a.closest('tr');
                return {
                    href: a.href,
                    linkText: a.innerText.trim(),
                    rowText: row ? row.innerText.trim().substring(0, 300) : 'NO ROW'
                };
            });
        }""")
        with open(OUTPUT_LINKS, "w", encoding="utf-8") as f:
            f.write(f"Найдено ссылок /edit: {len(results)}\n{'=' * 60}\n\n")
            for i, item in enumerate(results, 1):
                f.write(f"[{i}] href:     {item['href']}\n")
                f.write(f"    linkText: '{item['linkText']}'\n")
                f.write(f"    rowText:  {item['rowText']}\n\n")
        log(f"Ссылки сохранены → {OUTPUT_LINKS} ({len(results)} шт.)")

        if not results:
            log("Нет видео — дампы /edit и /translations пропускаю")
            return

        # 2. Страница /edit первого видео
        edit_url = results[0]["href"]
        log(f"Открываю /edit: {edit_url}")
        page.goto(edit_url)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(DEBUG_PAUSE)
        save_html(page, OUTPUT_EDIT)

        # 3. Страница /translations первого видео
        translations_url = edit_url.replace("/edit", "/translations")
        log(f"Открываю /translations: {translations_url}")
        page.goto(translations_url)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(DEBUG_PAUSE)
        save_html(page, OUTPUT_TRANSLATIONS)

        log("Готово.")


if __name__ == "__main__":
    main()
