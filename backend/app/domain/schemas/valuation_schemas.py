"""Schemas Pydantic (DTOs) para Estimación de Precio y Análisis Competitivo (F6 y F4).

Define los contratos de entrada y salida para:
- `POST /api/v1/properties/estimate` (Slice 2 - Patrón GoF Facade + RN-03 + RF-05)
- `POST /api/v1/properties/margin`   (Slice 3 - Patrón GoF Strategy + RN-04 + RF-06)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EstrategiaComercialKey = Literal["liquidez", "balanceada", "rentabilidad"]


class PropertyEstimateRequestSchema(BaseModel):
    """Datos del inmueble ingresados por el propietario en `Propietario.tsx`."""

    comuna: str = Field(..., min_length=2, description="Comuna oficial de Medellín (ej. 'El Poblado', 'Laureles - Estadio')")
    barrio: str | None = Field(default=None, description="Barrio opcional dentro de la comuna")
    tipo_inmueble: str = Field(..., description="Apartamento, Casa o Apartaestudio")
    area: float = Field(..., ge=15.0, le=1000.0, description="Área construida en m²")
    estrato: int = Field(..., ge=1, le=6, description="Estrato socioeconómico (1 a 6)")
    habitaciones: int = Field(..., ge=1, le=10, description="Número de habitaciones")
    banos: int = Field(..., ge=1, le=10, description="Número de baños")
    parqueaderos: int = Field(default=0, ge=0, le=10, description="Número de parqueaderos")
    amoblado: bool = Field(default=False, description="Indica si se arrienda amoblado")
    incluye_administracion: bool = Field(default=False, description="Indica si el canon incluye administración")


class CompetitorItemSchema(BaseModel):
    """Inmueble competidor real encontrado en PostgreSQL bajo los 4 criterios de RN-03."""

    id: int
    title: str
    comuna: str
    tipo_inmueble: str
    estrato: int
    area: float
    habitaciones: int
    banos: int
    parqueaderos: int
    precio_publicado: float
    portal: str
    url_origen: str
    diferencia_vs_estimado_pct: float = Field(
        ...,
        description="Variación porcentual del competidor respecto al precio estimado IA",
    )


class MarketMetricsSchema(BaseModel):
    """Métricas estadísticas del sector calculadas por `CompetitiveMetricsService` (RF-05)."""

    total_competidores: int
    precio_minimo: float
    precio_promedio: float
    precio_maximo: float
    rango_area_min_rn03: float
    rango_area_max_rn03: float


class PricingRecommendationSchema(BaseModel):
    """Resultado de una estrategia comercial concreta del Patrón GoF Strategy (RN-04, RF-06)."""

    clave: EstrategiaComercialKey
    nombre_estrategia: str
    objetivo_comercial: str
    precio_sugerido: float
    limite_inferior: float
    limite_superior: float
    ajuste_aplicado_pct: float
    explicacion: str


class MarginCalculationRequestSchema(BaseModel):
    """Solicitud directa para calcular una estrategia comercial específica (`POST /properties/margin`)."""

    estrategia: EstrategiaComercialKey = Field(
        default="balanceada",
        description="Estrategia comercial a evaluar: liquidez | balanceada | rentabilidad",
    )
    precio_base_estimado: float = Field(..., gt=0)
    metricas_mercado: MarketMetricsSchema


class PropertyEstimateResponseSchema(BaseModel):
    """Respuesta consolidada devuelta por `PropertyValuationFacade` y `AnalisisCompetitivoControl`."""

    precio_estimado: float = Field(..., description="Canon mensual estimado por el modelo ML en COP")
    precio_m2_estimado: float = Field(..., description="Valor estimado por m² en COP")
    modelo_utilizado: str = Field(..., description="Régimen aplicado: El Poblado u Otras Comunas")
    version_modelo: str
    mape_modelo_pct: float = Field(
        ...,
        description="MAPE vigente del modelo en porcentaje (cumpliendo RN-01 <= 16%)",
    )
    umbral_rn01_pct: float = Field(default=16.0, description="Umbral máximo permitido por RN-01 (16%)")
    metricas_mercado: MarketMetricsSchema
    competidores: list[CompetitorItemSchema]
    rango_sugerido_inferior: float
    rango_sugerido_superior: float
    estrategias_comerciales: dict[EstrategiaComercialKey, PricingRecommendationSchema] = Field(
        default_factory=dict,
        description="Las 3 estrategias del Patrón GoF Strategy evaluadas para el propietario (F4)",
    )
