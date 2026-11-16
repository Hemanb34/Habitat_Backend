"""Entidad ORM de Dominio Inmueble (<<entity>>).

Representa la tabla `properties` en PostgreSQL y encapsula las reglas de negocio
intrínsecas de un inmueble en arriendo:
- RN-06: Trazabilidad obligatoria mediante `url_origen` única y no nula.
- RN-03: Criterio estricto de comparabilidad (misma comuna, mismo estrato,
         mismo tipo de inmueble y área dentro del rango ±15%).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base


class Inmueble(Base):
    """Entidad persistente <<entity>> mapeada a la tabla `properties`."""

    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portal: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    tipo_inmueble: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    area: Mapped[float] = mapped_column(Float, nullable=False)
    estrato: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    comuna: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    barrio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    habitaciones: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    banos: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parqueaderos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estado: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Precios en pesos colombianos (COP)
    precio_publicado: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    precio_estimado: Mapped[float] = mapped_column(Float, nullable=False)
    valor_administracion: Mapped[float | None] = mapped_column(Float, nullable=True)
    incluye_administracion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    amoblado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Multimedia y Trazabilidad obligatoria (RN-06)
    imagen_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_origen: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # Coordenadas geográficas (WGS84) y antigüedad
    latitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    antiguedad: Mapped[str | None] = mapped_column(String(60), nullable=True)

    fecha_extraccion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Índice compuesto para acelerar consultas de catálogo (RNF-04 <= 2s)
    # y búsqueda de competidores comparables (RN-03, RNF-05 <= 3s)
    __table_args__ = (
        Index(
            "ix_properties_rn03_comparables",
            "comuna",
            "estrato",
            "tipo_inmueble",
            "area",
        ),
    )

    def es_comparable_con(
        self,
        comuna: str,
        estrato: int,
        tipo_inmueble: str,
        area_base: float,
    ) -> bool:
        """Verifica si este inmueble cumple los 4 criterios estrictos de RN-03.

        1. Misma comuna (comparación insensible a mayúsculas/espacios).
        2. Mismo estrato socioeconómico.
        3. Mismo tipo de inmueble.
        4. Área dentro del rango de variación de ±15% respecto a `area_base`.
        """
        if self.comuna.strip().lower() != comuna.strip().lower():
            return False
        if self.estrato != estrato:
            return False
        if self.tipo_inmueble.strip().lower() != tipo_inmueble.strip().lower():
            return False

        area_min = area_base * 0.85
        area_max = area_base * 1.15
        return area_min <= self.area <= area_max

    def diferencia_porcentual_oferta(self) -> float:
        """Calcula qué porcentaje está el precio publicado por debajo (+) o por encima (-) del estimado IA."""
        if not self.precio_estimado or self.precio_estimado <= 0:
            return 0.0
        return round(
            ((self.precio_estimado - self.precio_publicado) / self.precio_estimado) * 100.0,
            2,
        )

    def etiqueta_calidad_oferta(self) -> str:
        """Clasifica la oferta comercial comparando el canon publicado frente al estimado por ML."""
        diff = self.diferencia_porcentual_oferta()
        if diff > 10.0:
            return "Excelente precio"
        if diff > 4.0:
            return "Buen precio"
        if diff > -5.0:
            return "Precio justo"
        return "Precio elevado"
