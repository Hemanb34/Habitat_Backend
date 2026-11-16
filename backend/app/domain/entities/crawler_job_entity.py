"""Entidad ORM de Dominio CrawlerJob (<<entity>>).

Representa la tabla `crawler_jobs` en PostgreSQL donde se registra cada
ejecución de extracción de datos por portal (F1 - RF-08, RNF-09).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base


class CrawlerJob(Base):
    """Entidad persistente <<entity>> mapeada a la tabla `crawler_jobs`."""

    __tablename__ = "crawler_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portal: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    fecha_ejecucion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    dia_etiqueta: Mapped[str] = mapped_column(String(15), nullable=False, default="Hoy")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="SUCCESS")
    registros_extraidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    registros_validos_rn06: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicados_omitidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_segundos: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mensaje_error: Mapped[str | None] = mapped_column(Text, nullable=True)
