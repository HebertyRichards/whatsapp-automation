from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config.database import SessionLocal, engine
from app.config.logging_config import setup_logging
from app.config.redis_client import close_redis, init_redis
from app.config.settings import get_settings
from app.errors import register_exception_handlers
from app.repositories.store_repository import StoreRepository
from app.routes.webhook_routes import webhook_routes, webhook_tag_metadata
from app.services.evolution_service import close_evolution_client
from app.services.inbound_service import get_inbound_service

settings = get_settings()

setup_logging(settings.log_level, json_logs=settings.log_json or settings.is_production)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_redis()
    yield
    await get_inbound_service().shutdown()
    await close_evolution_client()
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title="WhatsApp Order Bot",
    description="Menu-driven WhatsApp ordering bot on top of the Evolution API.",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[webhook_tag_metadata],
)

register_exception_handlers(app)

app.include_router(webhook_routes)


def _unavailable(dependency: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={"status": "unavailable", "dependency": dependency})


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
async def ready() -> JSONResponse:
    try:
        async with SessionLocal() as session:
            store = await StoreRepository(session).get_settings()
    except Exception:
        return _unavailable("database")
    # Without the settings row the bot stays silent, so that counts as not ready.
    if store is None:
        return _unavailable("store_settings")
    return JSONResponse(content={"status": "ready"})
