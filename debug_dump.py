# debug_dump.py
import sys
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time

STUDIO_FILTERED_URL = (
    "https://studio.youtube.com/channel/UC9JODm8Vze3gdkL9x27eFwA/videos/upload"
    "?filter=%5B%7B%22name%22%3A%22VISIBILITY%22%2C%22value%22%3A%5B%22PRIVATE%22%5D%7D%5D"
    "&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D"
)
BROWSER_PROFILE_DIR = "./browser_profile"
OUTPUT_HTML = "debug_dump.html"
OUTPUT_LINKS = "debug_links.txt"
OUTPUT_EDIT_HTML = "debug_edit_page.html"
DEBUG_MIN_PAUSE = 2.0  # минимальная пауза между шагами (секунды)


def log(msg: str):
    """Вывод сообщения с временной меткой."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


def debug_wait(page, selector: str, timeout: int = 30000):
    """Ждать появления селектора, но не менее DEBUG_MIN_PAUSE секунд."""
    start = time.time()
    page.wait_for_selector(selector, timeout=timeout)
    elapsed = time.time() - start
    remaining = DEBUG_MIN_PAUSE - elapsed
    if remaining > 0:
        time.sleep(remaining)


def main():
    """Открыть страницу, дождаться таблицы, сохранить HTML и данные ссылок + страницу редактирования."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=False,
            slow_mo=2000,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()

        log("Открываю страницу списка видео (только Private)...")
        page.goto(STUDIO_FILTERED_URL)

        log("Жду таблицу... (если нужен логин — залогинься в браузере)")
        try:
            debug_wait(page, "table[aria-label='Video list']", timeout=40000)
            log("Таблица найдена!")
        except PlaywrightTimeoutError:
            log("Таблица не появилась за 120 сек — сохраняю что есть")

        log("Сохраняю HTML страницы списка...")
        html = page.content()
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"HTML сохранён → {OUTPUT_HTML} ({len(html)} байт)")

        log("Извлекаю данные по ссылкам /edit...")
        results = page.evaluate("""() => {
            const links = document.querySelectorAll("a[href*='/edit']");
            return Array.from(links).map(a => {
                const row = a.closest('tr');
                return {
                    href: a.href,
                    linkText: a.innerText.trim(),
                    linkHTML: a.innerHTML.trim().substring(0, 200),
                    rowText: row ? row.innerText.trim().substring(0, 300) : 'NO ROW'
                };
            });
        }""")

        with open(OUTPUT_LINKS, "w", encoding="utf-8") as f:
            f.write(f"Найдено ссылок /edit: {len(results)}\n")
            f.write("=" * 60 + "\n\n")
            for i, item in enumerate(results, 1):
                f.write(f"[{i}] href:     {item['href']}\n")
                f.write(f"    linkText: '{item['linkText']}'\n")
                f.write(f"    linkHTML: {item['linkHTML']}\n")
                f.write(f"    rowText:  {item['rowText']}\n")
                f.write("\n")

        log(f"Данные ссылок сохранены → {OUTPUT_LINKS} ({len(results)} ссылок)")

        if results:
            first_edit_url = results[0]["href"]
            log(f"Открываю страницу редактирования: {first_edit_url}")
            page.goto(first_edit_url)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
                time.sleep(DEBUG_MIN_PAUSE)
                log("Страница редактирования загружена")
            except PlaywrightTimeoutError:
                log("networkidle timeout — сохраняю что есть")

            log("Сохраняю HTML страницы редактирования...")
            edit_html = page.content()
            with open(OUTPUT_EDIT_HTML, "w", encoding="utf-8") as f:
                f.write(edit_html)
            log(f"HTML сохранён → {OUTPUT_EDIT_HTML} ({len(edit_html)} байт)")
        else:
            log("Нет ссылок /edit — пропускаю дамп страницы редактирования")

        log("Готово. Закрываю браузер.")
        context.close()


if __name__ == "__main__":
    main()
