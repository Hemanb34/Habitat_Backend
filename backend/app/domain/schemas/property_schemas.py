"""Schemas Pydantic (DTOs) para el Catálogo Consolidado de Inmuebles (F5 - HU-01).

Define la estructura validada que el Backend devuelve al Frontend en `GET /api/v1/properties`,
garantizando la presencia de `url_origen` (RN-06) y las métricas de comparación con IA.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrdenCatalogo = Literal["mejor-oferta", "menor-precio", "mayor-area"]


class PropertyCatalogItemSchema(BaseModel):
    """DTO de un inmueble individual dentro del catálogo de arrendatarios."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    comuna: str
    barrio: str | None = None
    tipo_inmueble: str
    area: float
    habitaciones: int
    banos: int
    parqueaderos: int
    estrato: int
    precio_publicado: float
    precio_estimado: float
    portal: str
    imagen_url: str | None = None
    url_origen: str = Field(..., description="URL original obligatoria del portal (RN-06)")
    amoblado: bool = False
    incluye_administracion: bool = False
    valor_administracion: float | None = None
    diferencia_pct: float = Field(
        ...,
        description="Porcentaje de ahorro (+) o sobreprecio (-) frente al estimado IA",
    )
    etiqueta_oferta: str = Field(
        ...,
        description="Clasificación comercial: Excelente precio | Buen precio | Precio justo | Precio elevado",
    )


class CatalogResponseSchema(BaseModel):
    """Respuesta paginada y enriquecida del catálogo de inmuebles (`GET /api/v1/properties`)."""

    total: int = Field(..., description="Total de inmuebles que coinciden con los filtros aplicados")
    comunas_disponibles: list[str] = Field(
        default_factory=list,
        description="Lista ordenada de las comunas presentes en el catálogo",
    )
    tipos_disponibles: list[str] = Field(
        default_factory=list,
        description="Lista ordenada de los tipos de inmueble presentes en el catálogo",
    )
    items: list[PropertyCatalogItemSchema]
