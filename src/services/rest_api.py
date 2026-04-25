from __future__ import annotations

import json
import math
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, String, cast, delete, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect as sa_inspect

from models.admin import AdminUser, AuditLog, MonitoringJob, PlatformSetting, SourcePolicy
from models.prices import Alert, CompetitorPrice, Notification
from models.products import Competitor
from schemas.admin import AdminAlertPayloadSchema, SourcePayloadSchema
from schemas.rest import (
    BackupCreateResponseSchema,
    BackupFilterSchema,
    BackupManifestSchema,
    BackupRestoreResponseSchema,
    CurrentPriceFilterSchema,
    CurrentPriceReadSchema,
    PageMetaSchema,
    PaginatedResponseSchema,
    PriceHistoryFilterSchema,
    PriceHistoryReadSchema,
    RecoveryActionResponseSchema,
    RecoveryStatusSchema,
    RuleFilterSchema,
    RuleReadSchema,
    ServiceSettingFilterSchema,
    ServiceSettingReadSchema,
    SourceConfigReadSchema,
    SourceFilterSchema,
)
from services.admin import AdminControlService, ensure_platform_settings, ensure_source_policies, serialize_alert, serialize_setting, serialize_source
from services.admin_auth import add_audit_log
from settings.config import get_settings
from trigger.competitor_price_trigger import ALERT_PROCESSOR_STATE_KEY, process_pending_price_alerts


settings = get_settings()
logger = logging.getLogger(__name__)


BACKUP_TABLE_MODELS: tuple[tuple[str, type], ...] = (
    ("admin_users", AdminUser),
    ("competitors", Competitor),
    ("source_policies", SourcePolicy),
    ("monitoring_jobs", MonitoringJob),
    ("platform_settings", PlatformSetting),
    ("alerts", Alert),
    ("competitor_prices", CompetitorPrice),
    ("notifications", Notification),
    ("audit_logs", AuditLog),
)

RESTORE_DELETE_ORDER: tuple[type, ...] = (
    Notification,
    CompetitorPrice,
    Alert,
    MonitoringJob,
    SourcePolicy,
    PlatformSetting,
    AuditLog,
    Competitor,
    AdminUser,
)

