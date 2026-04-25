from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.db import Base
from schemas.products import CompetitorSchema

if TYPE_CHECKING:
    from .prices import Alert, CompetitorPrice, Notification


class CatalogProduct(Base):
    __tablename__ = "products_catalogproduct"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(primary_key=True)

    competitor_prices: Mapped[list["CompetitorPrice"]] = relationship(
        "CompetitorPrice",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    alerts: Mapped[list["Alert"]] = relationship(
        "Alert",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="product",
        passive_deletes=True,
    )



class Competitor(Base):
    __tablename__ = 'competitors'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    base_url: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # relationships
    competitor_prices: Mapped[list["CompetitorPrice"]] = relationship(
        "CompetitorPrice",
        back_populates="competitor",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert",
        back_populates="competitor",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="competitor",
        passive_deletes=True,
    )
    
    def to_read_model(self) -> CompetitorSchema:
        return CompetitorSchema(
            id = self.id,
            name = self.name,
            base_url = self.base_url,
            created_at = self.created_at,
        )
