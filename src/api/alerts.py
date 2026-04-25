from typing import Annotated
from fastapi import APIRouter, Depends

from celery_app.tasks.tasks import periodic_job
from models.admin import AdminRole, AdminUser
from services.prices import AlertService, CompetitorPriceService
from services.admin_auth import require_roles
from services.competitor_parsing import run_real_price_parsing
from services.products import CompetitorService, CatalogProductService
from dependencies.prices import get_alert_service, get_competitor_price_service
from dependencies.products import get_competitor_service, get_catalog_product_service

from schemas.pagination import PaginationSchema
from schemas.prices import AlertAddSchema, CompetitorAddPriceSchema

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    include_in_schema=False,
    responses={404: {"description": "Not found"}},
)

OperatorOrSuperAdmin = Annotated[
    AdminUser,
    Depends(require_roles(AdminRole.operator, AdminRole.super_admin)),
]


@router.get('/{alert_id}')
async def get_alert(
    alert_id: int,
    _: OperatorOrSuperAdmin,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
):
    res = await alert_service.get_alert(id=alert_id)
    return {"id": res}

@router.post('/list')
async def get_alerts(
    pagination: Annotated[PaginationSchema, Depends()],
    filter_by: dict,
    _: OperatorOrSuperAdmin,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
):
    res = await alert_service.get_alerts(pagination, **filter_by)
    return {"result": res}

@router.post('/')
async def add_alert(
    alert: AlertAddSchema,
    _: OperatorOrSuperAdmin,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
):
    res = await alert_service.add_alert(alert)
    return {"id": res}


@router.delete('/{alert_id}')
async def remove_alert(
    alert_id: int,
    _: OperatorOrSuperAdmin,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
):
    res = await alert_service.remove_alerts(id=alert_id)
    return {"id": res}


@router.put('/id/{alert_id}')
async def update_alert(
    alert_id: int,
    alert: AlertAddSchema,
    _: OperatorOrSuperAdmin,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
):
    res = await alert_service.update_alert(alert, id=alert_id)
    return {"id": res}

@router.get('/perform-simulate/')
async def simulate_prices(
    _: OperatorOrSuperAdmin,
    alert_service: Annotated[AlertService, Depends(get_alert_service)],
    competitor_service: Annotated[CompetitorService, Depends(get_competitor_service)],
    competitor_price_service: Annotated[CompetitorPriceService, Depends(get_competitor_price_service)],
    catalog_product_service: Annotated[CatalogProductService, Depends(get_catalog_product_service)],
):
    alerts_product_id = [(res.model_dump())["product_id"] for res in await alert_service.get_alerts(
        pagination=None, additionalProp1={"enabled": True}
    )]
    competitor_ids = [res.model_dump()["id"] for res in await competitor_service.get_competitors(
        pagination=None, additionalProp1={}
    )]

    data_dict = {}
    for item in alerts_product_id:
        product_data = await catalog_product_service.get_product_data(item, catalog_product_service.repository.session)
        if product_data["price"]:
            data_dict[item] = product_data["price"]

    competitor_prices_ids = []
    from random import randint, choice
    from schemas.prices import CompetitorAddPriceSchema

    for product_id, price in data_dict.items():
        res = await competitor_price_service.add_price(CompetitorAddPriceSchema(
            product_id=product_id,
            competitor_id=choice(competitor_ids) if competitor_ids else None,
            price=round(float(price) * choice([randint(10, 80) / 100, randint(100, 1000) / 100]), 0),
            currency="RUB",
        ))
        competitor_prices_ids.append(res)

    return {"message": "Prices simulated successfully", "competitor_price_ids": competitor_prices_ids}


@router.get("/perform-parse/")
async def perform_real_parse(_: OperatorOrSuperAdmin):
    return await run_real_price_parsing()

@router.get("/parse/")
@router.get("/simulate/")
async def run_scheduled_parse(_: OperatorOrSuperAdmin):
    task = periodic_job.delay()
    return {"task_id": task.id}
