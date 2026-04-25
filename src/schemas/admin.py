from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


AdminRoleLiteral = Literal["operator", "super_admin"]


class AdminUserLoginSchema(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=6, max_length=255)


class AdminUserReadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str | None
    role: AdminRoleLiteral
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminUserCreateSchema(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=6, max_length=255)
    role: AdminRoleLiteral = "operator"
    is_active: bool = True


class AdminUserUpdateSchema(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=6, max_length=255)
    role: AdminRoleLiteral | None = None
    is_active: bool | None = None


class AuthTokenResponseSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AdminUserReadSchema


class SourcePayloadSchema(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    base_url: str = Field(min_length=4, max_length=512)
    enabled: bool = True
    requests_per_minute: int = Field(default=20, ge=1, le=1000)
    failure_threshold: int = Field(default=3, ge=1, le=100)
    block_duration_minutes: int = Field(default=30, ge=1, le=10080)
    notes: str | None = Field(default=None, max_length=4000)


class SourceReadSchema(BaseModel):
    id: int
    name: str
    base_url: str
    enabled: bool
    requests_per_minute: int
    failure_threshold: int
    block_duration_minutes: int
    failure_streak: int
    blocked_until: datetime | None
    last_error: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class MonitoringJobPayloadSchema(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    enabled: bool = True
    schedule_minutes: int = Field(default=30, ge=1, le=10080)
    alert_ids: list[int] = Field(
        default_factory=list,
        validation_alias=AliasChoices("alert_ids", "source_ids"),
    )
    limit_products_per_run: int | None = Field(default=None, ge=1, le=10000)
    retry_attempts: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=5, ge=0, le=600)
    request_delay_ms: int = Field(default=300, ge=0, le=60000)


class MonitoringJobUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    schedule_minutes: int | None = Field(default=None, ge=1, le=10080)
    alert_ids: list[int] | None = Field(
        default=None,
        validation_alias=AliasChoices("alert_ids", "source_ids"),
    )
    limit_products_per_run: int | None = Field(default=None, ge=1, le=10000)
    retry_attempts: int | None = Field(default=None, ge=0, le=10)
    retry_backoff_seconds: int | None = Field(default=None, ge=0, le=600)
    request_delay_ms: int | None = Field(default=None, ge=0, le=60000)


class MonitoringJobReadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    enabled: bool
    schedule_minutes: int
    alert_ids: list[int]
    limit_products_per_run: int | None
    retry_attempts: int
    retry_backoff_seconds: int
    request_delay_ms: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_status: str
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class AdminAlertPayloadSchema(BaseModel):
    product_id: int | None = None
    competitor_id: int | None = None
    type: Literal["zscore", "pct_change", "below_threshold"]
    params: dict[str, Any] = Field(default_factory=dict)
    recipients: list[Any] = Field(default_factory=list)
    enabled: bool = True


class AdminAlertReadSchema(BaseModel):
    id: int
    product_id: int | None
    competitor_id: int | None
    type: str
    params: dict[str, Any]
    recipients: list[Any]
    enabled: bool
    created_at: datetime | str


class PlatformSettingPayloadSchema(BaseModel):
    key: str = Field(min_length=2, max_length=128)
    value: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=4000)


class PlatformSettingReadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    value: dict[str, Any]
    description: str | None
    created_at: datetime
    updated_at: datetime


class AuditLogReadSchema(BaseModel):
    id: int
    actor_user_id: int | None
    actor_username: str | None = None
    action: str
    entity_type: str
    entity_id: str | None
    level: str
    message: str
    details: dict[str, Any]
    created_at: datetime


class DashboardSummarySchema(BaseModel):
    sources_total: int
    jobs_total: int
    jobs_enabled: int
    alerts_total: int
    users_total: int
    logs_total: int
    blocked_sources_total: int
    last_job_runs: list[AuditLogReadSchema]
