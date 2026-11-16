"""Punto de entrada principal de la API Backend de Habita (Puerto 8000).

Configura el ciclo de vida (lifespan), políticas CORS para el Frontend en React/Vite
y expone los routers de negocio bajo el prefijo /api/v1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.boundary.routers.admin_router import router as admin_router
from backend.app.boundary.routers.auth_router import router as auth_router
from backend.app.boundary.routers.catalog_router import router as catalog_router
from backend.app.boundary.routers.valuation_router import router as valuation_router
from backend.app.domain.config import CORS_ORIGINS, DB_NAME
from backend.app.infrastructure.database import init_db, verify_db_connection
from backend.app.infrastructure.ml_service_client import MLServiceClient


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Inicializa el esquema de base de datos y precarga en RAM el modelo ML de respaldo."""
    init_db()
    MLServiceClient.precargar_modelo_respaldo()
    yield


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
