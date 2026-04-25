from typing import Annotated
from fastapi import APIRouter, Depends

from services.products import CatalogProductService, CompetitorService
from dependencies.products import get_catalog_product_service, get_competitor_service
from schemas.pagination import PaginationSchema
from schemas.products import CompetitorAddSchema

from db.db import CurrSession

router = APIRouter(
    prefix="/products",
    tags=["products"],
    include_in_schema=False,
    responses={404: {"description": "Not found"}},
)
