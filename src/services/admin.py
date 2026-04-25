import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, outerjoin, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from db.db import async_session
from models.admin import AdminRole, AdminUser, AuditLog, MonitoringJob, PlatformSetting, SourcePolicy
from models.prices import Alert, AlertType
from models.products import Competitor
from schemas.admin import (
    AdminAlertPayloadSchema,
    AdminAlertReadSchema,
    AdminUserCreateSchema,
    AdminUserReadSchema,
    AdminUserUpdateSchema,
    AuditLogReadSchema,
    DashboardSummarySchema,
    MonitoringJobPayloadSchema,
    MonitoringJobReadSchema,
    MonitoringJobUpdateSchema,
    PlatformSettingPayloadSchema,
    PlatformSettingReadSchema,
    SourcePayloadSchema,
    SourceReadSchema,
)
from services.admin_auth import add_audit_log, hash_password, serialize_admin_user
from services.competitor_parsing import _load_parsing_scope, _save_price_with_retry, get_parser_for_competitor
from trigger.competitor_price_trigger import process_pending_price_alerts


DEFAULT_PLATFORM_SETTINGS = (
    {
        "key": "platform_name",
        "value": {"value": "Price Monitor Control Center"},
        "description": "Название административной платформы",
    },
    {
        "key": "support_contacts",
        "value": {"email": "", "telegram": ""},
        "description": "Контакты поддержки для операторов",
    },
    {
        "key": "alert_processor_state",
        "value": {"last_processed_competitor_price_id": 0},
        "description": "Служебное состояние фоновой обработки цен для alert-триггеров",
    },
)


@dataclass
class JobSnapshot:
    id: int
    name: str
    enabled: bool
    schedule_minutes: int
    alert_ids: list[int]
    limit_products_per_run: int | None
    retry_attempts: int
    retry_backoff_seconds: int
    request_delay_ms: int


@dataclass
class SourcePolicySnapshot:
    competitor_id: int
    competitor_name: str
    enabled: bool
    requests_per_minute: int
    failure_threshold: int
    block_duration_minutes: int
    failure_streak: int
    blocked_until: datetime | None
    last_error: str | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize_source(competitor: Competitor, policy: SourcePolicy) -> SourceReadSchema:
    return SourceReadSchema(
        id=competitor.id,
        name=competitor.name,
        base_url=competitor.base_url,
        enabled=policy.enabled,
        requests_per_minute=policy.requests_per_minute,
        failure_threshold=policy.failure_threshold,
        block_duration_minutes=policy.block_duration_minutes,
        failure_streak=policy.failure_streak,
        blocked_until=policy.blocked_until,
        last_error=policy.last_error,
        notes=policy.notes,
        created_at=competitor.created_at,
        updated_at=policy.updated_at,
    )


def serialize_job(job: MonitoringJob, *, alert_ids: list[int] | None = None) -> MonitoringJobReadSchema:
    return MonitoringJobReadSchema(
        id=job.id,
        name=job.name,
        description=job.description,
        enabled=job.enabled,
        schedule_minutes=job.schedule_minutes,
        alert_ids=alert_ids if alert_ids is not None else (job.alert_ids or []),
        limit_products_per_run=job.limit_products_per_run,
        retry_attempts=job.retry_attempts,
        retry_backoff_seconds=job.retry_backoff_seconds,
        request_delay_ms=job.request_delay_ms,
        last_run_at=job.last_run_at,
        next_run_at=job.next_run_at,
        last_status=job.last_status,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def serialize_setting(setting: PlatformSetting) -> PlatformSettingReadSchema:
    return PlatformSettingReadSchema.model_validate(setting)


def serialize_alert(alert: Alert) -> AdminAlertReadSchema:
    return AdminAlertReadSchema(
        id=alert.id,
        product_id=alert.product_id,
        competitor_id=alert.competitor_id,
        type=alert.type.value if isinstance(alert.type, AlertType) else alert.type,
        params=alert.params,
        recipients=alert.recipients,
        enabled=alert.enabled,
        created_at=alert.created_at,
    )


def _build_products_scope_from_alerts(alerts: list[Alert]) -> dict[int, set[int] | None]:
    products_scope: dict[int, set[int] | None] = {}

    for alert in alerts:
        if alert.product_id is None:
            continue

        current_scope = products_scope.get(alert.product_id)
        if current_scope is None and alert.product_id in products_scope:
            continue

        if alert.competitor_id is None:
            products_scope[alert.product_id] = None
            continue

        if current_scope is None:
            products_scope[alert.product_id] = {alert.competitor_id}
        else:
            current_scope.add(alert.competitor_id)

    return products_scope


async def _validate_job_alert_ids(session: AsyncSession, alert_ids: list[int]) -> None:
    if not alert_ids:
        return

    existing_ids = set(
        (
            await session.scalars(
                select(Alert.id).where(Alert.id.in_(alert_ids))
            )
        ).all()
    )
    missing_ids = sorted(set(alert_ids) - existing_ids)
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Alerts not found: {', '.join(str(alert_id) for alert_id in missing_ids)}",
        )


