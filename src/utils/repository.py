from typing import Generic, TypeVar
from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update, delete


T = TypeVar('T')
class AbstractRepository(Generic[T], ABC):
    @abstractmethod
    async def add(self, obj):
        pass

    @abstractmethod
    async def get(self):
        pass
    
    @abstractmethod
    async def get_list(self):
        pass
    
    @abstractmethod
    async def update(self):
        pass

    @abstractmethod
    async def delete(self):
        pass

class SQLAlchemyRepository(AbstractRepository[T]):
    model = None
    
    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def add(self, data: dict):
        obj = self.model(**data)
        
        # Добавляем его в сессию (теперь он попадет в session.new)
        self.session.add(obj)
        
        # Flush отправит данные в БД и вызовет ваше событие after_flush
        await self.session.flush() 
        await self.session.commit()
        
        return obj.id
    
    async def get(self, **filter_by):
        q = select(self.model)
        
        for key, value in filter_by.items():
            if hasattr(self.model, key) and value is not None:
                q = q.where(getattr(self.model, key) == value)
                
        q = await self.session.execute(q)
        res = q.scalar_one_or_none()
        
        return res.to_read_model() if res else None
        
    async def get_list(self, pagination: dict, **filter_by):
        q = select(self.model)
        
        for key, value in filter_by.items():
            if hasattr(self.model, key) and value is not None:
                q = q.where(getattr(self.model, key) == value)
        
        if pagination:
            q = q.limit(pagination["limit"]).offset(pagination["offset"])
            
        q = await self.session.execute(q)
        res = [r[0].to_read_model() for r in q]
        
        return res
    
    async def update(self, update_data: dict, **filter_by):
        q = update(self.model)
        
        for key, value in filter_by.items():
            if hasattr(self.model, key) and value is not None:
                q = q.where(getattr(self.model, key) == value)
        
        q = q.values(**update_data).returning(self.model.id)
        
        res = await self.session.execute(q)
        await self.session.commit()
        
        return res.scalar_one()
    
    async def delete(self, **filter_by):
        q = delete(self.model)
        
        for key, value in filter_by.items():
            if hasattr(self.model, key) and value is not None:
                q = q.where(getattr(self.model, key) == value)
                
        q = q.returning(self.model.id)
        
        res = await self.session.execute(q)
        await self.session.commit()
        
        return res.scalar_one()
