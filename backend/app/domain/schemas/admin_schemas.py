"""Schemas Pydantic (DTOs) para el Panel de Administración (F1, F2, F3 - AdminDashboard.tsx).

Define las estructuras de respuesta de `GET /api/v1/admin/dashboard`,
`POST /api/v1/admin/crawlers/run` y `POST /api/v1/admin/ml/retrain`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PortalStatusSchema(BaseModel):
    """Estado operativo y conteo real en BD de cada uno de los 3 portales (F1)."""

    key: str
    name: str
    url: str
    records: int
    lastRun: str
    status: Literal["idle", "running", "error"] = "idle"


class DailyScrapeItemSchema(BaseModel):
    """Conteo de registros procesados por día/ciclo para la gráfica de barras."""

    day: str
    count: int


class AuditLogItemSchema(BaseModel):
    """Fila de la tabla de auditoría inmutable (RNF-09)."""

    id: int
    time: str
    event: str
    result: Literal["OK", "WARN", "ERROR"]
    records: int | None = None
    usuario: str = "admin"


class ModelStatusSchema(BaseModel):
    """Estado del modelo predictivo en producción y su cumplimiento de RN-01 (MAPE <= 16%)."""

    version: str
    fecha_entrenamiento: str
    mape_poblado_pct: float
    mape_otras_comunas_pct: float
    mape_global_pct: float
    umbral_rn01_pct: float = 16.0
    en_produccion: bool = True
    total_registros_entrenamiento: int
    historial_mape: list[float]


class AdminDashboardResponseSchema(BaseModel):
    """DTO integral para poblar las 3 pestañas de `AdminDashboard.tsx`."""

    total_inmuebles: int
    portales_activos: int
    ultima_extraccion_texto: str
    ultimos_registros_procesados: int
    portales: list[PortalStatusSchema]
    scrape_data: list[DailyScrapeItemSchema]
    modelo: ModelStatusSchema
    audit_logs: list[AuditLogItemSchema]


class CrawlerRunRequestSchema(BaseModel):
    """Solicitud para disparar un crawler específico o los 3 en paralelo (Fork/Join)."""

    portal: str | None = Field(
        default=None,
        description="Nombre o clave del portal ('fincaraiz', 'metrocuadrado', 'ciencuadras') o None para todos",
    )
    max_pages: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Páginas por semilla a consultar durante la ejecución administrativa",
    )
    max_zones: int | None = Field(
        default=None,
        ge=1,
        le=17,
        description="Cantidad de zonas/comunas a recorrer por portal (None = las 17 zonas completas)",
    )


class CrawlerRunResponseSchema(BaseModel):
    """Resultado de la ejecución de crawlers y su persistencia (Upsert) en PostgreSQL."""

    exito: bool
    portales_ejecutados: list[str]
    registros_extraidos_brutos: int
    registros_validos_rn06: int
    nuevos_insertados: int
    actualizados: int
    duracion_segundos: float
    mensaje: str


class ModelRetrainResponseSchema(BaseModel):
    """Resultado del ciclo de reentrenamiento Template Method y compuerta RN-01."""

    exito: bool
    promovido_a_produccion: bool
    version_modelo: str
    mape_poblado_pct: float
    mape_otras_comunas_pct: float
    mape_global_pct: float
    umbral_rn01_pct: float = 16.0
    total_registros_entrenamiento: int
    mensaje: str
