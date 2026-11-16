"""Implementación SQLAlchemy del repositorio de Auditoría, Jobs y Versiones ML (Capa Infrastructure).

Gestiona la persistencia en PostgreSQL de las entidades:
- `Portal` (`portals`)
- `CrawlerJob` (`crawler_jobs`)
- `ModeloPrediccion` (`model_versions`)
- `LogAuditoria` (`audit_logs` - RNF-09)
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.domain.entities.audit_log_entity import LogAuditoria
from backend.app.domain.entities.crawler_job_entity import CrawlerJob
from backend.app.domain.entities.model_version_entity import ModeloPrediccion
from backend.app.domain.entities.portal_entity import Portal
from backend.app.domain.interfaces.repositories import IAuditRepository


class AuditRepository(IAuditRepository):
    """Repositorio concreto SQLAlchemy para telemetría administrativa y RNF-09."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def listar_portales(self) -> list[Portal]:
        stmt = select(Portal).order_by(Portal.id.asc())
        return list(self._db.execute(stmt).scalars().all())

    def actualizar_estado_portal(
        self,
        clave_o_nombre: str,
        estado: str = "idle",
    ) -> None:
        stmt = select(Portal).where(
            (Portal.clave == clave_o_nombre.lower())
            | (Portal.nombre == clave_o_nombre)
        )
        portal = self._db.execute(stmt).scalar_one_or_none()
        if portal is not None:
            portal.ultimo_estado = estado
            portal.ultima_ejecucion = datetime.now(timezone.utc)
            self._db.add(portal)
            self._db.commit()

    def registrar_crawler_job(self, job: CrawlerJob) -> CrawlerJob:
        self._db.add(job)
        self._db.commit()
        self._db.refresh(job)
        return job

    def listar_ultimos_jobs(self, limit: int = 7) -> list[CrawlerJob]:
        stmt = (
            select(CrawlerJob)
            .order_by(CrawlerJob.id.desc())
            .limit(limit)
        )
        items = list(self._db.execute(stmt).scalars().all())
        items.reverse()
        return items

    def obtener_modelo_en_produccion(self) -> ModeloPrediccion | None:
        stmt = (
            select(ModeloPrediccion)
            .where(ModeloPrediccion.en_produccion.is_(True))
            .order_by(ModeloPrediccion.id.desc())
            .limit(1)
        )
        return self._db.execute(stmt).scalar_one_or_none()

    def listar_historial_modelos(self, limit: int = 10) -> list[ModeloPrediccion]:
        stmt = (
            select(ModeloPrediccion)
            .order_by(ModeloPrediccion.id.desc())
            .limit(limit)
        )
        items = list(self._db.execute(stmt).scalars().all())
        items.reverse()
        return items

    def registrar_version_modelo(self, version: ModeloPrediccion) -> ModeloPrediccion:
        if version.en_produccion:
            self._db.execute(
                update(ModeloPrediccion).values(en_produccion=False)
            )
        self._db.add(version)
        self._db.commit()
        self._db.refresh(version)
        return version

    def listar_logs_auditoria(self, limit: int = 12) -> list[LogAuditoria]:
        stmt = (
            select(LogAuditoria)
            .order_by(LogAuditoria.id.desc())
            .limit(limit)
        )
        return list(self._db.execute(stmt).scalars().all())

    def registrar_log(
        self,
        accion: str,
        detalle: str,
        estado: str = "ok",
        usuario: str = "admin",
    ) -> LogAuditoria:
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
