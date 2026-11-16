"""Router HTTP para Estimación de Precio y Análisis Competitivo (Capa Boundary - <<boundary>>).

Expone:
- `POST /api/v1/properties/estimate` (F6 + F4: Patrón GoF Facade + Patrón GoF Strategy)
- `POST /api/v1/properties/margin`   (F4: Evaluación puntual de una estrategia con GoF Strategy)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.boundary.dependencies import get_analisis_competitivo_control
from backend.app.controls.analisis_competitivo_control import AnalisisCompetitivoControl
from backend.app.domain.schemas.valuation_schemas import (
    MarginCalculationRequestSchema,
    PricingRecommendationSchema,
    PropertyEstimateRequestSchema,
    PropertyEstimateResponseSchema,
)

router = APIRouter(prefix="/api/v1/properties", tags=["Valoración Propietario (F6 / F4)"])


@router.post("/estimate", response_model=PropertyEstimateResponseSchema)
async def estimar_precio_inmueble(
    payload: PropertyEstimateRequestSchema,
    control: AnalisisCompetitivoControl = Depends(get_analisis_competitivo_control),
) -> PropertyEstimateResponseSchema:
    """Ejecuta la Fachada (Fork/Join ML + SQL RN-03) y calcula las 3 estrategias GoF Strategy."""
    return await control.ejecutar_analisis_integral(payload)


@router.post("/margin", response_model=PricingRecommendationSchema)
def calcular_margen_comercial(
    payload: MarginCalculationRequestSchema,
    control: AnalisisCompetitivoControl = Depends(get_analisis_competitivo_control),
) -> PricingRecommendationSchema:
    """Calcula el precio sugerido intercambiando en tiempo de ejecución la estrategia (GoF Strategy)."""
    return control.calcular_margen_estrategia(payload)
