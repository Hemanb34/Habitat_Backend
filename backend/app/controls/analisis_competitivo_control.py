"""Controlador de caso de uso AnalisisCompetitivoControl (Capa Control - <<control>>).

Coordina la Fachada de Valoración (`PropertyValuationFacade` - Patrón GoF Facade)
con el Calculador de Márgenes (`PricingMarginCalculator` - Patrón GoF Strategy)
para entregar las recomendaciones de publicación de la funcionalidad F4 (HU-08, RF-06, RN-04).
"""

from __future__ import annotations

from backend.app.controls.valuation_facade_control import PropertyValuationFacade
from backend.app.domain.schemas.valuation_schemas import (
    MarginCalculationRequestSchema,
    PricingRecommendationSchema,
    PropertyEstimateRequestSchema,
    PropertyEstimateResponseSchema,
)
from backend.app.services.pricing_strategies import PricingMarginCalculator


class AnalisisCompetitivoControl:
    """Orquestador <<control>> para el cálculo de márgenes y estrategias comerciales (F4)."""

    def __init__(
        self,
        valuation_facade: PropertyValuationFacade,
        margin_calculator: PricingMarginCalculator,
    ) -> None:
        self._valuation_facade = valuation_facade
        self._margin_calculator = margin_calculator

    async def ejecutar_analisis_integral(
        self,
        solicitud: PropertyEstimateRequestSchema,
    ) -> PropertyEstimateResponseSchema:
        """Obtiene la valoración base de la Fachada y evalúa las 3 estrategias GoF Strategy."""
        respuesta = await self._valuation_facade.estimar_y_comparar(solicitud)

        estrategias = self._margin_calculator.evaluar_todas_las_estrategias(
            precio_base=respuesta.precio_estimado,
            metricas_mercado=respuesta.metricas_mercado,
        )

        respuesta.estrategias_comerciales = estrategias
        respuesta.rango_sugerido_inferior = estrategias["liquidez"].precio_sugerido
        respuesta.rango_sugerido_superior = estrategias["rentabilidad"].precio_sugerido
        return respuesta

    def calcular_margen_estrategia(
        self,
        solicitud: MarginCalculationRequestSchema,
    ) -> PricingRecommendationSchema:
        """Evalúa dinámicamente una estrategia específica seleccionada por el propietario."""
        return self._margin_calculator.calcular_por_clave(
            clave=solicitud.estrategia,
            precio_base=solicitud.precio_base_estimado,
            metricas_mercado=solicitud.metricas_mercado,
        )
