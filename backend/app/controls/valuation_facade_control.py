"""Patrón GoF Facade: PropertyValuationFacade (Capa Control - <<control>>).

Implementa el 4.º Patrón GoF del proyecto (Estructural - Facade) para la
funcionalidad F6 (Estimación de Precio y Búsqueda de Competidores Similares).

Oculta detrás de un único método (`estimar_y_comparar`) la interacción y
sincronización concurrente (Fork/Join con `asyncio.gather`) de 3 subsistemas:
1. Subsistema Predictivo (`IMLServiceClient`) -> Inferencia ML y MAPE (RN-01).
2. Subsistema de Persistencia (`IPropertyRepository`) -> Búsqueda SQL bajo los
   4 criterios estrictos de comparabilidad de RN-03.
3. Subsistema Estadístico (`CompetitiveMetricsService`) -> Cálculo de mínimo,
   promedio y máximo del sector (RF-05).
"""

from __future__ import annotations

import asyncio

from backend.app.domain.interfaces.ml_client import IMLServiceClient
from backend.app.domain.interfaces.repositories import IPropertyRepository
from backend.app.domain.schemas.valuation_schemas import (
    CompetitorItemSchema,
    PropertyEstimateRequestSchema,
    PropertyEstimateResponseSchema,
)
from backend.app.services.competitive_metrics_service import CompetitiveMetricsService


class PropertyValuationFacade:
    """Fachada <<control>> que unifica la valoración IA y el análisis de comparables RN-03."""

    def __init__(
        self,
        ml_client: IMLServiceClient,
        property_repo: IPropertyRepository,
        metrics_service: CompetitiveMetricsService,
    ) -> None:
        self._ml_client = ml_client
        self._property_repo = property_repo
        self._metrics_service = metrics_service

    async def estimar_y_comparar(
        self,
        solicitud: PropertyEstimateRequestSchema,
    ) -> PropertyEstimateResponseSchema:
        """Ejecuta el flujo Fork/Join del Diagrama F6 en <= 3 segundos (RNF-05)."""
        # BARRA FORK: Lanzar en paralelo la inferencia ML (Rama 1) y la consulta SQL RN-03 (Rama 2)
        tarea_ml = self._ml_client.predecir_precio(
            comuna=solicitud.comuna,
            barrio=solicitud.barrio,
            tipo_inmueble=solicitud.tipo_inmueble,
            area=solicitud.area,
            habitaciones=solicitud.habitaciones,
            banos=solicitud.banos,
            parqueaderos=solicitud.parqueaderos,
            estrato=solicitud.estrato,
            amoblado=solicitud.amoblado,
            incluye_administracion=solicitud.incluye_administracion,
        )

        tarea_similares = asyncio.to_thread(
            self._property_repo.buscar_similares_rn03,
            solicitud.comuna,
            solicitud.estrato,
            solicitud.tipo_inmueble,
            solicitud.area,
            10,
        )

        # BARRA JOIN: Sincronizar ambas respuestas
        prediccion_ml, competidores_entidades = await asyncio.gather(
            tarea_ml,
            tarea_similares,
        )

        precio_est = prediccion_ml.precio_estimado_cop

        # Subsistema 3: Calcular métricas estadísticas del sector (RF-05)
        metricas = self._metrics_service.calcular_metricas_sector(
            competidores=competidores_entidades,
            area_base=solicitud.area,
            precio_estimado_fallback=precio_est,
        )

        # Transformar competidores RN-03 a DTO calculando su desviación frente al estimado IA
        competidores_dto = [
            CompetitorItemSchema(
                id=inm.id,
                title=inm.title,
                comuna=inm.comuna,
                tipo_inmueble=inm.tipo_inmueble,
                estrato=inm.estrato,
                area=inm.area,
                habitaciones=inm.habitaciones,
                banos=inm.banos,
                parqueaderos=inm.parqueaderos,
                precio_publicado=inm.precio_publicado,
                portal=inm.portal,
                url_origen=inm.url_origen,
                diferencia_vs_estimado_pct=round(
                    ((inm.precio_publicado - precio_est) / precio_est) * 100.0,
                    1,
                )
                if precio_est > 0
                else 0.0,
            )
            for inm in competidores_entidades
        ]

        return PropertyEstimateResponseSchema(
            precio_estimado=precio_est,
            precio_m2_estimado=prediccion_ml.precio_m2_estimado_cop,
            modelo_utilizado=prediccion_ml.modelo_utilizado,
            version_modelo=prediccion_ml.version_modelo,
            mape_modelo_pct=round(prediccion_ml.mape_validacion_modelo * 100.0, 2),
            umbral_rn01_pct=16.0,
            metricas_mercado=metricas,
            competidores=competidores_dto,
            rango_sugerido_inferior=round(precio_est * 0.95, 0),
            rango_sugerido_superior=round(precio_est * 1.05, 0),
        )
