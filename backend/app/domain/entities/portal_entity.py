"""Entidad ORM de Dominio Portal (<<entity>>).

Representa la tabla `portals` en PostgreSQL para gestionar los portales
inmobiliarios soportados por `CrawlerFactory` (RNF-07):
Finca Raíz, Metrocuadrado y CienCuadras.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base


class Portal(Base):
    """Entidad persistente <<entity>> mapeada a la tabla `portals`."""

    __tablename__ = "portals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clave: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    url_base: Mapped[str] = mapped_column(String(120), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultima_ejecucion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ultimo_estado: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
