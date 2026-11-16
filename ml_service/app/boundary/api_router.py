import threading
from typing import Dict, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.controls.preprocessing_control import PreprocesamientoControl
from app.controls.training_pipeline_control import ReentrenamientoControl
from app.domain.config import MLServiceConfig
from app.domain.schemas import (
    BatchPredictionRequestSchema,
    InmuebleInputSchema,
    PrediccionOutputSchema,
    ResultadoReentrenamientoSchema,
)
from app.infrastructure.repositories import (
    FileGeoReferenceRepository,
    JoblibModelArtifactRepository,
    PostgresDatasetRepository,
)
from app.services.feature_engineering import FeatureEngineeringService
from app.services.inference_service import ModeloPredictivoService

router = APIRouter(prefix="/api/v1", tags=["Machine Learning Service"])

# ==============================================================================
# CONTENEDOR DE INYECCIÓN DE DEPENDENCIAS (Principio DIP - SOLID)
# ==============================================================================
_config = MLServiceConfig()
_geo_repo = FileGeoReferenceRepository(_config)
_artifact_repo = JoblibModelArtifactRepository(_config)
_dataset_repo = PostgresDatasetRepository(_config)
_feature_service = FeatureEngineeringService(_config)
_preprocessing_control = PreprocesamientoControl(_config, _geo_repo, _feature_service)
_retraining_control = ReentrenamientoControl(
    _config, _dataset_repo, _artifact_repo, _preprocessing_control
)
_inference_service = ModeloPredictivoService(_artifact_repo, _geo_repo, _feature_service)

# Candado de exclusión mutua para impedir reentrenamientos concurrentes entre /retrain y /retrain/sync
_retrain_lock = threading.Lock()

# Estado del último trabajo de reentrenamiento en segundo plano (RNF-08 / RNF-09)
_ultimo_resultado_reentrenamiento: Dict[str, object] = {
    "estado": "INACTIVO",
    "ultimo_reporte": None,
}


def get_inference_service() -> ModeloPredictivoService:
    return _inference_service


def get_retraining_control() -> ReentrenamientoControl:
    return _retraining_control


def precargar_recursos_al_inicio() -> None:
    """
    Precarga el catálogo SITVA y el artefacto .joblib en memoria RAM al arrancar FastAPI
    (evento lifespan), evitando latencia en la primera petición a /predict (RNF-05).
    """
    if _config.sitva_path.exists():
        _geo_repo.obtener_estaciones_sitva()
    if _artifact_repo.existe_artefacto():
        _inference_service.asegurar_modelo_cargado()


def _tarea_reentrenamiento_background(
    retraining_ctrl: ReentrenamientoControl,
    inference_srv: ModeloPredictivoService,
) -> None:
    """
    Worker en segundo plano (Diagrama de Actividades F3 - RNF-08):
    Ejecuta el Template Method sin bloquear las peticiones HTTP de los usuarios.
    Si el nuevo modelo aprueba RN-01, actualiza el modelo en memoria RAM en caliente.
    """
    try:
        reporte = retraining_ctrl.ejecutar_reentrenamiento()
        if reporte.promovido_a_produccion:
            inference_srv.recargar_modelo_en_caliente()
        _ultimo_resultado_reentrenamiento["estado"] = "COMPLETADO"
        _ultimo_resultado_reentrenamiento["ultimo_reporte"] = reporte.model_dump()
    except Exception as exc:
        _ultimo_resultado_reentrenamiento["estado"] = "ERROR"
        _ultimo_resultado_reentrenamiento["ultimo_reporte"] = {"detalle_error": str(exc)}
    finally:
        if _retrain_lock.locked():
            _retrain_lock.release()


# ==============================================================================
# ENDPOINTS HTTP REST DEL SERVICIO DE MACHINE LEARNING
# ==============================================================================
@router.get("/health", summary="Verificar estado del Servicio ML (Liveness & Readiness)")
def health_check(
    inference_srv: ModeloPredictivoService = Depends(get_inference_service),
) -> Dict[str, object]:
    existe = _artifact_repo.existe_artefacto()
    return {
        "status": "ok",
        "modelo_compilado_disponible": existe,
        "modelo_cargado_en_ram": inference_srv.esta_cargado_en_ram(),
        "estado_worker_reentrenamiento": _ultimo_resultado_reentrenamiento["estado"],
    }


