"""Entidad ORM de Dominio LogAuditoria (<<entity>>).

Representa la tabla `audit_logs` en PostgreSQL para cumplir con RNF-09
(Trazabilidad y Auditoría Inmutable de ejecuciones de crawlers,
reentrenamientos ML y eventos de seguridad administrativa).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.database import Base


class LogAuditoria(Base):
    """Entidad persistente <<entity>> mapeada a la tabla `audit_logs` (RNF-09)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    accion: Mapped[str] = mapped_column(String(120), nullable=False)
    detalle: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ok",
        doc="Estado visual para el dashboard: ok | warn | error",
    )
    usuario: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")
