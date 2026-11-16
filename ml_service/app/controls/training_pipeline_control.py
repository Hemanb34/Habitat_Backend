from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Tuple
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor, make_column_transformer
from sklearn.ensemble import ExtraTreesRegressor, VotingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler, TargetEncoder
from xgboost import XGBRegressor

from app.controls.preprocessing_control import PreprocesamientoControl
from app.domain.config import MLServiceConfig
from app.domain.schemas import ResultadoReentrenamientoSchema
from app.infrastructure.repositories import IDatasetRepository, IModelArtifactRepository
from app.infrastructure.spatial_transformers import SpatialKNNFeatures
from app.services.feature_engineering import FeatureEngineeringService


@dataclass
class ResultadoSubModelo:
    """Resultado devuelto por cada ejecución concreta del Template Method."""
    nombre_regimen: str
    pipeline_entrenado: TransformedTargetRegressor
    mape_validacion: float
    aprobado_rn01: bool


# ==============================================================================
# PATRÓN GOF: TEMPLATE METHOD (FICHA 4 - Preparar Datos F2 y Reentrenar F3)
# ==============================================================================
class BaseModelTrainingPipeline(ABC):
    """
    AbstractClass del Patrón Template Method.
    Define el esqueleto algorítmico invariable de entrenamiento y validación
    garantizando el cumplimiento forzoso de RN-02 (No Data Leakage) y RN-01 (Umbral MAPE <= 16%).
    """

    def __init__(self, config: MLServiceConfig):
        self._config = config

    def ejecutar_pipeline_completo(self, df_segmento: pd.DataFrame) -> ResultadoSubModelo:
        """
        TEMPLATE METHOD (Método Plantilla Inmutable):
        Fija el orden estricto de los pasos metodológicos de Machine Learning.
        """
        # Paso 1: Separar matriz de características (X) y variable objetivo (y)
        X, y = self._seleccionar_variables(df_segmento)

        # Paso 2 (RN-02): Partición estricta 80% Train / 20% Validación ANTES de cualquier escalado/codificación
        X_train, X_val, y_train, y_val = self._particionar_80_20(X, y)

        # Paso 3: Construir el preprocesador estadístico y el estimador de ensamble
        preprocesador = self._construir_preprocesador()
        estimador = self._construir_estimador()

        # Paso 4 (RN-02): Ensamblar y ajustar (.fit) EXCLUSIVAMENTE sobre el 80% de entrenamiento (X_train, y_train)
        modelo_entrenado = self._ajustar_sin_fuga_de_datos(
            preprocesador, estimador, X_train, y_train
        )

        # Paso 5: Evaluar sobre el 20% de validación nunca visto (X_val, y_val)
        mape_calculado = self._evaluar_mape(modelo_entrenado, X_val, y_val)

        # Paso 6 (RN-01 / RNF-02): Evaluar compuerta de calidad (MAPE <= 16%)
        aprobado = mape_calculado <= self._config.max_allowed_mape

        return ResultadoSubModelo(
            nombre_regimen=self.nombre_regimen,
            pipeline_entrenado=modelo_entrenado,
            mape_validacion=mape_calculado,
            aprobado_rn01=aprobado,
        )

    def _ajustar_sin_fuga_de_datos(
        self,
        preprocesador: ColumnTransformer,
        estimador: Any,
        X_train: pd.DataFrame,
        y_train: pd.Series,
    ) -> TransformedTargetRegressor:
        """
        Paso invariable que encapsula SpatialKNNFeatures + ColumnTransformer + Estimador
        dentro de TransformedTargetRegressor(log1p/expm1) y ajusta solo con X_train.
        Tras ajustar, configura n_jobs=1 en los estimadores ajustados para eliminar
        la sobrecarga de creación de hilos durante la inferencia en tiempo real (RNF-05).
        """
        pipeline_interno = make_pipeline(
            SpatialKNNFeatures(n_neighbors=20, n_jobs=self._config.n_jobs_training),
            preprocesador,
            estimador,
        )
        pipeline_completo = TransformedTargetRegressor(
            regressor=pipeline_interno,
            func=np.log1p,
            inverse_func=np.expm1,
        )
        pipeline_completo.fit(X_train, y_train)
        self._optimizar_hilos_para_inferencia(pipeline_completo)
        return pipeline_completo

    @staticmethod
    def _optimizar_hilos_para_inferencia(modelo: TransformedTargetRegressor) -> None:
        """
        Fija n_jobs=1 en los estimadores ya entrenados dentro de regressor_
        para que las llamadas a predict() desde la API no creen pools de hilos por petición.
        """
        pipe_ajustado = modelo.regressor_
        knn_step = pipe_ajustado.named_steps.get("spatialknnfeatures")
        if knn_step is not None:
            knn_step.n_jobs = 1
            if hasattr(knn_step, "knn_geo_"):
                knn_step.knn_geo_.set_params(n_jobs=1)
            if hasattr(knn_step, "knn_sim_"):
                knn_step.knn_sim_.set_params(n_jobs=1)

        voting_step = pipe_ajustado.named_steps.get("votingregressor")
        if voting_step is not None and hasattr(voting_step, "estimators_"):
            for sub_est in voting_step.estimators_:
                sub_est.set_params(n_jobs=1)

    def _crear_ensamble_regresion(self, n_estimators_xgb1: int) -> VotingRegressor:
        """
        Fábrica centralizada del ensamble VotingRegressor (2 XGBoost + ExtraTrees podado).
        - Se limita n_jobs a config.n_jobs_training para no saturar todos los núcleos de la CPU.
        - En ExtraTreesRegressor se ajusta max_depth=16, min_samples_leaf=3 y n_estimators=160,
          reduciendo el tamaño del artefacto de ~853 MB a ~64 MB sin degradar el MAPE.
        """
        n_jobs = self._config.n_jobs_training
        xgb_1 = XGBRegressor(
            objective="reg:absoluteerror", tree_method="hist",
            n_estimators=n_estimators_xgb1, learning_rate=0.025, max_depth=10,
            min_child_weight=2, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0, random_state=20, n_jobs=n_jobs,
        )
        xgb_2 = XGBRegressor(
            objective="reg:absoluteerror", tree_method="hist",
            n_estimators=850, learning_rate=0.03, max_depth=8,
            min_child_weight=3, subsample=0.85, colsample_bytree=0.75,
            reg_alpha=0.2, reg_lambda=1.5, random_state=42, n_jobs=n_jobs,
        )
        et = ExtraTreesRegressor(
            n_estimators=160, max_depth=16, min_samples_leaf=3, random_state=20, n_jobs=n_jobs
        )
        return VotingRegressor(
            estimators=[("xgb1", xgb_1), ("xgb2", xgb_2), ("et", et)],
            weights=[0.45, 0.35, 0.20],
        )

    @staticmethod
    def _evaluar_mape(
        modelo: TransformedTargetRegressor, X_val: pd.DataFrame, y_val: pd.Series
    ) -> float:
        """Evalúa el MAPE manteniendo el orden correcto (y_true, y_pred)."""
        predicciones = modelo.predict(X_val)
        return float(mean_absolute_percentage_error(y_val, predicciones))

    # --- Operaciones Primitivas Abstractas (Implementadas por las Subclases) ---
    @property
    @abstractmethod
    def nombre_regimen(self) -> str:
        pass

    @abstractmethod
    def _seleccionar_variables(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.Series]:
        pass

    @abstractmethod
    def _particionar_80_20(
        self, X: pd.DataFrame, y: pd.Series
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        pass

    @abstractmethod
    def _construir_preprocesador(self) -> ColumnTransformer:
        pass

    @abstractmethod
    def _construir_estimador(self) -> Any:
        pass


# ==============================================================================
# SUBCLASE CONCRETA 1: PIPELINE DE ENTRENAMIENTO PARA EL POBLADO
# ==============================================================================
class PobladoTrainingPipeline(BaseModelTrainingPipeline):
    """ConcreteClass 1 del Template Method: Especializada en la Comuna 14 (El Poblado)."""

    @property
    def nombre_regimen(self) -> str:
        return "Modelo El Poblado"

    def _seleccionar_variables(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.Series]:
        cols_features: List[str] = FeatureEngineeringService.COLUMNAS_NUMERICAS_BASE + [
            "estrato", "tipo_inmueble", "estado", "incluye_administracion",
            "amoblado", "barrio", "portal",
        ]
        return df[cols_features], df["precio_publicado"]

    def _particionar_80_20(
        self, X: pd.DataFrame, y: pd.Series
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        return train_test_split(
            X, y,
            test_size=self._config.test_size,
            random_state=self._config.random_state_split,
        )

    def _construir_preprocesador(self) -> ColumnTransformer:
        return make_column_transformer(
            (StandardScaler(), FeatureEngineeringService.COLUMNAS_NUMERICAS_TOTALES),
            (OneHotEncoder(handle_unknown="ignore", drop="first", sparse_output=False), ["tipo_inmueble", "portal"]),
            (TargetEncoder(cv=5, smooth="auto", random_state=42), ["barrio"]),
            (OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["estrato"]),
            (OrdinalEncoder(categories=[["Usado", "Nuevo"]], handle_unknown="use_encoded_value", unknown_value=-1), ["estado"]),
            (OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["incluye_administracion", "amoblado"]),
        )

    def _construir_estimador(self) -> Any:
        return self._crear_ensamble_regresion(n_estimators_xgb1=950)


# ==============================================================================
# SUBCLASE CONCRETA 2: PIPELINE DE ENTRENAMIENTO PARA OTRAS COMUNAS
# ==============================================================================
class OtrasComunasTrainingPipeline(BaseModelTrainingPipeline):
    """ConcreteClass 2 del Template Method: Especializada en el resto de comunas de Medellín."""

    @property
    def nombre_regimen(self) -> str:
        return "Modelo Otras Comunas"

    def _seleccionar_variables(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.Series]:
        cols_features: List[str] = (
            ["comuna"]
            + FeatureEngineeringService.COLUMNAS_NUMERICAS_BASE
            + [
                "estrato", "tipo_inmueble", "estado", "incluye_administracion",
                "amoblado", "barrio", "portal",
            ]
        )
        return df[cols_features], df["precio_publicado"]

    def _particionar_80_20(
        self, X: pd.DataFrame, y: pd.Series
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        return train_test_split(
            X, y,
            test_size=self._config.test_size,
            random_state=self._config.random_state_split,
            stratify=X["comuna"],
        )

    def _construir_preprocesador(self) -> ColumnTransformer:
        return make_column_transformer(
            (StandardScaler(), FeatureEngineeringService.COLUMNAS_NUMERICAS_TOTALES),
            (OneHotEncoder(handle_unknown="ignore", drop="first", sparse_output=False), ["comuna", "tipo_inmueble", "portal"]),
            (TargetEncoder(cv=5, smooth="auto", random_state=42), ["barrio"]),
            (OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["estrato"]),
            (OrdinalEncoder(categories=[["Usado", "Nuevo"]], handle_unknown="use_encoded_value", unknown_value=-1), ["estado"]),
            (OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["incluye_administracion", "amoblado"]),
        )

    def _construir_estimador(self) -> Any:
        return self._crear_ensamble_regresion(n_estimators_xgb1=1000)


# ==============================================================================
# CONTROLADOR DE ORQUESTACIÓN: ReentrenamientoControl (Nivel 4 C4)
# ==============================================================================
class ReentrenamientoControl:
    """
    Controlador <<control>> que coordina el ciclo completo de reentrenamiento (RF-10):
    1. Extrae los datos crudos desde IDatasetRepository.
    2. Ejecuta PreprocesamientoControl (RF-09, RN-06).
    3. Ejecuta el Template Method para El Poblado y Otras Comunas (RN-02).
    4. Valida la Compuerta de Calidad RN-01 (MAPE <= 16%):
       - Si ambos modelos cumplen, promueve el nuevo artefacto a producción.
       - Si alguno falla, aborta el despliegue protegiendo el modelo vigente.
    """

    def __init__(
        self,
        config: MLServiceConfig,
        dataset_repo: IDatasetRepository,
        artifact_repo: IModelArtifactRepository,
        preprocessing_control: PreprocesamientoControl,
    ):
        self._config = config
        self._dataset_repo = dataset_repo
        self._artifact_repo = artifact_repo
        self._preprocessing_control = preprocessing_control
        self._pipeline_poblado = PobladoTrainingPipeline(config)
        self._pipeline_comunas = OtrasComunasTrainingPipeline(config)

    def ejecutar_reentrenamiento(self) -> ResultadoReentrenamientoSchema:
        # 1. Cargar datos crudos
        df_crudo = self._dataset_repo.cargar_datos_entrenamiento()

        # 2. Limpieza y preparación de dominio
        datos_prep = self._preprocessing_control.ejecutar_limpieza_y_preparacion(df_crudo)

        # 3. Ejecutar Template Method en ambos segmentos
        res_poblado = self._pipeline_poblado.ejecutar_pipeline_completo(datos_prep.df_poblado)
        res_comunas = self._pipeline_comunas.ejecutar_pipeline_completo(datos_prep.df_otras_comunas)

        version_actual = datetime.now().strftime("v%Y%m%d_%H%M%S")
        umbral = self._config.max_allowed_mape

        # 4. Compuerta de Calidad Estricta RN-01 y RNF-02 (MAPE <= 16%)
        if res_poblado.aprobado_rn01 and res_comunas.aprobado_rn01:
            artefacto_produccion = {
                "version": version_actual,
                "fecha_entrenamiento": datetime.now().isoformat(),
                "pipeline_poblado": res_poblado.pipeline_entrenado,
                "pipeline_comunas": res_comunas.pipeline_entrenado,
                "centroides_barrio": datos_prep.centroides_barrio,
                "centroides_comuna": datos_prep.centroides_comuna,
                "comunas_validas_modelo": datos_prep.comunas_validas,
                "mape_poblado": res_poblado.mape_validacion,
                "mape_comunas": res_comunas.mape_validacion,
            }
            ruta_guardada = self._artifact_repo.guardar_artefacto(artefacto_produccion)
            return ResultadoReentrenamientoSchema(
                exito=True,
                promovido_a_produccion=True,
                version_modelo=version_actual,
                mape_poblado=round(res_poblado.mape_validacion, 4),
                mape_otras_comunas=round(res_comunas.mape_validacion, 4),
                umbral_rn01_aplicado=umbral,
                total_registros_entrenamiento=datos_prep.total_registros_limpios,
                mensaje=(
                    f"Modelo {version_actual} promovido exitosamente a producción en {ruta_guardada}. "
                    f"MAPE El Poblado: {res_poblado.mape_validacion * 100:.2f}%, "
                    f"MAPE Otras Comunas: {res_comunas.mape_validacion * 100:.2f}% (Umbral <= {umbral * 100:.0f}%)."
                ),
            )

        # Si supera el 16% (RN-01), se aborta la promoción y NO se toca el archivo .joblib en producción
        return ResultadoReentrenamientoSchema(
            exito=False,
            promovido_a_produccion=False,
            version_modelo=version_actual,
            mape_poblado=round(res_poblado.mape_validacion, 4),
            mape_otras_comunas=round(res_comunas.mape_validacion, 4),
            umbral_rn01_aplicado=umbral,
            total_registros_entrenamiento=datos_prep.total_registros_limpios,
            mensaje=(
                f"Despliegue ABORTADO por Regla de Negocio RN-01: El margen de error supera el umbral "
                f"permitido de {umbral * 100:.0f}% (El Poblado: {res_poblado.mape_validacion * 100:.2f}%, "
                f"Otras Comunas: {res_comunas.mape_validacion * 100:.2f}%). Se mantiene el modelo anterior."
            ),
        )
