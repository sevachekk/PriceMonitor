import asyncio
from collections.abc import Awaitable, Callable

from db.db import async_session
from dependencies.prices import get_alert_service, get_competitor_price_service
from dependencies.products import get_catalog_product_service, get_competitor_service
from parser.domingo import get_domingo_product_price
from parser.lemana import get_lemana_product_price
from parser.stroylandiya import get_stroylandiya_product_price
from parser.wildberries import get_wildberries_product_price
from parser.yandex import get_yandex_product_price
from schemas.prices import CompetitorAddPriceSchema
from sqlalchemy.exc import SQLAlchemyError

ParserFunc = Callable[[str], Awaitable[int]]

PARSERS_BY_COMPETITOR_NAME: dict[str, ParserFunc] = {
    "domingo": get_domingo_product_price,
    "stroylandiya": get_stroylandiya_product_price,
    "wildberries": get_wildberries_product_price,
    "yandex": get_yandex_product_price,
    "lemana": get_lemana_product_price,
}


def normalize_competitor_name(name: str) -> str:
    return name.strip().lower()


def get_parser_for_competitor(name: str) -> ParserFunc | None:
    return PARSERS_BY_COMPETITOR_NAME.get(normalize_competitor_name(name))


async def _load_parsing_scope() -> tuple[list, list, dict[int, set[int] | None], dict[int, str], dict[int, str]]:
    async with async_session() as session:
        alert_service = get_alert_service(session=session)
        competitor_service = get_competitor_service(session=session)
        catalog_product_service = get_catalog_product_service(session=session)

        alerts = await alert_service.get_alerts(pagination=None, enabled=True)
        competitors = await competitor_service.get_competitors(pagination=None)
        products_scope: dict[int, set[int] | None] = {}

        for alert in alerts:
            if alert.product_id is None:
                continue

            current_scope = products_scope.get(alert.product_id)
            if current_scope is None and alert.product_id in products_scope:
                continue

            if alert.competitor_id is None:
                products_scope[alert.product_id] = None
                continue

            if current_scope is None:
                products_scope[alert.product_id] = {alert.competitor_id}
            else:
                current_scope.add(alert.competitor_id)

        product_titles: dict[int, str] = {}
        product_statuses: dict[int, str] = {}
        for product_id in products_scope:
            product_data = await catalog_product_service.get_product_data(product_id, session)
            if not product_data:
                product_statuses[product_id] = "product_not_found"
                continue

            if not product_data.get("title"):
                product_statuses[product_id] = "missing_title"
                continue

            product_titles[product_id] = product_data["title"]

        return alerts, competitors, products_scope, product_titles, product_statuses


async def _save_price_with_retry(
    product_id: int,
    competitor_id: int,
    price: float,
    *,
    retries: int = 1,
) -> int:
    attempt = 0
    while True:
        try:
            async with async_session() as session:
                competitor_price_service = get_competitor_price_service(session=session)
                return await competitor_price_service.add_price(
                    CompetitorAddPriceSchema(
                        product_id=product_id,
                        competitor_id=competitor_id,
                        price=price,
                        currency="RUB",
                    )
                )
        except SQLAlchemyError:
            if attempt >= retries:
                raise
            attempt += 1


async def run_real_price_parsing() -> dict:
    _, competitors, products_scope, product_titles, product_statuses = await _load_parsing_scope()

    summary = {
        "message": "Real prices parsed",
        "products_total": len(products_scope),
        "prices_saved": 0,
        "created_price_ids": [],
        "unsupported_competitors": [],
        "not_found": [],
        "errors": [],
        "skipped_products": [],
    }

    for product_id, scoped_competitor_ids in products_scope.items():
        product_name = product_titles.get(product_id)
        if not product_name:
            summary["skipped_products"].append(
                {
                    "product_id": product_id,
                    "reason": product_statuses.get(product_id, "missing_title"),
                }
            )
            continue

        target_competitors = [
            competitor
            for competitor in competitors
            if scoped_competitor_ids is None or competitor.id in scoped_competitor_ids
        ]

        parser_jobs: list[tuple[int, str]] = []
        parser_tasks = []

        for competitor in target_competitors:
            parser = get_parser_for_competitor(competitor.name)
            if parser is None:
                summary["unsupported_competitors"].append(
                    {
                        "product_id": product_id,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                    }
                )
                continue

            parser_jobs.append((competitor.id, competitor.name))
            parser_tasks.append(parser(product_name))

        if not parser_tasks:
            continue

        results = await asyncio.gather(*parser_tasks, return_exceptions=True)

        for (competitor_id, competitor_name), result in zip(parser_jobs, results):
            if isinstance(result, Exception):
                summary["errors"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor_id,
                        "competitor_name": competitor_name,
                        "error": str(result),
                    }
                )
                continue

            if result <= 0:
                summary["not_found"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor_id,
                        "competitor_name": competitor_name,
                    }
                )
                continue

            try:
                price_id = await _save_price_with_retry(
                    product_id=product_id,
                    competitor_id=competitor_id,
                    price=float(result),
                )
            except SQLAlchemyError as exc:
                summary["errors"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor_id,
                        "competitor_name": competitor_name,
                        "error": f"db_write_failed: {exc}",
                    }
                )
                continue

            summary["prices_saved"] += 1
            summary["created_price_ids"].append(price_id)

    return summary
