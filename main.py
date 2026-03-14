# main.py
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import re

STUDIO_FILTERED_URL = (
    "https://studio.youtube.com/channel/UC9JODm8Vze3gdkL9x27eFwA/videos/upload"
    "?filter=%5B%7B%22name%22%3A%22VISIBILITY%22%2C%22value%22%3A%5B%22PRIVATE%22%5D%7D%5D"
    "&sort=%7B%22columnType%22%3A%22date%22%2C%22sortOrder%22%3A%22DESCENDING%22%7D"
)
CHECK_INTERVAL = 300  # секунд между проверками (5 минут)
BROWSER_PROFILE_DIR = "./browser_profile"


def log(msg: str):
    """Вывод сообщения с временной меткой."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}")


def find_private_videos(page) -> list[dict]:
    """
    Найти все видео на отфильтрованной странице (только Private).
    Возвращает список {'title': str, 'video_id': str}.
    Поддерживает до 10 видео (и более — цикл универсальный).
    """
    try:
        page.wait_for_selector("table[aria-label='Video list']", timeout=15000)
    except PlaywrightTimeoutError:
        log("WARN: таблица видео не найдена — страница ещё грузится")
        return []

    # position()>1 — пропускаем строку-заголовок таблицы
    edit_links = page.query_selector_all(
        "xpath=//table[@aria-label='Video list']"
        "//tr[@role='row'][position()>1]"
        "//a[contains(@href, '/edit')]"
    )

    videos = []
    for link in edit_links:
        href = link.get_attribute("href") or ""
        match = re.search(r"/video/([^/]+)/edit", href)
        if not match:
            continue

        video_id = match.group(1)

        # TODO: уточнить где находится текст названия видео в DOM.
        # inner_text() ссылки /edit может быть пустым (если ссылка оборачивает thumbnail).
        # Возможно, название — в соседнем элементе внутри той же строки tr.
        title = link.inner_text().strip()
        if not title:
            log(f"WARN: пустой title для video_id={video_id} — нужно уточнить селектор названия")
            title = video_id  # временный fallback: используем ID как идентификатор

        videos.append({"title": title, "video_id": video_id})

    return videos


def wait_for_save_confirmation(page) -> bool:
    """
    Ждать подтверждения что Save прошёл успешно.
    TODO: уточнить точный признак по реальной странице YouTube Studio.
    Логика: читаем DOM после Save и ищем подтверждение изменения.
    """
    # Вариант 1: появляется toast/snackbar
    try:
        page.wait_for_selector(
            "ytcp-notification-action-renderer, [class*='toast'], paper-toast",
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

    log("WARN: не удалось подтвердить сохранение — нужно уточнить селектор по реальной странице")
    return False


def set_language_russian(page, video_title: str, video_id: str) -> bool:
    """
    Открыть страницу редактирования видео, выставить язык Russian, сохранить.
    Возвращает True если язык успешно сохранён.
    """
    edit_url = f"https://studio.youtube.com/video/{video_id}/edit"

    try:
        page.goto(edit_url)
        page.wait_for_load_state("networkidle", timeout=15000)

        # TODO: уточнить селектор поля Language по реальной странице редактирования
        language_dropdown = page.locator(
            "ytcp-form-select[name='language'], "
            "[placeholder*='Language'], "
            "ytcp-dropdown-trigger:has-text('Language')"
        ).first
        language_dropdown.click()

        # TODO: уточнить как выглядит опция Russian в выпадающем списке
        russian_option = page.locator(
            "tp-yt-paper-item:has-text('Russian'), "
            "[data-value='ru'], "
            "ytcp-menu-item:has-text('Russian')"
        ).first
        russian_option.click()

        save_btn = page.locator("#save-button, button:has-text('Save')").first
        save_btn.click()

        success = wait_for_save_confirmation(page)

        page.goto(STUDIO_FILTERED_URL)
        page.wait_for_selector("table[aria-label='Video list']", timeout=15000)

        return success

    except PlaywrightTimeoutError as e:
        log(f"TIMEOUT при обработке '{video_title}': {e}")
        page.goto(STUDIO_FILTERED_URL)
        return False
    except Exception as e:
        log(f"ERROR при обработке '{video_title}': {e}")
        page.goto(STUDIO_FILTERED_URL)
        return False


def main():
    """Основной демон: мониторит Private видео каждые 5 минут и выставляет язык Russian."""
    processed_titles: set[str] = set()

    log("Запуск YouTube Studio Auto Language Setter")
    log(f"Интервал проверки: {CHECK_INTERVAL // 60} минут")

    with sync_playwright() as p:
        log("Запускаю браузер (persistent profile)...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=False,
            channel="chrome",
        )
        page = context.new_page()

        log("Открываю YouTube Studio (только Private видео)...")
        page.goto(STUDIO_FILTERED_URL)

        try:
            while True:
                log("Проверяю Private видео...")

                private_videos = find_private_videos(page)
                log(f"Найдено Private видео: {len(private_videos)}")

                new_videos = [v for v in private_videos if v["title"] not in processed_titles]
                log(f"Новых (не обработанных): {len(new_videos)}")

                for video in new_videos:
                    title = video["title"]
                    video_id = video["video_id"]
                    log(f"Обрабатываю: {title} (id={video_id})")

                    success = set_language_russian(page, title, video_id)

                    if success:
                        processed_titles.add(title)
                        log(f"OK: '{title}' → язык Russian установлен")
                    else:
                        log(f"FAIL: '{title}' — попробую в следующем цикле")

                log(f"Обработано в этой сессии: {len(processed_titles)}")
                log(f"Следующая проверка через {CHECK_INTERVAL // 60} мин. Ctrl+C для остановки.")

                time.sleep(CHECK_INTERVAL)

                page.goto(STUDIO_FILTERED_URL)
                page.wait_for_selector("table[aria-label='Video list']", timeout=15000)

        except KeyboardInterrupt:
            log("Остановлено пользователем (Ctrl+C)")
        finally:
            context.close()


if __name__ == "__main__":
    main()
