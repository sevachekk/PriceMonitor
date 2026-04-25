from .alerts import router as alerts_router
from .admin import router as admin_router
from .products import router as products_router
from .rest import router as rest_router


routers = [products_router, alerts_router, admin_router, rest_router]
