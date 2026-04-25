import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from algorithms.anomaly_detection_algorithm import (
    BaselineChoice,
    DirectionChoice,
    detect_below_threshold,
    detect_pct_change,
    detect_zscore,
)
from db.db import async_session
from dependencies.prices import (
    get_alert_service,
    get_competitor_price_service,
    get_notification_service,
)
from dependencies.products import get_catalog_product_service, get_competitor_service
from models.admin import PlatformSetting
from models.prices import AlertType, CompetitorPrice
from schemas.prices import NotificationAddSchema
from utils.send_email import format_alert_email, send_alert_email


logger = logging.getLogger(__name__)

ALERT_PROCESSOR_STATE_KEY = "alert_processor_state"


@dataclass(slots=True)
class NewPriceEvent:
    price_id: int
    product_id: int
    competitor_id: int
    price: float
    scraped_at: datetime | None = None


def _normalize_alert_params(params: dict | None) -> dict:
    if not isinstance(params, dict):
        return {}

    nested_params = params.get("additionalProp1")
    if isinstance(nested_params, dict):
        return nested_params

    return params


async def _get_or_create_processor_state(session) -> PlatformSetting:
    setting = await session.scalar(
        select(PlatformSetting).where(PlatformSetting.key == ALERT_PROCESSOR_STATE_KEY)
    )
    if setting is not None:
        return setting

    max_price_id = await session.scalar(select(func.max(CompetitorPrice.id))) or 0
    setting = PlatformSetting(
        key=ALERT_PROCESSOR_STATE_KEY,
        value={"last_processed_competitor_price_id": int(max_price_id)},
        description="Служебное состояние фоновой обработки цен для alert-триггеров",
    )
    session.add(setting)
    await session.commit()
    await session.refresh(setting)
    logger.info(
        "Initialized alert processor state from competitor_price_id=%s",
        max_price_id,
    )
    return setting


async def _get_last_processed_price_id(session) -> int:
    setting = await _get_or_create_processor_state(session)
    value = setting.value if isinstance(setting.value, dict) else {}
    try:
        return int(value.get("last_processed_competitor_price_id", 0))
    except (TypeError, ValueError):
        return 0


async def _mark_price_processed(price_id: int) -> None:
    async with async_session() as session:
        setting = await _get_or_create_processor_state(session)
        value = setting.value if isinstance(setting.value, dict) else {}
        current_id = int(value.get("last_processed_competitor_price_id", 0) or 0)
        if price_id <= current_id:
            return

        setting.value = {
            **value,
            "last_processed_competitor_price_id": int(price_id),
        }
        await session.commit()


async def _load_price_event_by_id(price_id: int) -> NewPriceEvent | None:
    async with async_session() as session:
        price_row = await session.get(CompetitorPrice, price_id)
        if price_row is None:
            return None

        return NewPriceEvent(
            price_id=price_row.id,
            product_id=price_row.product_id,
            competitor_id=price_row.competitor_id,
            price=float(price_row.price),
            scraped_at=price_row.scraped_at,
        )


def _is_history_row_before_event(row, price_event: NewPriceEvent) -> bool:
    if row.id == price_event.price_id:
        return False

    if price_event.scraped_at is None or row.scraped_at is None:
        return row.id < price_event.price_id

    if row.scraped_at < price_event.scraped_at:
        return True

    if row.scraped_at > price_event.scraped_at:
        return False

    return row.id < price_event.price_id


async def _deliver_alert_email(
    *,
    recipients: list,
    subject: str,
    plain_body: str,
    html_body: str | None,
    price_event: NewPriceEvent,
    alert_id: int,
) -> None:
    try:
        await send_alert_email(
            recipients=recipients,
            subject=subject,
            plain_body=plain_body,
            html_body=html_body,
        )
    except Exception:
        logger.exception(
            "Alert email delivery failed for alert_id=%s price_id=%s product_id=%s competitor_id=%s",
            alert_id,
            price_event.price_id,
            price_event.product_id,
            price_event.competitor_id,
        )


