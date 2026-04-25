from utils.repository import SQLAlchemyRepository
from models.prices import Alert, CompetitorPrice, Notification


class AlertRepository(SQLAlchemyRepository[Alert]):
    model = Alert
    
class CompetitorPriceRepository(SQLAlchemyRepository[CompetitorPrice]):
    model = CompetitorPrice
    
class NotificationRepository(SQLAlchemyRepository[Notification]):
    model = Notification