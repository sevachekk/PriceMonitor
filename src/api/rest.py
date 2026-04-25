from typing import Annotated

from fastapi import APIRouter, Depends, Query

from dependencies.admin import get_admin_control_service
from dependencies.rest import get_rest_api_service
from models.admin import AdminRole, AdminUser
from schemas.admin import AdminAlertPayloadSchema, AdminUserLoginSchema, AdminUserReadSchema, SourcePayloadSchema
from schemas.rest import BackupFilterSchema, CurrentPriceFilterSchema, PriceHistoryFilterSchema, RuleFilterSchema, ServiceSettingFilterSchema, SourceFilterSchema
from services.admin import AdminControlService
from services.admin_auth import authenticate_admin, get_current_admin, require_roles
from services.rest_api import RestAPIService


router = APIRouter(
    prefix="/api/v1",
    tags=["rest-api"],
    responses={404: {"description": "Not found"}},
)


OperatorOrSuperAdmin = Annotated[
    AdminUser,
    Depends(require_roles(AdminRole.operator, AdminRole.super_admin)),
]
SuperAdminOnly = Annotated[AdminUser, Depends(require_roles(AdminRole.super_admin))]


@router.post("/auth/login")
async def login(
    credentials: AdminUserLoginSchema,
    service: Annotated[AdminControlService, Depends(get_admin_control_service)],
):
    return await authenticate_admin(service.session, credentials)


@router.get("/auth/me")
async def me(current_user: Annotated[AdminUser, Depends(get_current_admin)]):
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
async def logout(current_user: Annotated[AdminUser, Depends(get_current_admin)]):
    return {"message": f"User {current_user.username} logged out"}


@router.get("/prices/current")
async def get_current_prices(
    filters: Annotated[CurrentPriceFilterSchema, Depends()],
    _: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.list_current_prices(filters)


@router.get("/prices/history")
async def get_price_history(
    filters: Annotated[PriceHistoryFilterSchema, Depends()],
    _: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.list_price_history(filters)


@router.get("/sources")
async def get_sources(
    filters: Annotated[SourceFilterSchema, Depends()],
    _: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.list_source_configs(filters)


@router.get("/sources/{source_id}")
async def get_source(
    source_id: int,
    _: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.get_source_config(source_id)


@router.post("/sources")
async def create_source(
    payload: SourcePayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.create_source_config(payload, current_user)


@router.put("/sources/{source_id}")
async def update_source(
    source_id: int,
    payload: SourcePayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.update_source_config(source_id, payload, current_user)


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.delete_source_config(source_id, current_user)


@router.get("/rules")
async def get_rules(
    filters: Annotated[RuleFilterSchema, Depends()],
    _: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.list_rules(filters)


@router.get("/rules/{rule_id}")
async def get_rule(
    rule_id: int,
    _: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.get_rule(rule_id)


@router.get("/service-settings")
async def get_service_settings(
    filters: Annotated[ServiceSettingFilterSchema, Depends()],
    _: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.list_service_settings(filters)


@router.post("/rules")
async def create_rule(
    payload: AdminAlertPayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.create_rule(payload, current_user)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    payload: AdminAlertPayloadSchema,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.update_rule(rule_id, payload, current_user)


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    current_user: OperatorOrSuperAdmin,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.delete_rule(rule_id, current_user)


@router.get("/recovery/status")
async def get_recovery_status(
    _: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.get_recovery_status()


@router.post("/recovery/unblock-sources")
async def unblock_sources(
    current_user: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
    force: bool = Query(default=True),
):
    return await service.unblock_sources(current_user, force=force)


@router.post("/recovery/replay-pending-alerts")
async def replay_pending_alerts(
    current_user: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
    limit: int = Query(default=200, ge=1, le=5000),
):
    return await service.replay_pending_price_alerts(current_user, limit=limit)


@router.get("/backups")
async def get_backups(
    filters: Annotated[BackupFilterSchema, Depends()],
    _: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.list_backups(filters)


@router.post("/backups")
async def create_backup(
    current_user: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.create_backup(current_user)


@router.delete("/backups/{backup_name}")
async def delete_backup(
    backup_name: str,
    current_user: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.delete_backup(backup_name, current_user)


@router.post("/backups/{backup_name}/restore")
async def restore_backup(
    backup_name: str,
    current_user: SuperAdminOnly,
    service: Annotated[RestAPIService, Depends(get_rest_api_service)],
):
    return await service.restore_backup(backup_name, current_user)