async def _persist_notification(
    *,
    notification_service,
    alert,
    price_event: NewPriceEvent,
    payload: dict,
) -> bool:
    existing_notifications = await notification_service.get_notifications(
        pagination=None,
        alert_id=alert.id,
        product_id=price_event.product_id,
        competitor_id=price_event.competitor_id,
    )
    for existing_notification in existing_notifications:
        existing_payload = existing_notification.payload or {}
        if existing_payload.get("price_event_id") == price_event.price_id:
            logger.info(
                "Skipping duplicate notification for alert_id=%s price_id=%s",
                alert.id,
                price_event.price_id,
            )
            return False

    notification_payload = {
        **payload,
        "price_event_id": price_event.price_id,
        "current_price": float(price_event.price),
    }
    await notification_service.add_notification(
        NotificationAddSchema(
            alert_id=alert.id,
            product_id=price_event.product_id,
            competitor_id=price_event.competitor_id,
            payload=notification_payload,
        )
    )
    return True


def _schedule_price_trigger(event_payload: NewPriceEvent) -> None:
    task = asyncio.create_task(handle_new_price(event_payload))

    def _log_task_result(completed_task: asyncio.Task) -> None:
        try:
            completed_task.result()
        except Exception:
            logger.exception(
                "Competitor price trigger failed for price_id=%s product_id=%s competitor_id=%s",
                event_payload.price_id,
                event_payload.product_id,
                event_payload.competitor_id,
            )

    task.add_done_callback(_log_task_result)


@event.listens_for(Session, "after_flush")
def receive_after_flush(session, flush_context):
    for obj in session.new:
        if isinstance(obj, CompetitorPrice):
            _schedule_price_trigger(
                NewPriceEvent(
                    price_id=obj.id,
                    product_id=obj.product_id,
                    competitor_id=obj.competitor_id,
                    price=float(obj.price),
                    scraped_at=obj.scraped_at,
                )
            )


