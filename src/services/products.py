from utils.repository import AbstractRepository
from models.products import CatalogProduct, Competitor
from schemas.products import CompetitorAddSchema, CompetitorSchema
from schemas.pagination import PaginationSchema

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text
from db.db import CurrSession


class CatalogProductService:
    def __init__(self, repository: AbstractRepository[CatalogProduct]):
        self.repository = repository

    async def add_product(self, data: dict) -> int:
        res = await self.repository.add(data)
        return res
    
    async def get_product(self, **filter_by) -> dict:
        res = await self.repository.get(**filter_by)
        return res

    async def get_products(self, pagination: PaginationSchema | None = None, **filter_by) -> list[dict]:
        pagination_dict = pagination.model_dump() if pagination else {}
        res = await self.repository.get_list(pagination_dict, **filter_by)
        return res
    
    async def get_product_data(self, product_id: int, session: AsyncSession) -> dict:
        stmt = text("SELECT * FROM public.products_catalogproduct WHERE id = :id")
        result = await session.execute(stmt, {"id": product_id})
        row = result.mappings().first()
        if row is None:
            return None 
        return dict(row)
    
    async def remove_products(self, **filter_by) -> int:
        res = await self.repository.delete(**filter_by)
        return res
    
    async def update_product(self, update_data: dict, **filter_by) -> int:
        res = await self.repository.update(update_data, **filter_by)
        return res
    
    
class CompetitorService:
    def __init__(self, repository: AbstractRepository[Competitor]):
        self.repository = repository

    async def add_competitor(self, competitor: CompetitorAddSchema) -> int:
        competitor_dict = competitor.model_dump()
        res = await self.repository.add(competitor_dict)
        return res
    
    async def get_competitor(self, **filter_by) -> dict:
        res = await self.repository.get(**filter_by)
        return res

    async def get_competitors(self, pagination: PaginationSchema | None = None, **filter_by) -> list[CompetitorSchema]:
        pagination_dict = pagination.model_dump() if pagination else {}
        res = await self.repository.get_list(pagination_dict, **filter_by)
        return res
    
    async def remove_competitors(self, **filter_by) -> int:
        res = await self.repository.delete(**filter_by)
        return res
    
    async def update_competitor(self, update_data: CompetitorAddSchema, **filter_by) -> int:
        update_data_dict = update_data.model_dump()
        res = await self.repository.update(update_data_dict, **filter_by)
        return res