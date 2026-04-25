from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from dependencies.admin import get_admin_control_service
from models.admin import AdminRole, AdminUser
from schemas.admin import (
    AdminAlertPayloadSchema,
    AdminUserCreateSchema,
    AdminUserLoginSchema,
    AdminUserReadSchema,
    AdminUserUpdateSchema,
    MonitoringJobPayloadSchema,
    MonitoringJobUpdateSchema,
    PlatformSettingPayloadSchema,
    SourcePayloadSchema,
)
from services.admin import AdminControlService, execute_due_monitoring_jobs, execute_monitoring_job
from services.admin_auth import (
    authenticate_admin,
    get_current_admin,
    require_roles,
    verify_internal_task_request,
)
from trigger.competitor_price_trigger import replay_price_trigger


router = APIRouter(
    prefix="/admin-api",
    tags=["admin"],
    include_in_schema=False,
    responses={404: {"description": "Not found"}},
)


OperatorOrSuperAdmin = Annotated[
    AdminUser,
    Depends(require_roles(AdminRole.operator, AdminRole.super_admin)),
]
SuperAdminOnly = Annotated[AdminUser, Depends(require_roles(AdminRole.super_admin))]


@router.post("/auth/login")
async def admin_login(
    credentials: AdminUserLoginSchema,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await authenticate_admin(service.session, credentials)


@router.get("/auth/me")
async def admin_me(current_user: Annotated[AdminUser, Depends(get_current_admin)]):
    return AdminUserReadSchema(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        role=current_user.role.value,
        is_active=current_user.is_active,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.post("/auth/logout")
async def admin_logout(current_user: Annotated[AdminUser, Depends(get_current_admin)]):
    return {"message": f"User {current_user.username} logged out"}


@router.get("/dashboard")
async def get_dashboard(
    _: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.get_dashboard()


@router.get("/sources")
async def get_sources(
    _: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.list_sources()


@router.post("/sources")
async def create_source(
    payload: SourcePayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.create_source(payload, current_user)


@router.put("/sources/{source_id}")
async def update_source(
    source_id: int,
    payload: SourcePayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.update_source(source_id, payload, current_user)


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.delete_source(source_id, current_user)


@router.get("/jobs")
async def get_jobs(
    _: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.list_jobs()


@router.post("/jobs")
async def create_job(
    payload: MonitoringJobPayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.create_job(payload, current_user)


@router.put("/jobs/{job_id}")
async def update_job(
    job_id: int,
    payload: MonitoringJobUpdateSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.update_job(job_id, payload, current_user)


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: int,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.delete_job(job_id, current_user)


@router.post("/jobs/{job_id}/run")
async def run_job_now(job_id: int, current_user: OperatorOrSuperAdmin):
    return await execute_monitoring_job(job_id, actor_user_id=current_user.id, triggered_by="manual")


@router.post("/jobs/run-due")
async def run_due_jobs(request: Request):
    await verify_internal_task_request(request)
    return await execute_due_monitoring_jobs()


@router.get("/alerts")
async def get_admin_alerts(
    _: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.list_alerts()


@router.post("/alerts")
async def create_admin_alert(
    payload: AdminAlertPayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.create_alert(payload, current_user)


@router.put("/alerts/{alert_id}")
async def update_admin_alert(
    alert_id: int,
    payload: AdminAlertPayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.update_alert(alert_id, payload, current_user)


@router.delete("/alerts/{alert_id}")
async def delete_admin_alert(
    alert_id: int,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.delete_alert(alert_id, current_user)


@router.post("/alerts/replay-price/{price_id}")
async def replay_alert_for_price(price_id: int, _: OperatorOrSuperAdmin):
    try:
        return await replay_price_trigger(price_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/logs")
async def get_logs(
    _: OperatorOrSuperAdmin,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
    limit: int = Query(default=100, ge=1, le=500),
):
    return await service.list_logs(limit=limit)


@router.get("/users")
async def get_users(
    _: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.list_users()


@router.post("/users")
async def create_user(
    payload: AdminUserCreateSchema,
    current_user: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.create_user(payload, current_user)


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    payload: AdminUserUpdateSchema,
    current_user: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.update_user(user_id, payload, current_user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.delete_user(user_id, current_user)


@router.get("/settings")
async def get_settings(
    _: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.list_settings()


@router.post("/settings")
async def upsert_setting(
    payload: PlatformSettingPayloadSchema,
    current_user: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.upsert_setting(payload, current_user)


@router.delete("/settings/{setting_id}")
async def delete_setting(
    setting_id: int,
    current_user: SuperAdminOnly,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await service.delete_setting(setting_id, current_user)