async def handle_new_price(price_event: NewPriceEvent) -> dict:
    triggered_alert_ids: list[int] = []

    async with async_session() as session:
        alert_service = get_alert_service(session=session)
        competitor_price_service = get_competitor_price_service(session=session)
        competitor_service = get_competitor_service(session=session)
        catalog_product_service = get_catalog_product_service(session=session)
        notification_service = get_notification_service(session=session)

        alerts_for_product = await alert_service.get_alerts(
            product_id=price_event.product_id,
            enabled=True,
        )
        relevant_alerts = [
            alert
            for alert in alerts_for_product
            if alert.competitor_id is None or alert.competitor_id == price_event.competitor_id
        ]
        if not relevant_alerts:
            logger.info(
                "No relevant alerts for price_id=%s product_id=%s competitor_id=%s",
                price_event.price_id,
                price_event.product_id,
                price_event.competitor_id,
            )
            await _mark_price_processed(price_event.price_id)
            return {"price_id": price_event.price_id, "triggered_alert_ids": []}

        competitor_prices = await competitor_price_service.get_prices(
            product_id=price_event.product_id,
            competitor_id=price_event.competitor_id,
        )
        competitor_price_history = sorted(
            [res for res in competitor_prices if _is_history_row_before_event(res, price_event)],
            key=lambda res: (res.scraped_at, res.id),
        )
        competitor_prices_list = [res.price for res in competitor_price_history]
        current_competitor_price = float(price_event.price)

        product_data = await catalog_product_service.get_product_data(price_event.product_id, session)
        product_path = product_data.get("path") if product_data else None
        prod_url = f"https://pogos.ru/{product_path}" if product_path else None
        product_name = product_data.get("title") if product_data else None

        competitor = await competitor_service.get_competitor(id=price_event.competitor_id)
        competitor_name = competitor.name if competitor else str(price_event.competitor_id)

        for alert in relevant_alerts:
            alert_params = _normalize_alert_params(alert.params)
            min_samples = int(alert_params.get("min_samples", 3))
            if len(competitor_prices_list) < min_samples:
                logger.info(
                    "Skipped alert_id=%s for price_id=%s: not enough samples (%s/%s)",
                    alert.id,
                    price_event.price_id,
                    len(competitor_prices_list),
                    min_samples,
                )
                continue

            recent_history = competitor_prices_list[-min_samples:]
            recent_prices = recent_history + [current_competitor_price]

            if alert.type == AlertType.zscore:
                triggered, detection_info = detect_zscore(
                    prices=recent_history,
                    current_price=current_competitor_price,
                    min_samples=min_samples,
                    threshold=alert_params.get("threshold", 3),
                    min_std=float(alert_params.get("min_std", 1e-3)),
                    direction=alert_params.get("direction", DirectionChoice.BOTH),
                )
                if not triggered:
                    logger.info(
                        "Alert_id=%s not triggered for price_id=%s via zscore: %s",
                        alert.id,
                        price_event.price_id,
                        detection_info,
                    )
                    continue

                triggered_alert_ids.append(alert.id)
                notification_created = await _persist_notification(
                    notification_service=notification_service,
                    alert=alert,
                    price_event=price_event,
                    payload=detection_info,
                )
                if not notification_created:
                    continue

                plain, html = format_alert_email(
                    alert=alert,
                    alert_method="zscore",
                    competitor_name=competitor_name,
                    product_id=price_event.product_id,
                    product_name=product_name,
                    current_price=current_competitor_price,
                    recent_prices=recent_prices,
                    detection_info=detection_info,
                    prod_url=prod_url,
                )
                await _deliver_alert_email(
                    recipients=alert.recipients,
                    subject=f"Оповещение (Z-score) — продукт {price_event.product_id}, конкурент {competitor_name}",
                    plain_body=plain,
                    html_body=html,
                    price_event=price_event,
                    alert_id=alert.id,
                )
                logger.info(
                    "Triggered alert_id=%s for price_id=%s via zscore",
                    alert.id,
                    price_event.price_id,
                )

            elif alert.type == AlertType.pct_change:
                triggered, detection_info = detect_pct_change(
                    past_prices=recent_history,
                    current_price=current_competitor_price,
                    threshold_pct=alert_params.get("threshold_pct", 10.0),
                    baseline=alert_params.get("baseline", BaselineChoice.MEAN),
                    min_samples=int(alert_params.get("min_samples", 1)),
                    min_baseline=alert_params.get("min_baseline", 1e-6),
                    direction=alert_params.get("direction", DirectionChoice.BOTH),
                )
                if not triggered:
                    logger.info(
                        "Alert_id=%s not triggered for price_id=%s via pct_change: %s",
                        alert.id,
                        price_event.price_id,
                        detection_info,
                    )
                    continue

                triggered_alert_ids.append(alert.id)
                notification_created = await _persist_notification(
                    notification_service=notification_service,
                    alert=alert,
                    price_event=price_event,
                    payload=detection_info,
                )
                if not notification_created:
                    continue

                plain, html = format_alert_email(
                    alert=alert,
                    alert_method="pct_change",
                    competitor_name=competitor_name,
                    product_id=price_event.product_id,
                    product_name=product_name,
                    current_price=current_competitor_price,
                    recent_prices=recent_prices,
                    detection_info=detection_info,
                    prod_url=prod_url,
                )
                await _deliver_alert_email(
                    recipients=alert.recipients,
                    subject=f"Оповещение (Percent change) — продукт {price_event.product_id}, конкурент {competitor_name}",
                    plain_body=plain,
                    html_body=html,
                    price_event=price_event,
                    alert_id=alert.id,
                )
                logger.info(
                    "Triggered alert_id=%s for price_id=%s via pct_change",
                    alert.id,
                    price_event.price_id,
                )

            elif alert.type == AlertType.below_threshold:
                triggered, detection_info = detect_below_threshold(
                    past_prices=recent_history,
                    current_price=current_competitor_price,
                    threshold_value=alert_params.get("threshold_value"),
                    threshold_pct=alert_params.get("threshold_pct"),
                    pct_baseline=alert_params.get("pct_baseline", BaselineChoice.MEAN),
                    min_samples=int(alert_params.get("min_samples", 1)),
                    min_baseline=alert_params.get("min_baseline", 1e-6),
                )
                if not triggered:
                    logger.info(
                        "Alert_id=%s not triggered for price_id=%s via below_threshold: %s",
                        alert.id,
                        price_event.price_id,
                        detection_info,
                    )
                    continue

                triggered_alert_ids.append(alert.id)
                notification_created = await _persist_notification(
                    notification_service=notification_service,
                    alert=alert,
                    price_event=price_event,
                    payload=detection_info,
                )
                if not notification_created:
                    continue

                plain, html = format_alert_email(
                    alert=alert,
                    alert_method="below_threshold",
                    competitor_name=competitor_name,
                    product_id=price_event.product_id,
                    product_name=product_name,
                    current_price=current_competitor_price,
                    recent_prices=recent_prices,
                    detection_info=detection_info,
                    prod_url=prod_url,
                )
                await _deliver_alert_email(
                    recipients=alert.recipients,
                    subject=f"Оповещение (Below threshold) — продукт {price_event.product_id}, конкурент {competitor_name}",
                    plain_body=plain,
                    html_body=html,
                    price_event=price_event,
                    alert_id=alert.id,
                )
                logger.info(
                    "Triggered alert_id=%s for price_id=%s via below_threshold",
                    alert.id,
                    price_event.price_id,
                )

    if triggered_alert_ids:
        logger.info(
            "Processed price_id=%s product_id=%s competitor_id=%s and triggered alerts=%s",
            price_event.price_id,
            price_event.product_id,
            price_event.competitor_id,
            triggered_alert_ids,
        )

    await _mark_price_processed(price_event.price_id)
    return {"price_id": price_event.price_id, "triggered_alert_ids": triggered_alert_ids}


