# schemas/prices.py
from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from enum import Enum

class AlertType(str, Enum):
    zscore = 'zscore'
    pct_change = 'pct_change'
    below_threshold = 'below_threshold'


class CompetitorAddPriceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int | None = Field(default=None)
    competitor_id: int | None = Field(default=None)
    price: float | None = Field(gt=0, default=None)
    currency: str | None = Field(default=None, max_length=8)


class CompetitorPriceSchema(CompetitorAddPriceSchema):
    id: int
    # теперь datetime
    scraped_at: datetime

    # сериализуем в ISO-строку при выдаче
    @field_serializer("scraped_at")
    def _serialize_scraped_at(self, v: datetime, _info):
        return v.isoformat()


class AlertAddSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: Optional[int]
    competitor_id: Optional[int]
    type: AlertType
    params: dict
    recipients: list
    enabled: bool = True


class AlertSchema(AlertAddSchema):
    id: int
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, v: datetime, _info):
        return v.isoformat()


class NotificationAddSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: Optional[int]
    product_id: Optional[int]
    competitor_id: Optional[int]
    payload: dict


class NotificationSchema(NotificationAddSchema):
    id: int
    sent_at: datetime

    @field_serializer("sent_at")
    def _serialize_sent_at(self, v: datetime, _info):
        return v.isoformat()
