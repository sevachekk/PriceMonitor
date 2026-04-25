from db.db import CurrSession
from services.rest_api import RestAPIService


def get_rest_api_service(session: CurrSession) -> RestAPIService:
    return RestAPIService(session)
