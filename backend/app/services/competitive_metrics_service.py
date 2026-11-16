"""Servicio de Dominio CompetitiveMetricsService (Capa Service - <<service>>).

Calcula las estadísticas descriptivas del mercado competitivo local (RF-05):
precio mínimo, precio promedio y precio máximo a partir del conjunto de
inmuebles comparables filtrados bajo la regla RN-03.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.domain.entities.property_entity import Inmueble
from backend.app.domain.schemas.valuation_schemas import MarketMetricsSchema


class CompetitiveMetricsService:
    """Servicio <<service>> sin estado para el cálculo de indicadores de mercado (RF-05)."""

    def calcular_metricas_sector(
        self,
        competidores: Sequence[Inmueble],
        area_base: float,
        precio_estimado_fallback: float,
    ) -> MarketMetricsSchema:
        """Calcula mínimo, promedio y máximo de los competidores RN-03.

        Si para una combinación atípica no existieran competidores exactos en la BD,
        utiliza una banda de referencia ±8% alrededor del precio estimado IA para no
        devolver ceros a la interfaz gráfica.
        """
        rango_area_min = round(area_base * 0.85, 1)
        rango_area_max = round(area_base * 1.15, 1)

        if not competidores:
            return MarketMetricsSchema(
                total_competidores=0,
                precio_minimo=round(precio_estimado_fallback * 0.92, 0),
                precio_promedio=round(precio_estimado_fallback, 0),
                precio_maximo=round(precio_estimado_fallback * 1.08, 0),
                rango_area_min_rn03=rango_area_min,
                rango_area_max_rn03=rango_area_max,
            )

        precios = [float(c.precio_publicado) for c in competidores]
        minimo = round(min(precios), 0)
        maximo = round(max(precios), 0)
        promedio = round(sum(precios) / len(precios), 0)

        return MarketMetricsSchema(
            total_competidores=len(precios),
            precio_minimo=minimo,
            precio_promedio=promedio,
            precio_maximo=maximo,
            rango_area_min_rn03=rango_area_min,
            rango_area_max_rn03=rango_area_max,
        )
