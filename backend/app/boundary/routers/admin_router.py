"""Router HTTP para el Panel de Administración (Capa Boundary - <<boundary>>).

Todos los endpoints están protegidos por el guardián JWT `get_current_admin` (RN-05):
- `GET  /api/v1/admin/dashboard`    (Métricas de portales, historial MAPE y auditoría RNF-09)
- `POST /api/v1/admin/crawlers/run` (F1 - Orquestación de Crawlers + Upsert en PostgreSQL)
- `POST /api/v1/admin/ml/retrain`   (F2/F3 - Reentrenamiento Template Method + Compuerta RN-01)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.boundary.dependencies import (
    get_admin_orchestrator_control,
    get_current_admin,
)
from backend.app.controls.admin_orchestrator_control import AdminOrchestratorControl
from backend.app.domain.schemas.admin_schemas import (
    AdminDashboardResponseSchema,
    CrawlerRunRequestSchema,
    CrawlerRunResponseSchema,
    ModelRetrainResponseSchema,
)

router = APIRouter(prefix="/api/v1/admin", tags=["Administración (F1, F2, F3 - RNF-09)"])


@router.get("/dashboard", response_model=AdminDashboardResponseSchema)
def obtener_dashboard_admin(
    _admin_user: str = Depends(get_current_admin),
    control: AdminOrchestratorControl = Depends(get_admin_orchestrator_control),
) -> AdminDashboardResponseSchema:
    """Devuelve las métricas consolidadas en tiempo real desde PostgreSQL."""
    return control.obtener_estado_dashboard()


@router.post("/crawlers/run", response_model=CrawlerRunResponseSchema)
async def ejecutar_crawlers_admin(
    payload: CrawlerRunRequestSchema,
    admin_user: str = Depends(get_current_admin),
    control: AdminOrchestratorControl = Depends(get_admin_orchestrator_control),
) -> CrawlerRunResponseSchema:
    """Dispara la extracción concurrente (Fork/Join) de uno o todos los portales."""
    return await control.ejecutar_crawlers(payload, admin_username=admin_user)


@router.post("/ml/retrain", response_model=ModelRetrainResponseSchema)
def ejecutar_reentrenamiento_admin(
    admin_user: str = Depends(get_current_admin),
    control: AdminOrchestratorControl = Depends(get_admin_orchestrator_control),
) -> ModelRetrainResponseSchema:
    """Ejecuta y valida el modelo predictivo bajo la compuerta RN-01 (MAPE <= 16%)."""
    return control.ejecutar_reentrenamiento_ml(admin_username=admin_user)
