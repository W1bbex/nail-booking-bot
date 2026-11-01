from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routes_admin import router as admin_router
from api.routes_client import router as client_router
from core.config import settings
from core.database import init_db
from core.logger import setup_logger

logger = setup_logger("api.app")

BASE_DIR = Path(__file__).resolve().parent.parent
MINIAPP_DIR = BASE_DIR / "miniapp"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI application starting up...")
    await init_db()
    yield


app = FastAPI(
    title="Nail Atelier Booking API",
    description="Backend API and Mini App service for Nail Salon Telegram Bot",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(client_router)
app.include_router(admin_router)

# Mount Telegram Mini App static assets
if MINIAPP_DIR.is_dir():
    app.mount("/miniapp", StaticFiles(directory=str(MINIAPP_DIR), html=True), name="miniapp")


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/miniapp/")


@app.get("/api/health")
async def health_check() -> dict:
    return {
        "status": "ok",
        "service": "nail-booking-bot",
        "dev_mode": settings.dev_mode,
        "database": "sqlite_aiosqlite",
    }
