from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from schemas.admin import (
    AdminAlertPayloadSchema,
    AdminAlertReadSchema,
    AdminUserReadSchema,
    AuthTokenResponseSchema,
    PlatformSettingReadSchema,
    SourceReadSchema,
)


T = TypeVar("T")


class PaginationParamsSchema(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    q: str | None = Field(default=None, max_length=255)


class PageMetaSchema(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class PaginatedResponseSchema(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMetaSchema


class AuthLoginResponseSchema(AuthTokenResponseSchema):
    pass


class CurrentPriceFilterSchema(PaginationParamsSchema):
    product_id: int | None = Field(default=None, ge=1)
    competitor_id: int | None = Field(default=None, ge=1)
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    scraped_from: datetime | None = None
    scraped_to: datetime | None = None


class PriceHistoryFilterSchema(PaginationParamsSchema):
    product_id: int | None = Field(default=None, ge=1)
    competitor_id: int | None = Field(default=None, ge=1)
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    scraped_from: datetime | None = None
    scraped_to: datetime | None = None


class SourceFilterSchema(PaginationParamsSchema):
    enabled: bool | None = None
    blocked: bool | None = None


class RuleFilterSchema(PaginationParamsSchema):
    product_id: int | None = Field(default=None, ge=1)
    competitor_id: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    type: Literal["zscore", "pct_change", "below_threshold"] | None = None


class BackupFilterSchema(PaginationParamsSchema):
    pass


class ServiceSettingFilterSchema(PaginationParamsSchema):
    key: str | None = Field(default=None, max_length=128)


class CurrentPriceReadSchema(BaseModel):
    price_id: int
    product_id: int
    competitor_id: int
    competitor_name: str
    price: float
    currency: str
    scraped_at: datetime
    previous_price: float | None = None
    change_abs: float | None = None
    change_pct: float | None = None

    @field_serializer("scraped_at")
    def _serialize_scraped_at(self, value: datetime, _info):
        return value.isoformat()


class PriceHistoryReadSchema(BaseModel):
    id: int
    product_id: int
    competitor_id: int
    competitor_name: str
    price: float
    currency: str
    scraped_at: datetime

    @field_serializer("scraped_at")
    def _serialize_scraped_at(self, value: datetime, _info):
        return value.isoformat()


class SourceConfigReadSchema(SourceReadSchema):
    pass


class RuleReadSchema(AdminAlertReadSchema):
    pass


class ServiceSettingReadSchema(PlatformSettingReadSchema):
    pass


class BackupManifestSchema(BaseModel):
    backup_name: str
    created_at: datetime
    size_bytes: int

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime, _info):
        return value.isoformat()


class BackupCreateResponseSchema(BaseModel):
    backup: BackupManifestSchema
    tables: dict[str, int]


class BackupRestoreResponseSchema(BaseModel):
    restored_from: str
    safety_backup: BackupManifestSchema
    tables: dict[str, int]


class RecoveryStatusSchema(BaseModel):
    blocked_sources_total: int
    blocked_sources: list[SourceReadSchema]
    failed_jobs_total: int
    failed_jobs: list[dict]
    pending_price_alerts_total: int
    last_processed_competitor_price_id: int
    latest_backup: BackupManifestSchema | None = None


class RecoveryActionResponseSchema(BaseModel):
    action: str
    details: dict


class AuthenticatedAdminSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access: AdminUserReadSchema
