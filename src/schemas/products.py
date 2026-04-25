# schemas/products.py
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CompetitorAddSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    base_url: str


class CompetitorSchema(CompetitorAddSchema):
    id: int
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, v: datetime, _info):
        return v.isoformat()
