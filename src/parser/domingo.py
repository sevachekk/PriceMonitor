import aiohttp
import asyncio
import re
from urllib.parse import quote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://domingo.su/",
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


async def get_domingo_product_price(product_name: str) -> int:
    """
    Возвращает цену ПЕРВОГО товара на domingo.su.
    Если товаров не найдено — возвращает 0.
    """
    encoded_name = quote(product_name)
    search_url = f"https://domingo.su/catalog/search/?q={encoded_name}"

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # 1. Поисковая страница
        async with session.get(search_url) as response:
            if response.status != 200:
                print(f"❌ Ошибка поиска (статус {response.status})")
                return 0
            search_html = await response.text()

        # === НОВАЯ ПРОВЕРКА: «Ничего не найдено» ===
        if any(phrase in search_html for phrase in [
            "К сожалению, по вашему запросу",
            "ничего не найдено",
            "По вашему запросу ничего не найдено"
        ]):
            print("🔍 По запросу ничего не найдено")
            return 0

        # 2. Ищем ссылку на первый товар
        link_match = re.search(r'href="(/product/[^"]+)"', search_html)
        if not link_match:
            print("❌ Ссылка на товар не найдена (возможно, пустая выдача)")
            return 0

        relative_url = link_match.group(1)
        product_url = f"https://domingo.su{relative_url}"

        # 3. Страница товара
        async with session.get(product_url) as response:
            if response.status != 200:
                print(f"❌ Ошибка страницы товара (статус {response.status})")
                return 0
            product_html = await response.text()

        # 4. Извлекаем цену
        # Основной способ (data-price)
        price_match = re.search(r'data-price="(\d+)"', product_html)
        if price_match:
            price = int(price_match.group(1))
            return price

        # Запасной способ (текст с ₽)
        price_match2 = re.search(r'([\d\s]+)\s*₽', product_html)
        if price_match2:
            price_str = price_match2.group(1).replace(' ', '')
            if price_str.isdigit():
                return int(price_str)

        print("❌ Цена не найдена даже запасным способом")
        return 0