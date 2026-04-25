from db.db import CurrSession
from services.prices import AlertService, CompetitorPriceService, NotificationService
from repositories.prices import AlertRepository, CompetitorPriceRepository, NotificationRepository


def get_competitor_price_service(session: CurrSession) -> CompetitorPriceService:
    repository = CompetitorPriceRepository(session)
    service = CompetitorPriceService(repository)
    return service

def get_alert_service(session: CurrSession) -> AlertService:
    repository = AlertRepository(session)
    service = AlertService(repository)
    return service

def get_notification_service(session: CurrSession) -> NotificationService:
    repository = NotificationRepository(session)
    service = NotificationService(repository)
    return service