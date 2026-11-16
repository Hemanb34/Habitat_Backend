"""Implementación SQLAlchemy del repositorio de Administradores (Capa Infrastructure).

Persiste el estado de intentos fallidos y bloqueo de 30 minutos (RN-05) en la
tabla `admins`, así como los eventos de seguridad en `audit_logs` (RNF-09).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.domain.entities.admin_entity import Administrador
from backend.app.domain.entities.audit_log_entity import LogAuditoria
from backend.app.domain.interfaces.repositories import IAdminRepository


class AdminRepository(IAdminRepository):
    """Repositorio concreto SQLAlchemy para `Administrador` y auditoría de acceso."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def obtener_por_username(self, username: str) -> Administrador | None:
        """Busca un administrador por su `username` de forma insensible a mayúsculas."""
        stmt = select(Administrador).where(
            func.lower(Administrador.username) == username.strip().lower()
        )
        return self._db.execute(stmt).scalar_one_or_none()

    def guardar(self, admin: Administrador) -> Administrador:
        """Guarda y confirma en PostgreSQL el estado del administrador."""
        self._db.add(admin)
        self._db.commit()
        self._db.refresh(admin)
        return admin

    def registrar_evento_auditoria(
        self,
        accion: str,
        detalle: str,
        estado: str = "ok",
        usuario: str = "admin",
    ) -> LogAuditoria:
        """Inserta un registro inmutable en la tabla `audit_logs` (RNF-09)."""
        evento = LogAuditoria(
            accion=accion,
            detalle=detalle,
            estado=estado,
            usuario=usuario,
        )
        self._db.add(evento)
        self._db.commit()
        self._db.refresh(evento)
        return evento
