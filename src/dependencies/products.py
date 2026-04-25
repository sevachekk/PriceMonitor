from db.db import CurrSession
from services.products import CatalogProductService, CompetitorService
from repositories.products import CatalogProductRepository, CompetitorRepository


def get_catalog_product_service(session: CurrSession) -> CatalogProductService:
    repository = CatalogProductRepository(session)
    service = CatalogProductService(repository)
    return service

def get_competitor_service(session: CurrSession) -> CompetitorService:
    repository = CompetitorRepository(session)
    service = CompetitorService(repository)
    return service