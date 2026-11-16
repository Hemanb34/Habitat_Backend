"""Entidad ORM de Dominio ModeloPrediccion (<<entity>>).

Representa la tabla `model_versions` en PostgreSQL donde se registra cada
ciclo de entrenamiento del modelo de Machine Learning y su evaluación frente
a la compuerta de calidad RN-01 (`MAPE <= 16%`).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base


class ModeloPrediccion(Base):
    """Entidad persistente <<entity>> mapeada a la tabla `model_versions`."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    fecha_entrenamiento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    mape_poblado: Mapped[float] = mapped_column(Float, nullable=False)
    mape_otras_comunas: Mapped[float] = mapped_column(Float, nullable=False)
    mape_promedio: Mapped[float] = mapped_column(Float, nullable=False)
    registros_entrenamiento: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    en_produccion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