async def replay_price_trigger(price_id: int) -> dict:
    price_event = await _load_price_event_by_id(price_id)
    if price_event is None:
        raise ValueError(f"Competitor price with id={price_id} not found")

    return await handle_new_price(price_event)


async def process_pending_price_alerts(limit: int = 200) -> dict:
    async with async_session() as session:
        last_processed_price_id = await _get_last_processed_price_id(session)
        rows = list(
            (
                await session.scalars(
                    select(CompetitorPrice)
                    .where(CompetitorPrice.id > last_processed_price_id)
                    .order_by(CompetitorPrice.id.asc())
                    .limit(limit)
                )
            ).all()
        )

    if not rows:
        return {
            "initialized_from_price_id": last_processed_price_id,
            "processed_price_ids": [],
            "errors": [],
        }

    logger.info(
        "Processing pending price alerts from last_processed_price_id=%s, rows=%s",
        last_processed_price_id,
        len(rows),
    )

    summary = {
        "initialized_from_price_id": last_processed_price_id,
        "processed_price_ids": [],
        "errors": [],
    }

    for row in rows:
        price_event = NewPriceEvent(
            price_id=row.id,
            product_id=row.product_id,
            competitor_id=row.competitor_id,
            price=float(row.price),
            scraped_at=row.scraped_at,
        )
        try:
            await handle_new_price(price_event)
            summary["processed_price_ids"].append(row.id)
        except Exception as exc:
            logger.exception(
                "Pending price alert processing failed for price_id=%s product_id=%s competitor_id=%s",
                row.id,
                row.product_id,
                row.competitor_id,
            )
            await _mark_price_processed(row.id)
            summary["errors"].append(
                {
                    "price_id": row.id,
                    "product_id": row.product_id,
                    "competitor_id": row.competitor_id,
                    "error": str(exc),
                }
            )

    return summary
