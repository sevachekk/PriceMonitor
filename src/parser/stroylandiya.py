import asyncio
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


async def get_stroylandiya_product_price(product_name: str) -> int:
    """
    Возвращает цену ПЕРВОГО товара на stroylandiya.ru.
    Если «По вашему запросу ничего не найдено» — возвращает 0.
    """
    encoded_name = quote(product_name)
    search_url = f"https://stroylandiya.ru/search/?q={encoded_name}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(**get_chromium_launch_options())
        page = await browser.new_page()
        await page.set_extra_http_headers(HEADERS)

        await page.goto(search_url, wait_until="domcontentloaded")
        await page.reload(wait_until="domcontentloaded")

        try:
            title_locator = page.locator("h1#pagetitle")
            title_text = await title_locator.inner_text(timeout=5000)
            if "ничего не найдено" in title_text.lower():
                await browser.close()
                return 0
        except PlaywrightTimeoutError:
            pass

        try:
            await page.wait_for_selector(".fb-product-card__price-value", timeout=15000)
        except PlaywrightTimeoutError:
            await browser.close()
            raise TimeoutError("Не найдена ни цена товара, ни сообщение «ничего не найдено»")

        price_locator = page.locator(".fb-product-card__price-value").first
        price_text = await price_locator.text_content()

        clean_price = "".join(c for c in price_text if c.isdigit())
        if not clean_price:
            await browser.close()
            raise ValueError(f"Не удалось извлечь цену. Получено: {price_text}")

        price_int = int(clean_price)
        await browser.close()
        return price_int
