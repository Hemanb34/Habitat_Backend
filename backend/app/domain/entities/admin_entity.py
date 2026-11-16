"""Entidad ORM de Dominio Administrador (<<entity>>).

Representa la tabla `admins` en PostgreSQL y encapsula la regla de negocio RN-05:
- Al acumular 3 intentos fallidos consecutivos de inicio de sesión, la cuenta
  se bloquea temporalmente durante 30 minutos (`LOCKOUT_DURATION_MINUTES`).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.domain.config import (
    LOCKOUT_DURATION_MINUTES,
    MAX_FAILED_LOGIN_ATTEMPTS,
)
from backend.app.infrastructure.database import Base


class Administrador(Base):
    """Entidad persistente <<entity>> mapeada a la tabla `admins`."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(40), nullable=False, default="ADMIN")

    # Estado de protección contra fuerza bruta (RN-05)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ultimo_acceso: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def esta_bloqueado(self, ahora: datetime | None = None) -> bool:
        """Verifica si la cuenta tiene un bloqueo temporal activo según RN-05."""
        if self.bloqueado_hasta is None:
            return False
        ref = ahora or datetime.now(timezone.utc)
        bloqueo = (
            self.bloqueado_hasta
            if self.bloqueado_hasta.tzinfo is not None
            else self.bloqueado_hasta.replace(tzinfo=timezone.utc)
        )
        return ref < bloqueo

    def minutos_restantes_bloqueo(self, ahora: datetime | None = None) -> int:
        """Calcula cuántos minutos faltan para que expire el bloqueo de 30 minutos."""
        if not self.esta_bloqueado(ahora):
            return 0
        ref = ahora or datetime.now(timezone.utc)
        assert self.bloqueado_hasta is not None
        bloqueo = (
            self.bloqueado_hasta
            if self.bloqueado_hasta.tzinfo is not None
            else self.bloqueado_hasta.replace(tzinfo=timezone.utc)
        )
        segundos = max(0.0, (bloqueo - ref).total_seconds())
        return max(1, math.ceil(segundos / 60.0))

    def registrar_intento_fallido_rn05(self, ahora: datetime | None = None) -> bool:
        """Incrementa el contador de fallos y activa el bloqueo de 30 min al 3.er intento (RN-05).

        Retorna True si en este intento se activó el bloqueo de la cuenta.
        """
        ref = ahora or datetime.now(timezone.utc)
        # Si tenía un bloqueo previo ya vencido, reiniciar conteo antes de sumar el nuevo fallo
        if self.bloqueado_hasta is not None and not self.esta_bloqueado(ref):
            self.intentos_fallidos = 0
            self.bloqueado_hasta = None

        self.intentos_fallidos += 1
        if self.intentos_fallidos >= MAX_FAILED_LOGIN_ATTEMPTS:
            self.bloqueado_hasta = ref + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            return True
        return False

    def resetear_intentos(self, ahora: datetime | None = None) -> None:
        """Limpia el contador de fallos y registra la fecha de ingreso exitoso."""
        ref = ahora or datetime.now(timezone.utc)
        self.intentos_fallidos = 0
        self.bloqueado_hasta = None
        self.ultimo_acceso = ref
