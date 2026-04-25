import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from parser.browser import get_chromium_launch_options

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Sec-Ch-Ua": '"Not-A.Brand";v="8", "Chromium";v="134", "Google Chrome";v="134"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Cache-Control": "max-age=0",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_cookie_candidates(filename: str) -> list[Path]:
    cookies_dir = os.getenv("COOKIES_DIR")
    candidates: list[Path] = []
    if cookies_dir:
        candidates.append(Path(cookies_dir) / filename)
    candidates.extend([
        PROJECT_ROOT / "cookies" / filename,
        PROJECT_ROOT / filename,
    ])

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate_str)
    return unique_candidates


def find_cookie_file(filename: str) -> Path | None:
    for candidate in get_cookie_candidates(filename):
        if candidate.exists():
            return candidate
    return None


def get_cookie_search_locations(filename: str) -> list[str]:
    return [str(candidate) for candidate in get_cookie_candidates(filename)]


def clean_cookies(cookies: list) -> list:
    """Исправляет common проблемы с sameSite"""
    for cookie in cookies:
        # Нормализация sameSite
        if "sameSite" in cookie:
            val = cookie["sameSite"]
            if val is None or str(val).lower() in ["none", "no_restriction", ""]:
                cookie["sameSite"] = "None"
            elif str(val).lower() == "strict":
                cookie["sameSite"] = "Strict"
            elif str(val).lower() == "lax":
                cookie["sameSite"] = "Lax"
            else:
                cookie["sameSite"] = "Lax"  # безопасный дефолт
        else:
            cookie["sameSite"] = "Lax"
        # Приводим expires к int (если float)
        if "expires" in cookie and isinstance(cookie["expires"], float):
            cookie["expires"] = int(cookie["expires"])
    return cookies


async def get_lemana_product_price(product_name: str) -> int:
    """
    Возвращает цену ПЕРВОГО товара на lemanapro.ru (krasnoyarsk).
    Если «Не найдено» / «ничего не найдено» — возвращает 0.
    Адаптировано под актуальную верстку (data-testid="price-integer").
    """
    encoded_name = quote(product_name)
    search_url = f"https://krasnoyarsk.lemanapro.ru/search/?q={encoded_name}&suggest=true"

    async with async_playwright() as p:
        browser = await p.chromium.launch(**get_chromium_launch_options())
        context = await browser.new_context()

        # === Загрузка cookies (исправлено название файла) ===
        try:
            cookie_file = find_cookie_file("cookie_lemana.txt")
            if cookie_file is None:
                raise FileNotFoundError(
                    f"cookie_lemana.txt; searched: {', '.join(get_cookie_search_locations('cookie_lemana.txt'))}"
                )

            with cookie_file.open("r", encoding="utf-8") as f:
                cookies_data = json.load(f)
            if isinstance(cookies_data, dict) and "cookies" in cookies_data:
                cookies_data = cookies_data["cookies"]
            if not isinstance(cookies_data, list):
                raise ValueError("Неверный формат cookie_lemana.txt")
            cleaned_cookies = clean_cookies(cookies_data)
            await context.add_cookies(cleaned_cookies)
            print("✅ Cookies успешно загружены и очищены из cookie_lemana.txt")
        except FileNotFoundError as exc:
            print(f"⚠️ {exc}. Продолжаем без cookies.")
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке cookie_lemana.txt: {e}")
            print(" Продолжаем без cookies.")

        page = await context.new_page()
        await page.set_extra_http_headers(HEADERS)

        await page.goto(search_url, wait_until="domcontentloaded")
        await page.reload(wait_until="domcontentloaded")

        # === Проверка «ничего не найдено» (текст присутствует в error-layout) ===
        try:
            nothing_locator = page.get_by_text("ничего не найдено", exact=False)
            await nothing_locator.wait_for(timeout=5000)
            await browser.close()
            return 0
        except PlaywrightTimeoutError:
            pass  # товар есть — продолжаем

        # === Ожидание цены первого товара (новый селектор из актуальной верстки) ===
        try:
            await page.wait_for_selector('[data-testid="price-integer"]', timeout=15000)
        except PlaywrightTimeoutError:
            await browser.close()
            raise TimeoutError("Не найдена цена товара и не обнаружено сообщение «Ничего не найдено»")

        # Берём цену ПЕРВОГО товара
        price_locator = page.locator('[data-testid="price-integer"]').first
        price_text = await price_locator.text_content()

        clean_price = "".join(c for c in price_text if c.isdigit())
        if not clean_price:
            await browser.close()
            raise ValueError(f"Не удалось извлечь цену. Получено: {price_text}")

        price_int = int(clean_price)
        await browser.close()
        return price_int
