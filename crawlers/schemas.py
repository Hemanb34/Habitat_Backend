"""
schemas.py — Esquemas Pydantic canónicos del módulo de ingesta (Crawlers).

Define el contrato de datos `PropertyCreate` producido por los adaptadores
(`PropertyDataAdapter`) y validado estrictamente bajo la regla de negocio RN-06
(toda propiedad debe poseer URL original válida de trazabilidad).
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class PropertyCreate(BaseModel):
    """
    DTO canónico de un inmueble extraído y adaptado desde cualquier portal.
    Cumple con el Principio de Sustitución de Liskov (LSP) y la regla RN-06.
    """

    portal: str = Field(..., description="Portal de origen: metrocuadrado | fincaraiz | ciencuadras")
    title: Optional[str] = Field(default=None, description="Título o descripción corta del anuncio")
    tipo_inmueble: Optional[str] = Field(default=None, description="Apartamento, Casa, Apartaestudio")
    area: Optional[float] = Field(default=None, description="Área construida o privada en m²")
    estrato: Optional[int] = Field(default=None, description="Estrato socioeconómico (1 a 6)")
    comuna: str = Field(..., description="Nombre canónico de la comuna en Medellín")
    barrio: Optional[str] = Field(default=None, description="Nombre del barrio reportado por el portal")
    habitaciones: Optional[int] = Field(default=None, description="Número de habitaciones")
    banos: Optional[int] = Field(default=None, description="Número de baños")
    parqueaderos: int = Field(default=0, description="Número de parqueaderos")
    estado: Optional[str] = Field(default=None, description="Nuevo o Usado")
    imagen_url: Optional[str] = Field(default=None, description="URL de la imagen principal")
    precio_publicado: float = Field(..., gt=0, description="Canon de arrendamiento mensual en COP (> 0)")
    url_origen: str = Field(..., description="URL pública original del anuncio (Obligatoria por RN-06)")
    incluye_administracion: bool = Field(default=False, description="Indica si el canon incluye administración")
    amoblado: bool = Field(default=False, description="Indica si el inmueble se arrienda amoblado")
    latitud: Optional[float] = Field(default=None, description="Latitud geográfica WGS84")
    longitud: Optional[float] = Field(default=None, description="Longitud geográfica WGS84")
    antiguedad: Optional[str] = Field(default=None, description="Rango o años de antigüedad")
    valor_administracion: Optional[float] = Field(default=None, description="Valor de administración en COP")

    @field_validator("url_origen")
    @classmethod
    def validate_rn06_url_origen(cls, value: str) -> str:
        """
        Regla de Negocio RN-06: Descarte obligatorio de registros sin URL original.
        """
        cleaned = (value or "").strip()
        if not cleaned or not (cleaned.startswith("http://") or cleaned.startswith("https://")):
            raise ValueError("RN-06 violada: 'url_origen' es obligatoria y debe ser una URL HTTP/HTTPS válida.")
        return cleaned


class PortalCrawlReport(BaseModel):
    """Métricas de auditoría por portal para RNF-09 (crawler_jobs / audit_logs)."""

    portal: str
    status: str = "SUCCESS"
    raw_extracted: int = 0
    rejected_rn06_or_invalid: int = 0
    duplicates_removed: int = 0
    valid_unique_items: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None


class OrchestrationSummary(BaseModel):
    """Resumen consolidado de la ejecución paralela Fork/Join de todos los portales."""

    total_raw_extracted: int
    total_rejected: int
    total_duplicates_removed: int
    total_valid_unique: int
    elapsed_seconds: float
    portal_reports: list[PortalCrawlReport]
    items: list[PropertyCreate]
