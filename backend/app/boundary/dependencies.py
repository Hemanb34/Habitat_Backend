"""Inyección de dependencias para la Capa Boundary (FastAPI).

Gestiona el ciclo de vida de la sesión de base de datos por cada petición HTTP
aplicando el principio de Inversión de Dependencias (SOLID DIP).
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.controls.admin_orchestrator_control import AdminOrchestratorControl
from backend.app.controls.analisis_competitivo_control import AnalisisCompetitivoControl
from backend.app.controls.autenticacion_control import AutenticacionControl
from backend.app.controls.busqueda_control import BusquedaControl
from backend.app.controls.valuation_facade_control import PropertyValuationFacade
from backend.app.infrastructure.database import SessionLocal
from backend.app.infrastructure.ml_service_client import MLServiceClient
from backend.app.infrastructure.repositories.admin_repository import AdminRepository
from backend.app.infrastructure.repositories.audit_repository import AuditRepository
from backend.app.infrastructure.repositories.property_repository import (
    PropertyRepository,
)
from backend.app.infrastructure.security import decode_access_token
from backend.app.services.competitive_metrics_service import CompetitiveMetricsService
from backend.app.services.pricing_strategies import PricingMarginCalculator

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Abre una sesión de SQLAlchemy al iniciar el request y la cierra al finalizar.

    El bloque try/finally garantiza que la conexión regrese al Pool del Engine
    incluso si ocurre una excepción durante el procesamiento del endpoint.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_busqueda_control(db: Session = Depends(get_db)) -> BusquedaControl:
    """Inyecta `PropertyRepository` dentro de `BusquedaControl` (SOLID DIP)."""
    repo = PropertyRepository(db)
    return BusquedaControl(property_repo=repo)


def get_valuation_facade(db: Session = Depends(get_db)) -> PropertyValuationFacade:
    """Ensambla e inyecta los 3 subsistemas dentro de `PropertyValuationFacade` (GoF Facade)."""
    ml_client = MLServiceClient()
    property_repo = PropertyRepository(db)
    metrics_service = CompetitiveMetricsService()
    return PropertyValuationFacade(
        ml_client=ml_client,
        property_repo=property_repo,
        metrics_service=metrics_service,
    )


def get_analisis_competitivo_control(
    facade: PropertyValuationFacade = Depends(get_valuation_facade),
) -> AnalisisCompetitivoControl:
    """Inyecta `PropertyValuationFacade` (GoF Facade) y `PricingMarginCalculator` (GoF Strategy)."""
    margin_calculator = PricingMarginCalculator()
    return AnalisisCompetitivoControl(
        valuation_facade=facade,
        margin_calculator=margin_calculator,
    )


def get_autenticacion_control(db: Session = Depends(get_db)) -> AutenticacionControl:
    """Inyecta `AdminRepository` dentro de `AutenticacionControl` (SOLID DIP)."""
    admin_repo = AdminRepository(db)
    return AutenticacionControl(admin_repo=admin_repo)


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """Guardián JWT para proteger los endpoints administrativos (`/api/v1/admin/*`)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT no proporcionado. Inicia sesión como Administrador.",
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None or payload.get("rol") != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token JWT inválido o expirado.",
        )
    return str(payload.get("sub", "admin"))


def get_admin_orchestrator_control(
    db: Session = Depends(get_db),
) -> AdminOrchestratorControl:
    """Inyecta `PropertyRepository` y `AuditRepository` en `AdminOrchestratorControl`."""
    property_repo = PropertyRepository(db)
    audit_repo = AuditRepository(db)
    return AdminOrchestratorControl(
        property_repo=property_repo,
        audit_repo=audit_repo,
    )