RESTORE_INSERT_ORDER: tuple[type, ...] = (
    AdminUser,
    Competitor,
    SourcePolicy,
    MonitoringJob,
    PlatformSetting,
    Alert,
    CompetitorPrice,
    Notification,
    AuditLog,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_backup_dir() -> Path:
    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def resolve_backup_path(backup_name: str) -> Path:
    normalized_name = Path(backup_name).name
    if normalized_name != backup_name or not normalized_name.endswith(".json"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup name")
    return ensure_backup_dir() / normalized_name


def _normalize_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _build_page_meta(*, page: int, page_size: int, total: int) -> PageMetaSchema:
    total_pages = math.ceil(total / page_size) if total else 0
    return PageMetaSchema(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total_pages > 0,
    )


def _serialize_model_instance(instance) -> dict:
    result: dict = {}
    mapper = sa_inspect(type(instance))
    for attr in mapper.column_attrs:
        column = attr.columns[0]
        value = getattr(instance, attr.key)
        if isinstance(value, Enum):
            result[attr.key] = value.value
        elif isinstance(value, datetime):
            result[attr.key] = value.isoformat()
        else:
            result[attr.key] = value
    return result


def _deserialize_row(model: type, row: dict) -> dict:
    result: dict = {}
    mapper = sa_inspect(model)
    for attr in mapper.column_attrs:
        column = attr.columns[0]
        if attr.key not in row:
            continue
        value = row[attr.key]
        if value is None:
            result[attr.key] = None
            continue
        if isinstance(column.type, SQLAlchemyEnum) and getattr(column.type, "enum_class", None):
            enum_class = column.type.enum_class
            result[attr.key] = value if isinstance(value, enum_class) else enum_class(value)
            continue
        if isinstance(column.type, DateTime) and isinstance(value, str):
            result[attr.key] = datetime.fromisoformat(value)
            continue
        result[attr.key] = value
    return result


async def _reset_primary_key_sequence(session: AsyncSession, model: type) -> None:
    table = model.__table__
    if "id" not in table.c:
        return

    schema = table.schema
    table_name = table.name
    quoted_table = f'"{schema}"."{table_name}"' if schema else f'"{table_name}"'
    serial_name = f"{schema}.{table_name}" if schema else table_name
    await session.execute(
        text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{serial_name}', 'id'),
                COALESCE((SELECT MAX(id) FROM {quoted_table}), 1),
                COALESCE((SELECT MAX(id) IS NOT NULL FROM {quoted_table}), false)
            )
            """
        )
    )


async def _load_alert_processor_state(session: AsyncSession) -> int:
    setting = await session.scalar(select(PlatformSetting).where(PlatformSetting.key == ALERT_PROCESSOR_STATE_KEY))
    if setting is None:
        return 0
    value = setting.value or {}
    return int(value.get("last_processed_competitor_price_id", 0) or 0)


class RestAPIService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.admin_service = AdminControlService(session)

    async def list_current_prices(
        self,
        filters: CurrentPriceFilterSchema,
    ) -> PaginatedResponseSchema[CurrentPriceReadSchema]:
        ranked_prices = (
            select(
                CompetitorPrice.id.label("price_id"),
                CompetitorPrice.product_id.label("product_id"),
                CompetitorPrice.competitor_id.label("competitor_id"),
                Competitor.name.label("competitor_name"),
                CompetitorPrice.price.label("price"),
                CompetitorPrice.currency.label("currency"),
                CompetitorPrice.scraped_at.label("scraped_at"),
                func.lag(CompetitorPrice.price).over(
                    partition_by=(CompetitorPrice.product_id, CompetitorPrice.competitor_id),
                    order_by=(CompetitorPrice.scraped_at, CompetitorPrice.id),
                ).label("previous_price"),
                func.row_number().over(
                    partition_by=(CompetitorPrice.product_id, CompetitorPrice.competitor_id),
                    order_by=(CompetitorPrice.scraped_at.desc(), CompetitorPrice.id.desc()),
                ).label("row_num"),
            )
            .join(Competitor, Competitor.id == CompetitorPrice.competitor_id)
            .subquery()
        )

        statement = select(ranked_prices).where(ranked_prices.c.row_num == 1)
        query = _normalize_query(filters.q)
        if filters.product_id is not None:
            statement = statement.where(ranked_prices.c.product_id == filters.product_id)
        if filters.competitor_id is not None:
            statement = statement.where(ranked_prices.c.competitor_id == filters.competitor_id)
        if filters.min_price is not None:
            statement = statement.where(ranked_prices.c.price >= filters.min_price)
        if filters.max_price is not None:
            statement = statement.where(ranked_prices.c.price <= filters.max_price)
        if filters.scraped_from is not None:
            statement = statement.where(ranked_prices.c.scraped_at >= filters.scraped_from)
        if filters.scraped_to is not None:
            statement = statement.where(ranked_prices.c.scraped_at <= filters.scraped_to)
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    cast(ranked_prices.c.product_id, String).ilike(pattern),
                    cast(ranked_prices.c.competitor_id, String).ilike(pattern),
                    ranked_prices.c.competitor_name.ilike(pattern),
                    cast(ranked_prices.c.price, String).ilike(pattern),
                )
            )

        total = await self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        offset = (filters.page - 1) * filters.page_size
        rows = (
            await self.session.execute(
                statement
                .order_by(ranked_prices.c.scraped_at.desc(), ranked_prices.c.price_id.desc())
                .offset(offset)
                .limit(filters.page_size)
            )
        ).mappings().all()

        items = []
        for row in rows:
            previous_price = float(row["previous_price"]) if row["previous_price"] is not None else None
            current_price = float(row["price"])
            change_abs = None if previous_price is None else round(current_price - previous_price, 2)
            change_pct = None
            if previous_price not in (None, 0):
                change_pct = round(((current_price - previous_price) / previous_price) * 100, 2)
            items.append(
                CurrentPriceReadSchema(
                    price_id=row["price_id"],
                    product_id=row["product_id"],
                    competitor_id=row["competitor_id"],
                    competitor_name=row["competitor_name"],
                    price=current_price,
                    currency=row["currency"],
                    scraped_at=row["scraped_at"],
                    previous_price=previous_price,
                    change_abs=change_abs,
                    change_pct=change_pct,
                )
            )

        return PaginatedResponseSchema(items=items, meta=_build_page_meta(page=filters.page, page_size=filters.page_size, total=total))

    async def list_price_history(
        self,
        filters: PriceHistoryFilterSchema,
    ) -> PaginatedResponseSchema[PriceHistoryReadSchema]:
        statement = (
            select(CompetitorPrice, Competitor.name.label("competitor_name"))
            .join(Competitor, Competitor.id == CompetitorPrice.competitor_id)
        )
        query = _normalize_query(filters.q)

        if filters.product_id is not None:
            statement = statement.where(CompetitorPrice.product_id == filters.product_id)
        if filters.competitor_id is not None:
            statement = statement.where(CompetitorPrice.competitor_id == filters.competitor_id)
        if filters.min_price is not None:
            statement = statement.where(CompetitorPrice.price >= filters.min_price)
        if filters.max_price is not None:
            statement = statement.where(CompetitorPrice.price <= filters.max_price)
        if filters.scraped_from is not None:
            statement = statement.where(CompetitorPrice.scraped_at >= filters.scraped_from)
        if filters.scraped_to is not None:
            statement = statement.where(CompetitorPrice.scraped_at <= filters.scraped_to)
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    cast(CompetitorPrice.id, String).ilike(pattern),
                    cast(CompetitorPrice.product_id, String).ilike(pattern),
                    cast(CompetitorPrice.competitor_id, String).ilike(pattern),
                    Competitor.name.ilike(pattern),
                    cast(CompetitorPrice.price, String).ilike(pattern),
                )
            )

        total = await self.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
        offset = (filters.page - 1) * filters.page_size
        rows = (
            await self.session.execute(
                statement
                .order_by(CompetitorPrice.scraped_at.desc(), CompetitorPrice.id.desc())
                .offset(offset)
                .limit(filters.page_size)
            )
        ).all()
        items = [
            PriceHistoryReadSchema(
                id=price.id,
                product_id=price.product_id,
                competitor_id=price.competitor_id,
                competitor_name=competitor_name,
                price=float(price.price),
                currency=price.currency,
                scraped_at=price.scraped_at,
            )
            for price, competitor_name in rows
        ]
        return PaginatedResponseSchema(items=items, meta=_build_page_meta(page=filters.page, page_size=filters.page_size, total=total))

    async def list_source_configs(
        self,
        filters: SourceFilterSchema,
    ) -> PaginatedResponseSchema[SourceConfigReadSchema]:
        await ensure_source_policies(self.session)
        statement = (
            select(Competitor, SourcePolicy)
            .join(SourcePolicy, SourcePolicy.competitor_id == Competitor.id)
        )
        query = _normalize_query(filters.q)
        if filters.enabled is not None:
            statement = statement.where(SourcePolicy.enabled.is_(filters.enabled))
        if filters.blocked is True:
            statement = statement.where(SourcePolicy.blocked_until > utcnow())
        elif filters.blocked is False:
            statement = statement.where(or_(SourcePolicy.blocked_until.is_(None), SourcePolicy.blocked_until <= utcnow()))
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    cast(Competitor.id, String).ilike(pattern),
                    Competitor.name.ilike(pattern),
                    Competitor.base_url.ilike(pattern),
                    SourcePolicy.notes.ilike(pattern),
                    SourcePolicy.last_error.ilike(pattern),
                )
            )

        total = await self.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
        offset = (filters.page - 1) * filters.page_size
        rows = (
            await self.session.execute(
                statement
                .order_by(Competitor.name.asc())
                .offset(offset)
                .limit(filters.page_size)
            )
        ).all()
        items = [SourceConfigReadSchema.model_validate(serialize_source(competitor, policy)) for competitor, policy in rows]
        return PaginatedResponseSchema(items=items, meta=_build_page_meta(page=filters.page, page_size=filters.page_size, total=total))

    async def get_source_config(self, source_id: int) -> SourceConfigReadSchema:
        await ensure_source_policies(self.session)
        row = (
            await self.session.execute(
                select(Competitor, SourcePolicy)
                .join(SourcePolicy, SourcePolicy.competitor_id == Competitor.id)
                .where(Competitor.id == source_id)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
        competitor, policy = row
        return SourceConfigReadSchema.model_validate(serialize_source(competitor, policy))

    async def list_rules(
        self,
        filters: RuleFilterSchema,
    ) -> PaginatedResponseSchema[RuleReadSchema]:
        statement = select(Alert)
        query = _normalize_query(filters.q)
        if filters.product_id is not None:
            statement = statement.where(Alert.product_id == filters.product_id)
        if filters.competitor_id is not None:
            statement = statement.where(Alert.competitor_id == filters.competitor_id)
        if filters.enabled is not None:
            statement = statement.where(Alert.enabled.is_(filters.enabled))
        if filters.type is not None:
            statement = statement.where(Alert.type == filters.type)
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    cast(Alert.id, String).ilike(pattern),
                    cast(Alert.product_id, String).ilike(pattern),
                    cast(Alert.competitor_id, String).ilike(pattern),
                    cast(Alert.type, String).ilike(pattern),
                )
            )

        total = await self.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
        offset = (filters.page - 1) * filters.page_size
        rows = list(
            (
                await self.session.scalars(
                    statement.order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(filters.page_size)
                )
            ).all()
        )
        items = [RuleReadSchema.model_validate(serialize_alert(alert)) for alert in rows]
        return PaginatedResponseSchema(items=items, meta=_build_page_meta(page=filters.page, page_size=filters.page_size, total=total))

    async def get_rule(self, rule_id: int) -> RuleReadSchema:
        alert = await self.session.get(Alert, rule_id)
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
        return RuleReadSchema.model_validate(serialize_alert(alert))

    async def create_source_config(self, payload: SourcePayloadSchema, actor: AdminUser) -> SourceConfigReadSchema:
        return SourceConfigReadSchema.model_validate(await self.admin_service.create_source(payload, actor))

    async def update_source_config(self, source_id: int, payload: SourcePayloadSchema, actor: AdminUser) -> SourceConfigReadSchema:
        return SourceConfigReadSchema.model_validate(await self.admin_service.update_source(source_id, payload, actor))

    async def delete_source_config(self, source_id: int, actor: AdminUser) -> dict:
        return await self.admin_service.delete_source(source_id, actor)

    async def create_rule(self, payload: AdminAlertPayloadSchema, actor: AdminUser) -> RuleReadSchema:
        return RuleReadSchema.model_validate(await self.admin_service.create_alert(payload, actor))

    async def update_rule(self, rule_id: int, payload: AdminAlertPayloadSchema, actor: AdminUser) -> RuleReadSchema:
        return RuleReadSchema.model_validate(await self.admin_service.update_alert(rule_id, payload, actor))

    async def delete_rule(self, rule_id: int, actor: AdminUser) -> dict:
        return await self.admin_service.delete_alert(rule_id, actor)

    async def list_service_settings(
        self,
        filters: ServiceSettingFilterSchema,
    ) -> PaginatedResponseSchema[ServiceSettingReadSchema]:
        await ensure_platform_settings(self.session)
        statement = select(PlatformSetting)
        query = _normalize_query(filters.q)
        if filters.key:
            statement = statement.where(PlatformSetting.key == filters.key)
        if query:
            pattern = f"%{query}%"
            statement = statement.where(
                or_(
                    PlatformSetting.key.ilike(pattern),
                    PlatformSetting.description.ilike(pattern),
                    cast(PlatformSetting.value, String).ilike(pattern),
                )
            )

        total = await self.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
        offset = (filters.page - 1) * filters.page_size
        rows = list(
            (
                await self.session.scalars(
                    statement.order_by(PlatformSetting.key.asc()).offset(offset).limit(filters.page_size)
                )
            ).all()
        )
        items = [ServiceSettingReadSchema.model_validate(serialize_setting(setting)) for setting in rows]
        return PaginatedResponseSchema(items=items, meta=_build_page_meta(page=filters.page, page_size=filters.page_size, total=total))

    async def list_backups(
        self,
        filters: BackupFilterSchema,
    ) -> PaginatedResponseSchema[BackupManifestSchema]:
        backup_dir = ensure_backup_dir()
        query = _normalize_query(filters.q)
        backups = []
        for path in sorted(backup_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            if query and query.lower() not in path.name.lower():
                continue
            stat = path.stat()
            backups.append(
                BackupManifestSchema(
                    backup_name=path.name,
                    created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    size_bytes=stat.st_size,
                )
            )

        total = len(backups)
        offset = (filters.page - 1) * filters.page_size
        items = backups[offset : offset + filters.page_size]
        return PaginatedResponseSchema(items=items, meta=_build_page_meta(page=filters.page, page_size=filters.page_size, total=total))

    async def create_backup(self, actor: AdminUser | None = None) -> BackupCreateResponseSchema:
        backup_dir = ensure_backup_dir()
        payload = {
            "meta": {
                "created_at": utcnow().isoformat(),
                "db_name": settings.DB_NAME,
                "app": "PriceMonitor",
            },
            "tables": {},
        }
        table_counts: dict[str, int] = {}
        for table_name, model in BACKUP_TABLE_MODELS:
            rows = list((await self.session.scalars(select(model).order_by(model.id.asc()))).all())
            payload["tables"][table_name] = [_serialize_model_instance(row) for row in rows]
            table_counts[table_name] = len(rows)

        timestamp = utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"price-monitor-backup-{timestamp}.json"
        backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = BackupManifestSchema(
            backup_name=backup_path.name,
            created_at=datetime.fromtimestamp(backup_path.stat().st_mtime, tz=timezone.utc),
            size_bytes=backup_path.stat().st_size,
        )

        add_audit_log(
            self.session,
            actor_user_id=actor.id if actor else None,
            action="backup_created",
            entity_type="backup",
            entity_id=backup_path.name,
            message=f"Backup {backup_path.name} created",
            details={"tables": table_counts},
        )
        await self.session.commit()
        return BackupCreateResponseSchema(backup=manifest, tables=table_counts)

    async def delete_backup(self, backup_name: str, actor: AdminUser) -> dict:
        backup_path = resolve_backup_path(backup_name)
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")

        backup_path.unlink()
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="backup_deleted",
            entity_type="backup",
            entity_id=backup_name,
            message=f"Backup {backup_name} deleted",
        )
        await self.session.commit()
        return {"deleted_backup_name": backup_name}

    async def restore_backup(self, backup_name: str, actor: AdminUser) -> BackupRestoreResponseSchema:
        backup_path = resolve_backup_path(backup_name)
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")

        safety_backup = await self.create_backup(actor=None)
        payload = json.loads(backup_path.read_text(encoding="utf-8"))
        tables_payload = payload.get("tables", {})
        restored_counts: dict[str, int] = {}

        for model in RESTORE_DELETE_ORDER:
            await self.session.execute(delete(model))

        for model in RESTORE_INSERT_ORDER:
            table_name = model.__table__.name
            raw_rows = tables_payload.get(table_name, [])
            prepared_rows = [_deserialize_row(model, row) for row in raw_rows]
            if prepared_rows:
                await self.session.execute(insert(model), prepared_rows)
            restored_counts[table_name] = len(prepared_rows)
            await _reset_primary_key_sequence(self.session, model)

        add_audit_log(
            self.session,
            actor_user_id=None,
            action="backup_restored",
            entity_type="backup",
            entity_id=backup_name,
            level="warning",
            message=f"Backup {backup_name} restored by {actor.username}",
            details={"restored_tables": restored_counts, "safety_backup": safety_backup.backup.backup_name},
        )
        await self.session.commit()
        return BackupRestoreResponseSchema(
            restored_from=backup_name,
            safety_backup=safety_backup.backup,
            tables=restored_counts,
        )

    async def get_recovery_status(self) -> RecoveryStatusSchema:
        await ensure_source_policies(self.session)
        await ensure_platform_settings(self.session)

        blocked_rows = (
            await self.session.execute(
                select(Competitor, SourcePolicy)
                .join(SourcePolicy, SourcePolicy.competitor_id == Competitor.id)
                .where(SourcePolicy.blocked_until > utcnow())
                .order_by(SourcePolicy.blocked_until.asc())
            )
        ).all()
        blocked_sources = [serialize_source(competitor, policy) for competitor, policy in blocked_rows]

        failed_jobs = list(
            (
                await self.session.execute(
                    select(MonitoringJob)
                    .where(MonitoringJob.last_status.in_(("failed", "partial_error")))
                    .order_by(MonitoringJob.updated_at.desc(), MonitoringJob.id.desc())
                    .limit(20)
                )
            ).scalars().all()
        )

        last_processed_price_id = await _load_alert_processor_state(self.session)
        pending_price_alerts_total = await self.session.scalar(
            select(func.count(CompetitorPrice.id)).where(CompetitorPrice.id > last_processed_price_id)
        ) or 0

        latest_backup_page = await self.list_backups(BackupFilterSchema(page=1, page_size=1))
        latest_backup = latest_backup_page.items[0] if latest_backup_page.items else None

        return RecoveryStatusSchema(
            blocked_sources_total=len(blocked_sources),
            blocked_sources=blocked_sources,
            failed_jobs_total=len(failed_jobs),
            failed_jobs=[
                {
                    "id": job.id,
                    "name": job.name,
                    "last_status": job.last_status,
                    "last_error": job.last_error,
                    "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
                    "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
                }
                for job in failed_jobs
            ],
            pending_price_alerts_total=int(pending_price_alerts_total),
            last_processed_competitor_price_id=last_processed_price_id,
            latest_backup=latest_backup,
        )

    async def unblock_sources(self, actor: AdminUser, *, force: bool) -> RecoveryActionResponseSchema:
        now = utcnow()
        statement = select(SourcePolicy).where(SourcePolicy.blocked_until.is_not(None))
        if not force:
            statement = statement.where(SourcePolicy.blocked_until <= now)
        policies = list((await self.session.scalars(statement)).all())
        unblocked_ids = []
        for policy in policies:
            policy.blocked_until = None
            policy.failure_streak = 0
            policy.last_error = None
            policy.updated_by_id = actor.id
            unblocked_ids.append(policy.competitor_id)

        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="sources_unblocked",
            entity_type="recovery",
            message="Blocked sources were released",
            details={"force": force, "competitor_ids": unblocked_ids},
        )
        await self.session.commit()
        return RecoveryActionResponseSchema(
            action="unblock_sources",
            details={"force": force, "unblocked_source_ids": unblocked_ids, "count": len(unblocked_ids)},
        )

    async def replay_pending_price_alerts(self, actor: AdminUser, *, limit: int) -> RecoveryActionResponseSchema:
        summary = await process_pending_price_alerts(limit=limit)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="pending_alerts_replayed",
            entity_type="recovery",
            message="Pending competitor price alerts replayed",
            details=summary,
        )
        await self.session.commit()
        return RecoveryActionResponseSchema(action="replay_pending_price_alerts", details=summary)


async def run_startup_recovery() -> None:
    ensure_backup_dir()
    try:
        summary = await process_pending_price_alerts(limit=settings.STARTUP_RECOVERY_PENDING_ALERT_LIMIT)
        if summary["processed_price_ids"] or summary["errors"]:
            logger.info("Startup recovery processed pending price alerts: %s", summary)
    except Exception:  # noqa: BLE001
        logger.exception("Startup recovery failed while replaying pending price alerts")