def _resolve_job_alerts(job: MonitoringJob, enabled_alerts: list[Alert]) -> list[Alert]:
    selectable_alerts = [alert for alert in enabled_alerts if alert.product_id is not None]
    if not job.alert_ids:
        return selectable_alerts

    selected_ids = set(job.alert_ids)
    alerts_by_id = [alert for alert in selectable_alerts if alert.id in selected_ids]
    if alerts_by_id:
        return alerts_by_id

    # Compatibility for jobs saved before the UI switched from sources to alerts.
    alerts_by_competitor = [
        alert
        for alert in selectable_alerts
        if alert.competitor_id is not None and alert.competitor_id in selected_ids
    ]
    return alerts_by_competitor


async def ensure_source_policies(session: AsyncSession) -> None:
    competitors = list((await session.scalars(select(Competitor))).all())
    policy_competitor_ids = set((await session.scalars(select(SourcePolicy.competitor_id))).all())
    created = False

    for competitor in competitors:
        if competitor.id in policy_competitor_ids:
            continue
        session.add(SourcePolicy(competitor_id=competitor.id))
        created = True

    if created:
        await session.commit()


async def ensure_platform_settings(session: AsyncSession) -> None:
    existing_keys = set((await session.scalars(select(PlatformSetting.key))).all())
    created = False

    for item in DEFAULT_PLATFORM_SETTINGS:
        if item["key"] in existing_keys:
            continue
        session.add(PlatformSetting(**item))
        created = True

    if created:
        await session.commit()


