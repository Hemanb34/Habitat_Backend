"""Cliente HTTP asíncrono hacia el Microservicio de Machine Learning (Capa Infrastructure).

Implementa `IMLServiceClient` comunicándose con `ml_service` en el puerto 8001
vía `httpx.AsyncClient`. Incluye fallback transparente en memoria hacia
`ModeloPredictivoService` si el contenedor/proceso de `ml_service` no está
levantado por separado durante las pruebas locales.
"""

from __future__ import annotations

import sys

import httpx

from backend.app.domain.config import ML_SERVICE_BASE_URL, PROJECT_ROOT
from backend.app.domain.interfaces.ml_client import IMLServiceClient, MLPredictionResult


class MLServiceClient(IMLServiceClient):
    """Adaptador de infraestructura para consumir el motor predictivo de Habita."""

    def __init__(self, base_url: str = ML_SERVICE_BASE_URL, timeout_sec: float = 2.5) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

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
        """Envía la petición `POST /api/v1/ml/predict` o usa inferencia directa de respaldo."""
        payload = {
            "comuna": comuna,
            "barrio": barrio,
            "tipo_inmueble": tipo_inmueble,
            "area": float(area),
            "habitaciones": int(habitaciones),
            "banos": int(banos),
            "parqueaderos": int(parqueaderos),
            "estrato": int(estrato),
            "estado": "Usado",
            "incluye_administracion": bool(incluye_administracion),
            "amoblado": bool(amoblado),
            "titulo_o_descripcion": f"{tipo_inmueble} en arriendo en {barrio or comuna}, Medellín",
        }

        timeout = httpx.Timeout(connect=0.25, read=self._timeout_sec, write=1.0, pool=0.5)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self._base_url}/api/v1/ml/predict",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return MLPredictionResult(
                    precio_estimado_cop=round(float(data["precio_estimado_cop"]), 0),
                    precio_m2_estimado_cop=round(float(data["precio_m2_estimado_cop"]), 0),
                    modelo_utilizado=str(data["modelo_utilizado"]),
                    version_modelo=str(data["version_modelo"]),
                    mape_validacion_modelo=float(data["mape_validacion_modelo"]),
                )
        except httpx.HTTPError:
            return self._predecir_en_proceso_local(payload)

    @staticmethod
    def _predecir_en_proceso_local(payload: dict[str, object]) -> MLPredictionResult:
        """Respaldo directo usando el artefacto .joblib de `ml_service`."""
        ml_dir = str(PROJECT_ROOT / "ml_service")
        if ml_dir not in sys.path:
            sys.path.insert(0, ml_dir)

        from app.boundary.api_router import get_inference_service  # type: ignore[import-not-found]
        from app.domain.schemas import InmuebleInputSchema  # type: ignore[import-not-found]

        service = get_inference_service()
        schema_in = InmuebleInputSchema(**payload)
        pred = service.predecir_individual(schema_in)
        return MLPredictionResult(
            precio_estimado_cop=round(float(pred.precio_estimado_cop), 0),
            precio_m2_estimado_cop=round(float(pred.precio_m2_estimado_cop), 0),
            modelo_utilizado=str(pred.modelo_utilizado),
            version_modelo=str(pred.version_modelo),
            mape_validacion_modelo=float(pred.mape_validacion_modelo),
        )

    @staticmethod
    def precargar_modelo_respaldo() -> None:
        """Precarga en RAM el artefacto .joblib al iniciar el Backend para cumplir RNF-05 (< 3s)."""
        ml_dir = str(PROJECT_ROOT / "ml_service")
        if ml_dir not in sys.path:
            sys.path.insert(0, ml_dir)
        from app.boundary.api_router import precargar_recursos_al_inicio  # type: ignore[import-not-found]

        precargar_recursos_al_inicio()
