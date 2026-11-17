"""Punto de entrada principal de la API Backend de Habita (Puerto 8000).

Configura el ciclo de vida (lifespan), políticas CORS para el Frontend en React/Vite
y expone los routers de negocio bajo el prefijo /api/v1.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.boundary.routers.admin_router import router as admin_router
from backend.app.boundary.routers.auth_router import router as auth_router
from backend.app.boundary.routers.catalog_router import router as catalog_router
from backend.app.boundary.routers.valuation_router import router as valuation_router
from backend.app.controls.admin_orchestrator_control import AdminOrchestratorControl
from backend.app.domain.config import CORS_ORIGINS, DB_NAME
from backend.app.domain.schemas.admin_schemas import CrawlerRunRequestSchema
from backend.app.infrastructure.database import (
    SessionLocal,
    init_db,
    verify_db_connection,
)
from backend.app.infrastructure.ml_service_client import MLServiceClient
from backend.app.infrastructure.repositories.audit_repository import AuditRepository
from backend.app.infrastructure.repositories.property_repository import (
    PropertyRepository,
)

logger = logging.getLogger(__name__)
CRAWLER_SCHEDULE_SECONDS = 24 * 60 * 60  # 24 horas (Transición T-09b / RNF-03)


async def _scheduler_extraccion_24h() -> None:
    """Ejecuta periódicamente cada 24 horas la extracción automática de crawlers (T-09b / RNF-03)."""
    while True:
        await asyncio.sleep(CRAWLER_SCHEDULE_SECONDS)
        try:
            with SessionLocal() as db:
                control = AdminOrchestratorControl(
                    property_repo=PropertyRepository(db),
                    audit_repo=AuditRepository(db),
                )
                await control.ejecutar_crawlers(
                    CrawlerRunRequestSchema(portal=None),
                    admin_username="scheduler_24h",
                )
        except Exception as exc:
            logger.error("Error en ejecución programada 24h de crawlers (T-09b): %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Inicializa el esquema de BD (resiliente ante Flujo E1), precarga el modelo ML en RAM y activa el Scheduler 24h (RNF-03)."""
    try:
        init_db()
    except Exception as exc:
        logger.warning(
            "PostgreSQL aún no está disponible al iniciar (Flujo E1): %s. "
            "El servidor FastAPI iniciará y reconectará automáticamente cuando el contenedor esté activo.",
            exc,
        )
    MLServiceClient.precargar_modelo_respaldo()
    scheduler_task = asyncio.create_task(_scheduler_extraccion_24h())
    try:
        yield
    finally:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task


app = FastAPI(
    title="Habita - API Backend Principal",
    description=(
        "API de negocio para análisis, consolidación y estimación "
        "de arriendos en Medellín (Arquitectura BCE + Service)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware CORS: Permite peticiones asíncronas (fetch) desde React (localhost:5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Registro de Routers de la Capa Boundary
app.include_router(catalog_router)
app.include_router(valuation_router)
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/api/v1/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Verifica el estado del Backend y la conexión viva con PostgreSQL en Docker."""
    db_ok = verify_db_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "habita-backend",
        "database": "connected" if db_ok else "disconnected",
        "db_name": DB_NAME,
    }
