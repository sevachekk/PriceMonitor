from utils.repository import AbstractRepository
from models.prices import CompetitorPrice, Alert, Notification
from schemas.prices import CompetitorPriceSchema, CompetitorAddPriceSchema, AlertAddSchema, AlertSchema, NotificationAddSchema, NotificationSchema
from schemas.pagination import PaginationSchema


class CompetitorPriceService:
    def __init__(self, repository: AbstractRepository[CompetitorPrice]):
        self.repository = repository

    async def add_price(self, price: CompetitorAddPriceSchema) -> int:
        price_dict = price.model_dump()
        res = await self.repository.add(price_dict)
        return res
    
    async def get_price(self, **filter_by) -> dict:
        res = await self.repository.get(**filter_by)
        return res

    async def get_prices(self, pagination: PaginationSchema | None = None, **filter_by) -> list[CompetitorPriceSchema]:
        pagination_dict = pagination.model_dump() if pagination else {}
        res = await self.repository.get_list(pagination_dict, **filter_by)
        return res
    
    async def remove_prices(self, **filter_by) -> int:
        res = await self.repository.delete(**filter_by)
        return res
    
    async def update_price(self, update_data: CompetitorAddPriceSchema, **filter_by) -> int:
        update_data_dict = update_data.model_dump()
        res = await self.repository.update(update_data_dict, **filter_by)
        return res
    
    
class AlertService:
    def __init__(self, repository: AbstractRepository[Alert]):
        self.repository = repository

    async def add_alert(self, alert: AlertAddSchema) -> int:
        alert_dict = alert.model_dump()
        res = await self.repository.add(alert_dict)
        return res
    
    async def get_alert(self, **filter_by) -> dict:
        res = await self.repository.get(**filter_by)
        return res

    async def get_alerts(self, pagination: PaginationSchema | None = None, **filter_by) -> list[AlertSchema]:
        pagination_dict = pagination.model_dump() if pagination else {}
        res = await self.repository.get_list(pagination_dict, **filter_by)
        return res
    
    async def remove_alerts(self, **filter_by) -> int:
        res = await self.repository.delete(**filter_by)
        return res
    
    async def update_alert(self, update_data: AlertAddSchema, **filter_by) -> int:
        update_data_dict = update_data.model_dump()
        res = await self.repository.update(update_data_dict, **filter_by)
        return res
    
    
class NotificationService:
    def __init__(self, repository: AbstractRepository[Notification]):
        self.repository = repository

    async def add_notification(self, notification: NotificationAddSchema) -> int:
        notification_dict = notification.model_dump()
        res = await self.repository.add(notification_dict)
        return res
    
    async def get_notification(self, **filter_by) -> dict:
        res = await self.repository.get(**filter_by)
        return res

    async def get_notifications(self, pagination: PaginationSchema | None = None, **filter_by) -> list[NotificationSchema]:
        pagination_dict = pagination.model_dump() if pagination else {}
        res = await self.repository.get_list(pagination_dict, **filter_by)
        return res
    
    async def remove_notifications(self, **filter_by) -> int:
        res = await self.repository.delete(**filter_by)
        return res
    
    async def update_notification(self, update_data: NotificationAddSchema, **filter_by) -> int:
        update_data_dict = update_data.model_dump()
        res = await self.repository.update(update_data_dict, **filter_by)
        return res