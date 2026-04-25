# models/prices.py
from __future__ import annotations
from enum import Enum
from typing import TYPE_CHECKING, List
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, Enum as SQLAlchemyEnum
from sqlalchemy import Float, String, DateTime, JSON, Boolean, func

from db.db import Base
from schemas.prices import AlertSchema, CompetitorPriceSchema, NotificationSchema

if TYPE_CHECKING:
    from .products import CatalogProduct, Competitor


class CompetitorPrice(Base):
    __tablename__ = 'competitor_prices'

    id: Mapped[int] = mapped_column(primary_key=True)
    # здесь ссылка на thin-таблицу product
    product_id: Mapped[int] = mapped_column(
        ForeignKey("public.products_catalogproduct.id", ondelete="CASCADE"),
        nullable=False,
    )
    competitor_id: Mapped[int] = mapped_column(ForeignKey('competitors.id', ondelete="CASCADE"))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(length=8), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product: Mapped["CatalogProduct"] = relationship("CatalogProduct", back_populates="competitor_prices")
    competitor: Mapped["Competitor"] = relationship("Competitor", back_populates="competitor_prices")

    def to_read_model(self) -> CompetitorPriceSchema:
        return CompetitorPriceSchema(
            id=self.id,
            product_id=self.product_id,
            competitor_id=self.competitor_id,
            price=self.price,
            currency=self.currency,
            scraped_at=self.scraped_at.isoformat() if isinstance(self.scraped_at, datetime) else self.scraped_at,
        )


class AlertType(str, Enum):
    zscore = 'zscore'
    pct_change = 'pct_change'
    below_threshold = 'below_threshold'


class Alert(Base):
    __tablename__ = 'alerts'

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.products_catalogproduct.id", ondelete="CASCADE"),
        nullable=True,
    )
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey('competitors.id', ondelete="CASCADE"), nullable=True)
    type: Mapped[AlertType] = mapped_column(SQLAlchemyEnum(AlertType), nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    product: Mapped["CatalogProduct"] = relationship("CatalogProduct", back_populates="alerts")
    competitor: Mapped["Competitor"] = relationship("Competitor", back_populates="alerts")
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="alert",
        passive_deletes=True,
    )

    def to_read_model(self) -> AlertSchema:
        return AlertSchema(
            id=self.id,
            product_id=self.product_id,
            competitor_id=self.competitor_id,
            type=self.type.value if isinstance(self.type, AlertType) else self.type,
            params=self.params,
            recipients=self.recipients,
            enabled=self.enabled,
            created_at=self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
        )


class Notification(Base):
    __tablename__ = 'notifications'

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey('alerts.id', ondelete='SET NULL'), nullable=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("public.products_catalogproduct.id", ondelete="SET NULL"),
        nullable=True,
    )
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey('competitors.id', ondelete="SET NULL"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    alert: Mapped["Alert"] = relationship("Alert", back_populates="notifications")
    product: Mapped["CatalogProduct"] = relationship("CatalogProduct", back_populates="notifications")
    competitor: Mapped["Competitor"] = relationship("Competitor", back_populates="notifications")

    def to_read_model(self) -> NotificationSchema:
        return NotificationSchema(
            id=self.id,
            alert_id=self.alert_id,
            product_id=self.product_id,
            competitor_id=self.competitor_id,
            payload=self.payload,
            sent_at=self.sent_at.isoformat() if isinstance(self.sent_at, datetime) else self.sent_at,
        )
