"""Contrato abstracto para el cliente del Microservicio de Machine Learning (SOLID DIP).

Permite que `PropertyValuationFacade` (Patrón GoF Facade) solicite predicciones
sin acoplarse al protocolo de transporte (HTTP httpx o inferencia local).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MLPredictionResult:
    """Resultado tipado de una predicción devuelta por el servicio de ML."""

    precio_estimado_cop: float
    precio_m2_estimado_cop: float
    modelo_utilizado: str
    version_modelo: str
    mape_validacion_modelo: float


class IMLServiceClient(ABC):
    """Interfaz <<interface>> para comunicación con el motor predictivo."""

    @abstractmethod
    async def predecir_precio(
        self,
        comuna: str,
        tipo_inmueble: str,
        area: float,
        habitaciones: int,
        banos: int,
        parqueaderos: int,
        estrato: int,
        barrio: str | None = None,
        amoblado: bool = False,
        incluye_administracion: bool = False,
    ) -> MLPredictionResult:
        """Solicita de forma asíncrona la estimación del canon mensual en COP."""
