"""Contratos abstractos de Repositorios (Principios SOLID DIP e ISP).

Los Controladores (<<control>>) dependen de estas abstracciones y no de
la implementación concreta de SQLAlchemy en la capa de infraestructura.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from backend.app.domain.entities.admin_entity import Administrador
from backend.app.domain.entities.audit_log_entity import LogAuditoria
from backend.app.domain.entities.crawler_job_entity import CrawlerJob
from backend.app.domain.entities.model_version_entity import ModeloPrediccion
from backend.app.domain.entities.portal_entity import Portal
from backend.app.domain.entities.property_entity import Inmueble
from backend.app.domain.schemas.property_schemas import OrdenCatalogo


class IPropertyRepository(ABC):
    """Contrato de acceso a datos para la entidad Inmueble."""

    @abstractmethod
    def listar_catalogo(
        self,
        comuna: str | None = None,
        tipo_inmueble: str | None = None,
        ordenar_por: OrdenCatalogo = "mejor-oferta",
        limit: int = 60,
        offset: int = 0,
    ) -> tuple[list[Inmueble], int]:
        """Retorna la lista de inmuebles filtrados/ordenados y el conteo total."""

    @abstractmethod
    def obtener_filtros_disponibles(self) -> tuple[list[str], list[str]]:
        """Retorna las comunas y tipos de inmueble únicos disponibles en la BD."""

    @abstractmethod
    def buscar_similares_rn03(
        self,
        comuna: str,
        estrato: int,
        tipo_inmueble: str,
        area_base: float,
        limit: int = 10,
    ) -> Sequence[Inmueble]:
        """Busca inmuebles competidores aplicando los 4 criterios de RN-03."""


class IAdminRepository(ABC):
    """Contrato de acceso a datos para la entidad Administrador y eventos de seguridad."""

    @abstractmethod
    def obtener_por_username(self, username: str) -> Administrador | None:
        """Busca un administrador por su nombre de usuario."""

    @abstractmethod
    def guardar(self, admin: Administrador) -> Administrador:
        """Persiste los cambios de estado del administrador (intentos, bloqueo RN-05)."""

    @abstractmethod
    def registrar_evento_auditoria(
        self,
        accion: str,
        detalle: str,
        estado: str = "ok",
        usuario: str = "admin",
    ) -> LogAuditoria:
        """Registra un evento inmutable en la tabla `audit_logs` (RNF-09)."""


class IAuditRepository(ABC):
    """Contrato de acceso a datos para telemetría de portales, jobs, modelos y auditoría (RNF-09)."""

    @abstractmethod
    def listar_portales(self) -> list[Portal]:
        """Retorna los 3 portales configurados en el ecosistema."""

    @abstractmethod
    def registrar_crawler_job(self, job: CrawlerJob) -> CrawlerJob:
        """Persiste el reporte de una ejecución de crawler."""

    @abstractmethod
    def listar_ultimos_jobs(self, limit: int = 7) -> list[CrawlerJob]:
        """Retorna las últimas ejecuciones de extracción para la gráfica del dashboard."""

    @abstractmethod
    def obtener_modelo_en_produccion(self) -> ModeloPrediccion | None:
        """Retorna la versión activa del modelo predictivo en producción."""

    @abstractmethod
    def listar_historial_modelos(self, limit: int = 10) -> list[ModeloPrediccion]:
        """Retorna las últimas versiones entrenadas para la gráfica de evolución del MAPE."""

    @abstractmethod
    def registrar_version_modelo(self, version: ModeloPrediccion) -> ModeloPrediccion:
        """Guarda una nueva versión evaluada del modelo predictivo."""

    @abstractmethod
    def listar_logs_auditoria(self, limit: int = 12) -> list[LogAuditoria]:
        """Retorna los eventos más recientes de `audit_logs` (RNF-09)."""