@router.get("/metrics", summary="Consultar métricas MAPE del modelo en producción (RF-11)")
def obtener_metricas_modelo(
    inference_srv: ModeloPredictivoService = Depends(get_inference_service),
) -> Dict[str, object]:
    try:
        return {
            "modelo_activo": inference_srv.obtener_metricas_actuales(),
            "historial_ultimo_reentrenamiento": _ultimo_resultado_reentrenamiento,
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/predict",
    response_model=PrediccionOutputSchema,
    summary="Estimar canon de arriendo de un inmueble individual (RF-03, RNF-05)",
)
def predecir_inmueble(
    inmueble: InmuebleInputSchema,
    inference_srv: ModeloPredictivoService = Depends(get_inference_service),
) -> PrediccionOutputSchema:
    try:
        return inference_srv.predecir_individual(inmueble)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/predict/batch",
    response_model=List[PrediccionOutputSchema],
    summary="Estimar canon de arriendo en lote para ordenar por 'Mejor Oferta' (RF-02)",
)
def predecir_lote_inmuebles(
    payload: BatchPredictionRequestSchema,
    inference_srv: ModeloPredictivoService = Depends(get_inference_service),
) -> List[PrediccionOutputSchema]:
    try:
        return inference_srv.predecir_lote(payload.inmuebles)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/retrain",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Iniciar reentrenamiento en segundo plano sin bloquear el servicio (RF-10, RNF-08)",
)
def iniciar_reentrenamiento_asincrono(
    background_tasks: BackgroundTasks,
    retraining_ctrl: ReentrenamientoControl = Depends(get_retraining_control),
    inference_srv: ModeloPredictivoService = Depends(get_inference_service),
) -> Dict[str, str]:
    if not _retrain_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un proceso de reentrenamiento en ejecución.",
        )

    _ultimo_resultado_reentrenamiento["estado"] = "EN_EJECUCION"
    background_tasks.add_task(
        _tarea_reentrenamiento_background, retraining_ctrl, inference_srv
    )
    return {
        "estado": "202 Accepted",
        "mensaje": (
            "El proceso de preprocesamiento (RN-02, RN-06) y reentrenamiento (RN-01) "
            "ha iniciado en segundo plano. Consulte GET /api/v1/metrics para ver el resultado."
        ),
    }


@router.post(
    "/retrain/sync",
    response_model=ResultadoReentrenamientoSchema,
    summary="Ejecutar reentrenamiento sincrónico esperando el reporte final (Pruebas / Admin)",
)
def ejecutar_reentrenamiento_sincronico(
    retraining_ctrl: ReentrenamientoControl = Depends(get_retraining_control),
    inference_srv: ModeloPredictivoService = Depends(get_inference_service),
) -> ResultadoReentrenamientoSchema:
    if not _retrain_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un proceso de reentrenamiento en ejecución.",
        )

    _ultimo_resultado_reentrenamiento["estado"] = "EN_EJECUCION"
    try:
        reporte = retraining_ctrl.ejecutar_reentrenamiento()
        if reporte.promovido_a_produccion:
            inference_srv.recargar_modelo_en_caliente()
        _ultimo_resultado_reentrenamiento["estado"] = "COMPLETADO"
        _ultimo_resultado_reentrenamiento["ultimo_reporte"] = reporte.model_dump()
        return reporte
    except Exception as exc:
        _ultimo_resultado_reentrenamiento["estado"] = "ERROR"
        _ultimo_resultado_reentrenamiento["ultimo_reporte"] = {"detalle_error": str(exc)}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante el reentrenamiento: {exc}",
        ) from exc
    finally:
        if _retrain_lock.locked():
            _retrain_lock.release()
