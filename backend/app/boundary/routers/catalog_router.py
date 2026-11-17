"""Router HTTP para el Catálogo Consolidado de Inmuebles (Capa Boundary - <<boundary>>).

Expone el endpoint `GET /api/v1/properties` consumido por `Arrendatario.tsx` (F5 - HU-01).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from backend.app.boundary.dependencies import get_busqueda_control
from backend.app.controls.busqueda_control import BusquedaControl
from backend.app.domain.schemas.property_schemas import (
    CatalogResponseSchema,
    OrdenCatalogo,
)

router = APIRouter(prefix="/api/v1/properties", tags=["Catálogo Arrendatario (F5)"])


@router.get("", response_model=CatalogResponseSchema)
def listar_inmuebles_catalogo(
    comuna: str | None = Query(
        default=None,
        description="Filtrar por una de las 16 comunas de Medellín (o 'Todos')",
    ),
    tipo_inmueble: str | None = Query(
        default=None,
        description="Filtrar por tipo de inmueble: Apartamento, Casa, Apartaestudio (o 'Todos')",
    ),
    ordenar_por: OrdenCatalogo = Query(
        default="mejor-oferta",
        description="Criterio de ordenamiento: mejor-oferta | menor-precio | mayor-area",
    ),
    limit: int = Query(default=60, ge=1, le=200, description="Máximo de inmuebles a retornar"),
    offset: int = Query(default=0, ge=0, description="Desplazamiento para paginación"),
    control: BusquedaControl = Depends(get_busqueda_control),
) -> CatalogResponseSchema:
    """Retorna el catálogo consolidado de inmuebles con precio estimado por IA y URL original (RN-06)."""
    try:
        return control.consultar_catalogo(
            comuna=comuna,
            tipo_inmueble=tipo_inmueble,
            ordenar_por=ordenar_por,
            limit=limit,
            offset=offset,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio de base de datos PostgreSQL temporalmente no disponible (Flujo E1). Intenta reconectar.",
        ) from exc
