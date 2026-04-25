from db.db import CurrSession
from services.admin import AdminControlService


def get_admin_control_service(session: CurrSession) -> AdminControlService:
    return AdminControlService(session)
