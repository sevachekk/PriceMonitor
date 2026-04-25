from utils.repository import SQLAlchemyRepository
from models.products import CatalogProduct, Competitor


class CatalogProductRepository(SQLAlchemyRepository[CatalogProduct]):
    model = CatalogProduct
    
class CompetitorRepository(SQLAlchemyRepository[Competitor]):
    model = Competitor