class AdminControlService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_dashboard(self) -> DashboardSummarySchema:
        await ensure_source_policies(self.session)
        counts = {
            "sources_total": await self.session.scalar(select(func.count(Competitor.id))) or 0,
            "jobs_total": await self.session.scalar(select(func.count(MonitoringJob.id))) or 0,
            "jobs_enabled": await self.session.scalar(
                select(func.count(MonitoringJob.id)).where(MonitoringJob.enabled.is_(True))
            ) or 0,
            "alerts_total": await self.session.scalar(select(func.count(Alert.id))) or 0,
            "users_total": await self.session.scalar(select(func.count(AdminUser.id))) or 0,
            "logs_total": await self.session.scalar(select(func.count(AuditLog.id))) or 0,
            "blocked_sources_total": await self.session.scalar(
                select(func.count(SourcePolicy.id)).where(SourcePolicy.blocked_until > utcnow())
            ) or 0,
        }
        logs = await self.list_logs(limit=5)
        return DashboardSummarySchema(last_job_runs=logs, **counts)

    async def list_sources(self) -> list[SourceReadSchema]:
        await ensure_source_policies(self.session)
        rows = await self.session.execute(
            select(Competitor, SourcePolicy)
            .join(SourcePolicy, SourcePolicy.competitor_id == Competitor.id)
            .order_by(Competitor.name.asc())
        )
        return [serialize_source(competitor, policy) for competitor, policy in rows.all()]

    async def create_source(self, payload: SourcePayloadSchema, actor: AdminUser) -> SourceReadSchema:
        existing = await self.session.scalar(
            select(Competitor).where(func.lower(Competitor.name) == payload.name.lower())
        )
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source already exists")

        competitor = Competitor(name=payload.name, base_url=payload.base_url)
        self.session.add(competitor)
        await self.session.flush()

        policy = SourcePolicy(
            competitor_id=competitor.id,
            enabled=payload.enabled,
            requests_per_minute=payload.requests_per_minute,
            failure_threshold=payload.failure_threshold,
            block_duration_minutes=payload.block_duration_minutes,
            notes=payload.notes,
            updated_by_id=actor.id,
        )
        self.session.add(policy)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="source_created",
            entity_type="source",
            entity_id=str(competitor.id),
            message=f"Source {competitor.name} created",
            details=payload.model_dump(),
        )
        await self.session.commit()
        await self.session.refresh(competitor)
        await self.session.refresh(policy)
        return serialize_source(competitor, policy)

    async def update_source(self, source_id: int, payload: SourcePayloadSchema, actor: AdminUser) -> SourceReadSchema:
        await ensure_source_policies(self.session)
        competitor = await self.session.get(Competitor, source_id)
        policy = await self.session.scalar(select(SourcePolicy).where(SourcePolicy.competitor_id == source_id))
        if competitor is None or policy is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

        competitor.name = payload.name
        competitor.base_url = payload.base_url
        policy.enabled = payload.enabled
        policy.requests_per_minute = payload.requests_per_minute
        policy.failure_threshold = payload.failure_threshold
        policy.block_duration_minutes = payload.block_duration_minutes
        policy.notes = payload.notes
        policy.updated_by_id = actor.id

        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="source_updated",
            entity_type="source",
            entity_id=str(source_id),
            message=f"Source {competitor.name} updated",
            details=payload.model_dump(),
        )
        await self.session.commit()
        await self.session.refresh(competitor)
        await self.session.refresh(policy)
        return serialize_source(competitor, policy)

    async def delete_source(self, source_id: int, actor: AdminUser) -> dict:
        competitor = await self.session.get(Competitor, source_id)
        if competitor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

        source_name = competitor.name
        await self.session.delete(competitor)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="source_deleted",
            entity_type="source",
            entity_id=str(source_id),
            message=f"Source {source_name} deleted",
        )
        await self.session.commit()
        return {"deleted_id": source_id}

    async def list_jobs(self) -> list[MonitoringJobReadSchema]:
        jobs = list((await self.session.scalars(select(MonitoringJob).order_by(MonitoringJob.name.asc()))).all())
        enabled_alerts = list(
            (
                await self.session.scalars(
                    select(Alert).where(Alert.enabled.is_(True)).order_by(Alert.created_at.desc())
                )
            ).all()
        )
        return [
            serialize_job(
                job,
                alert_ids=[alert.id for alert in _resolve_job_alerts(job, enabled_alerts)],
            )
            for job in jobs
        ]

    async def create_job(self, payload: MonitoringJobPayloadSchema, actor: AdminUser) -> MonitoringJobReadSchema:
        existing = await self.session.scalar(select(MonitoringJob).where(MonitoringJob.name == payload.name))
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job already exists")

        await _validate_job_alert_ids(self.session, payload.alert_ids)
        next_run_at = utcnow() + timedelta(minutes=payload.schedule_minutes) if payload.enabled else None
        job = MonitoringJob(
            **payload.model_dump(),
            next_run_at=next_run_at,
            created_by_id=actor.id,
            updated_by_id=actor.id,
        )
        self.session.add(job)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="job_created",
            entity_type="job",
            message=f"Monitoring job {payload.name} created",
            details=payload.model_dump(),
        )
        await self.session.commit()
        await self.session.refresh(job)
        return serialize_job(job)

    async def update_job(self, job_id: int, payload: MonitoringJobUpdateSchema, actor: AdminUser) -> MonitoringJobReadSchema:
        job = await self.session.get(MonitoringJob, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        update_data = payload.model_dump(exclude_unset=True)
        await _validate_job_alert_ids(
            self.session,
            update_data.get("alert_ids") or [],
        )
        schedule_changed = "schedule_minutes" in update_data or "enabled" in update_data
        for key, value in update_data.items():
            setattr(job, key, value)

        if schedule_changed:
            job.next_run_at = utcnow() + timedelta(minutes=job.schedule_minutes) if job.enabled else None
        job.updated_by_id = actor.id

        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="job_updated",
            entity_type="job",
            entity_id=str(job_id),
            message=f"Monitoring job {job.name} updated",
            details=update_data,
        )
        await self.session.commit()
        await self.session.refresh(job)
        return serialize_job(job)

    async def delete_job(self, job_id: int, actor: AdminUser) -> dict:
        job = await self.session.get(MonitoringJob, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        job_name = job.name
        await self.session.delete(job)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="job_deleted",
            entity_type="job",
            entity_id=str(job_id),
            message=f"Monitoring job {job_name} deleted",
        )
        await self.session.commit()
        return {"deleted_id": job_id}

    async def list_alerts(self) -> list[AdminAlertReadSchema]:
        alerts = list((await self.session.scalars(select(Alert).order_by(Alert.created_at.desc()))).all())
        return [serialize_alert(alert) for alert in alerts]

    async def create_alert(self, payload: AdminAlertPayloadSchema, actor: AdminUser) -> AdminAlertReadSchema:
        alert = Alert(
            product_id=payload.product_id,
            competitor_id=payload.competitor_id,
            type=AlertType(payload.type),
            params=payload.params,
            recipients=payload.recipients,
            enabled=payload.enabled,
        )
        self.session.add(alert)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="alert_created",
            entity_type="alert",
            message="Monitoring alert created",
            details=payload.model_dump(),
        )
        await self.session.commit()
        await self.session.refresh(alert)
        return serialize_alert(alert)

    async def update_alert(self, alert_id: int, payload: AdminAlertPayloadSchema, actor: AdminUser) -> AdminAlertReadSchema:
        alert = await self.session.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        alert.product_id = payload.product_id
        alert.competitor_id = payload.competitor_id
        alert.type = AlertType(payload.type)
        alert.params = payload.params
        alert.recipients = payload.recipients
        alert.enabled = payload.enabled
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="alert_updated",
            entity_type="alert",
            entity_id=str(alert_id),
            message="Monitoring alert updated",
            details=payload.model_dump(),
        )
        await self.session.commit()
        await self.session.refresh(alert)
        return serialize_alert(alert)

    async def delete_alert(self, alert_id: int, actor: AdminUser) -> dict:
        alert = await self.session.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        await self.session.delete(alert)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="alert_deleted",
            entity_type="alert",
            entity_id=str(alert_id),
            message="Monitoring alert deleted",
        )
        await self.session.commit()
        return {"deleted_id": alert_id}

    async def list_users(self) -> list[AdminUserReadSchema]:
        users = list((await self.session.scalars(select(AdminUser).order_by(AdminUser.username.asc()))).all())
        return [serialize_admin_user(user) for user in users]

    async def create_user(self, payload: AdminUserCreateSchema, actor: AdminUser) -> AdminUserReadSchema:
        existing = await self.session.scalar(
            select(AdminUser).where(func.lower(AdminUser.username) == payload.username.lower())
        )
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

        user = AdminUser(
            username=payload.username,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
            role=AdminRole(payload.role),
            is_active=payload.is_active,
        )
        self.session.add(user)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="user_created",
            entity_type="admin_user",
            message=f"Admin user {payload.username} created",
            details={**payload.model_dump(exclude={"password"}), "password": "***"},
        )
        await self.session.commit()
        await self.session.refresh(user)
        return serialize_admin_user(user)

    async def update_user(self, user_id: int, payload: AdminUserUpdateSchema, actor: AdminUser) -> AdminUserReadSchema:
        user = await self.session.get(AdminUser, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        update_data = payload.model_dump(exclude_unset=True)
        if "role" in update_data and update_data["role"] is not None:
            update_data["role"] = AdminRole(update_data["role"])
        if "password" in update_data and update_data["password"]:
            update_data["password_hash"] = hash_password(update_data.pop("password"))

        await self._validate_super_admin_guard(user, update_data)

        for key, value in update_data.items():
            setattr(user, key, value)

        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="user_updated",
            entity_type="admin_user",
            entity_id=str(user_id),
            message=f"Admin user {user.username} updated",
            details={**update_data, "password_hash": "***"} if "password_hash" in update_data else update_data,
        )
        await self.session.commit()
        await self.session.refresh(user)
        return serialize_admin_user(user)

    async def delete_user(self, user_id: int, actor: AdminUser) -> dict:
        user = await self.session.get(AdminUser, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if actor.id == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete yourself")

        await self._validate_super_admin_guard(user, {"is_active": False, "role": AdminRole.operator})
        username = user.username
        await self.session.delete(user)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="user_deleted",
            entity_type="admin_user",
            entity_id=str(user_id),
            message=f"Admin user {username} deleted",
        )
        await self.session.commit()
        return {"deleted_id": user_id}

    async def _validate_super_admin_guard(self, user: AdminUser, update_data: dict) -> None:
        role_after = update_data.get("role", user.role)
        is_active_after = update_data.get("is_active", user.is_active)
        if user.role != AdminRole.super_admin:
            return
        if role_after == AdminRole.super_admin and is_active_after:
            return

        active_super_admins = await self.session.scalar(
            select(func.count(AdminUser.id)).where(
                AdminUser.role == AdminRole.super_admin,
                AdminUser.is_active.is_(True),
            )
        ) or 0
        if active_super_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one active super-admin must remain",
            )

    async def list_settings(self) -> list[PlatformSettingReadSchema]:
        await ensure_platform_settings(self.session)
        settings = list((await self.session.scalars(select(PlatformSetting).order_by(PlatformSetting.key.asc()))).all())
        return [serialize_setting(setting) for setting in settings]

    async def upsert_setting(self, payload: PlatformSettingPayloadSchema, actor: AdminUser) -> PlatformSettingReadSchema:
        setting = await self.session.scalar(select(PlatformSetting).where(PlatformSetting.key == payload.key))
        if setting is None:
            setting = PlatformSetting(
                key=payload.key,
                value=payload.value,
                description=payload.description,
                updated_by_id=actor.id,
            )
            self.session.add(setting)
            action = "setting_created"
            message = f"Platform setting {payload.key} created"
        else:
            setting.value = payload.value
            setting.description = payload.description
            setting.updated_by_id = actor.id
            action = "setting_updated"
            message = f"Platform setting {payload.key} updated"

        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action=action,
            entity_type="platform_setting",
            entity_id=payload.key,
            message=message,
            details=payload.model_dump(),
        )
        await self.session.commit()
        await self.session.refresh(setting)
        return serialize_setting(setting)

    async def delete_setting(self, setting_id: int, actor: AdminUser) -> dict:
        setting = await self.session.get(PlatformSetting, setting_id)
        if setting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Setting not found")

        setting_key = setting.key
        await self.session.delete(setting)
        add_audit_log(
            self.session,
            actor_user_id=actor.id,
            action="setting_deleted",
            entity_type="platform_setting",
            entity_id=str(setting_id),
            message=f"Platform setting {setting_key} deleted",
        )
        await self.session.commit()
        return {"deleted_id": setting_id}

    async def list_logs(self, limit: int = 100) -> list[AuditLogReadSchema]:
        rows = await self.session.execute(
            select(AuditLog, AdminUser.username)
            .select_from(outerjoin(AuditLog, AdminUser, AdminUser.id == AuditLog.actor_user_id))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        result: list[AuditLogReadSchema] = []
        for log, username in rows.all():
            result.append(
                AuditLogReadSchema(
                    id=log.id,
                    actor_user_id=log.actor_user_id,
                    actor_username=username,
                    action=log.action,
                    entity_type=log.entity_type,
                    entity_id=log.entity_id,
                    level=log.level,
                    message=log.message,
                    details=log.details,
                    created_at=log.created_at,
                )
            )
        return result


async def _record_source_failure(competitor_id: int, error_message: str) -> datetime | None:
    async with async_session() as session:
        policy = await session.scalar(select(SourcePolicy).where(SourcePolicy.competitor_id == competitor_id))
        if policy is None:
            return None

        policy.failure_streak += 1
        policy.last_error = error_message[:2000]
        blocked_until = None
        if policy.failure_streak >= policy.failure_threshold:
            blocked_until = utcnow() + timedelta(minutes=policy.block_duration_minutes)
            policy.blocked_until = blocked_until
            policy.failure_streak = 0

        await session.commit()
        return blocked_until


async def _record_source_success(competitor_id: int) -> None:
    async with async_session() as session:
        policy = await session.scalar(select(SourcePolicy).where(SourcePolicy.competitor_id == competitor_id))
        if policy is None:
            return

        if policy.failure_streak or policy.last_error or policy.blocked_until:
            policy.failure_streak = 0
            policy.last_error = None
            if policy.blocked_until and policy.blocked_until <= utcnow():
                policy.blocked_until = None
            await session.commit()


async def _load_job_runtime(job_id: int) -> tuple[JobSnapshot, dict[int, SourcePolicySnapshot], list[Alert], list[Competitor]]:
    async with async_session() as session:
        await ensure_source_policies(session)
        job = await session.get(MonitoringJob, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        competitors = list((await session.scalars(select(Competitor).order_by(Competitor.name.asc()))).all())
        enabled_alerts = list(
            (
                await session.scalars(
                    select(Alert).where(Alert.enabled.is_(True)).order_by(Alert.created_at.desc())
                )
            ).all()
        )
        selected_alerts = _resolve_job_alerts(job, enabled_alerts)

        rows = await session.execute(
            select(SourcePolicy, Competitor)
            .join(Competitor, Competitor.id == SourcePolicy.competitor_id)
            .order_by(Competitor.name.asc())
        )
        policies: dict[int, SourcePolicySnapshot] = {}
        for policy, competitor in rows.all():
            policies[competitor.id] = SourcePolicySnapshot(
                competitor_id=competitor.id,
                competitor_name=competitor.name,
                enabled=policy.enabled,
                requests_per_minute=policy.requests_per_minute,
                failure_threshold=policy.failure_threshold,
                block_duration_minutes=policy.block_duration_minutes,
                failure_streak=policy.failure_streak,
                blocked_until=policy.blocked_until,
                last_error=policy.last_error,
            )

        snapshot = JobSnapshot(
            id=job.id,
            name=job.name,
            enabled=job.enabled,
            schedule_minutes=job.schedule_minutes,
            alert_ids=job.alert_ids or [],
            limit_products_per_run=job.limit_products_per_run,
            retry_attempts=job.retry_attempts,
            retry_backoff_seconds=job.retry_backoff_seconds,
            request_delay_ms=job.request_delay_ms,
        )
        return snapshot, policies, selected_alerts, competitors


async def _wait_for_rate_limit(
    *,
    competitor_id: int,
    policy: SourcePolicySnapshot,
    job: JobSnapshot,
    last_request_ts: dict[int, float],
) -> None:
    minimum_interval_seconds = 60 / max(policy.requests_per_minute, 1)
    minimum_interval_seconds = max(minimum_interval_seconds, job.request_delay_ms / 1000)
    now_monotonic = asyncio.get_running_loop().time()
    previous_started = last_request_ts.get(competitor_id)
    if previous_started is None:
        last_request_ts[competitor_id] = now_monotonic
        return

    elapsed = now_monotonic - previous_started
    if elapsed < minimum_interval_seconds:
        await asyncio.sleep(minimum_interval_seconds - elapsed)
    last_request_ts[competitor_id] = asyncio.get_running_loop().time()


async def _run_parser_with_retry(
    parser,
    product_name: str,
    *,
    retry_attempts: int,
    retry_backoff_seconds: int,
) -> int:
    last_exception = None
    attempts_total = retry_attempts + 1
    for attempt in range(attempts_total):
        try:
            return await parser(product_name)
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            if attempt == attempts_total - 1:
                break
            if retry_backoff_seconds > 0:
                await asyncio.sleep(retry_backoff_seconds)

    raise last_exception


def _resolve_summary_status(summary: dict) -> tuple[str, str | None]:
    if summary["errors"]:
        if summary["prices_saved"] > 0:
            return "partial_error", summary["errors"][0]["error"]
        return "failed", summary["errors"][0]["error"]
    if summary["prices_saved"] > 0:
        return "success", None
    return "idle", None


async def _finalize_job_run(
    *,
    job_id: int,
    actor_user_id: int | None,
    triggered_by: str,
    summary: dict,
) -> None:
    status_value, error_message = _resolve_summary_status(summary)
    async with async_session() as session:
        job = await session.get(MonitoringJob, job_id)
        if job is None:
            return

        now = utcnow()
        job.last_run_at = now
        job.last_status = status_value
        job.last_error = error_message
        job.next_run_at = now + timedelta(minutes=job.schedule_minutes) if job.enabled else None

        add_audit_log(
            session,
            actor_user_id=actor_user_id,
            action="job_run",
            entity_type="job",
            entity_id=str(job_id),
            message=f"Monitoring job {job.name} completed via {triggered_by}",
            level="error" if summary["errors"] else "info",
            details=summary,
        )
        await session.commit()


async def execute_monitoring_job(
    job_id: int,
    *,
    actor_user_id: int | None = None,
    triggered_by: str = "manual",
) -> dict:
    job, source_policies, selected_alerts, competitors = await _load_job_runtime(job_id)
    _, _, _, product_titles, product_statuses = await _load_parsing_scope()
    products_scope = _build_products_scope_from_alerts(selected_alerts)

    selected_product_ids = list(products_scope.keys())
    if job.limit_products_per_run is not None:
        selected_product_ids = selected_product_ids[:job.limit_products_per_run]

    summary = {
        "job_id": job.id,
        "job_name": job.name,
        "message": "Monitoring job executed",
        "products_total": len(selected_product_ids),
        "prices_saved": 0,
        "created_price_ids": [],
        "unsupported_competitors": [],
        "not_found": [],
        "errors": [],
        "skipped_products": [],
        "blocked_sources": [],
        "skipped_sources": [],
    }

    last_request_ts: dict[int, float] = {}

    for product_id in selected_product_ids:
        product_name = product_titles.get(product_id)
        if not product_name:
            summary["skipped_products"].append(
                {
                    "product_id": product_id,
                    "reason": product_statuses.get(product_id, "missing_title"),
                }
            )
            continue

        scoped_competitor_ids = products_scope.get(product_id)
        target_competitors = [
            competitor
            for competitor in competitors
            if competitor.id in source_policies
            and (scoped_competitor_ids is None or competitor.id in scoped_competitor_ids)
        ]

        for competitor in target_competitors:
            parser = get_parser_for_competitor(competitor.name)
            if parser is None:
                summary["unsupported_competitors"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                    }
                )
                continue

            policy = source_policies[competitor.id]
            if not policy.enabled:
                summary["skipped_sources"].append(
                    {
                        "product_id": product_id,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                        "reason": "disabled",
                    }
                )
                continue

            if policy.blocked_until and policy.blocked_until > utcnow():
                summary["blocked_sources"].append(
                    {
                        "product_id": product_id,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                        "blocked_until": policy.blocked_until.isoformat(),
                    }
                )
                continue

            await _wait_for_rate_limit(
                competitor_id=competitor.id,
                policy=policy,
                job=job,
                last_request_ts=last_request_ts,
            )

            try:
                result = await _run_parser_with_retry(
                    parser,
                    product_name,
                    retry_attempts=job.retry_attempts,
                    retry_backoff_seconds=job.retry_backoff_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                blocked_until = await _record_source_failure(competitor.id, str(exc))
                policy.blocked_until = blocked_until
                summary["errors"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                        "error": str(exc),
                    }
                )
                continue

            await _record_source_success(competitor.id)
            policy.blocked_until = None

            if result <= 0:
                summary["not_found"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                    }
                )
                continue

            try:
                price_id = await _save_price_with_retry(
                    product_id=product_id,
                    competitor_id=competitor.id,
                    price=float(result),
                )
            except SQLAlchemyError as exc:
                summary["errors"].append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "competitor_id": competitor.id,
                        "competitor_name": competitor.name,
                        "error": f"db_write_failed: {exc}",
                    }
                )
                continue

            summary["prices_saved"] += 1
            summary["created_price_ids"].append(price_id)

    await _finalize_job_run(
        job_id=job.id,
        actor_user_id=actor_user_id,
        triggered_by=triggered_by,
        summary=summary,
    )
    return summary


