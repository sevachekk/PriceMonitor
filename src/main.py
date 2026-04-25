from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routers import routers
from db.db import init_db
from middleware.rate_limit import InMemoryRateLimitMiddleware
from services.rest_api import run_startup_recovery

@asynccontextmanager
async def lifespan(app: FastAPI):
    import models.products
    import models.prices
    import models.admin
    import trigger.competitor_price_trigger
    await init_db()
    await run_startup_recovery()
    yield
    
app = FastAPI(lifespan=lifespan)

settings = None
try:
    from settings.config import get_settings
    settings = get_settings()
except Exception:
    settings = None

allow_origins = ["*"]
allow_credentials = False
if settings and settings.CORS_ALLOW_ORIGINS.strip():
    parsed_origins = [
        origin.strip()
        for origin in settings.CORS_ALLOW_ORIGINS.split(",")
        if origin.strip()
    ]
    if parsed_origins:
        allow_origins = parsed_origins
        allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(InMemoryRateLimitMiddleware)

for router in routers:
    app.include_router(router)


@app.get("/health", include_in_schema=False)
async def healthcheck():
    return JSONResponse({"status": "ok"})


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADMIN_CONSOLE_DIR = PROJECT_ROOT / "admin_console"

if ADMIN_CONSOLE_DIR.exists():
    app.mount("/", StaticFiles(directory=str(ADMIN_CONSOLE_DIR), html=True), name="admin-console")