async def execute_due_monitoring_jobs() -> dict:
    async with async_session() as session:
        due_job_ids = list(
            (
                await session.scalars(
                    select(MonitoringJob.id).where(
                        MonitoringJob.enabled.is_(True),
                        or_(MonitoringJob.next_run_at.is_(None), MonitoringJob.next_run_at <= utcnow()),
                    )
                )
            ).all()
        )

    results = []
    for job_id in due_job_ids:
        try:
            results.append(await execute_monitoring_job(job_id, triggered_by="scheduler"))
        except Exception as exc:  # noqa: BLE001
            error_summary = {
                "job_id": job_id,
                "message": "Monitoring job failed before completion",
                "products_total": 0,
                "prices_saved": 0,
                "created_price_ids": [],
                "unsupported_competitors": [],
                "not_found": [],
                "errors": [{"error": str(exc)}],
                "skipped_products": [],
                "blocked_sources": [],
                "skipped_sources": [],
            }
            await _finalize_job_run(
                job_id=job_id,
                actor_user_id=None,
                triggered_by="scheduler",
                summary=error_summary,
            )
            results.append(error_summary)

    pending_price_alerts = await process_pending_price_alerts()

    return {
        "jobs_dispatched": len(due_job_ids),
        "results": results,
        "pending_price_alerts": pending_price_alerts,
    }
