import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional
import geopandas as gpd
import joblib
import pandas as pd
from sqlalchemy import create_engine, text

from app.domain.config import MLServiceConfig


# ==============================================================================
# 1. INTERFACES ABSTRACTAS (Contratos segregados - Principios ISP y DIP)
# ==============================================================================
class IDatasetRepository(ABC):
    """Contrato para obtener el dataset crudo de inmuebles para entrenamiento."""

    @abstractmethod
    def cargar_datos_entrenamiento(self) -> pd.DataFrame:
        pass


class IGeoReferenceRepository(ABC):
    """Contrato para obtener los catálogos geográficos estáticos de Medellín."""

    @abstractmethod
    def obtener_mapa_comunas(self) -> gpd.GeoDataFrame:
        pass

    @abstractmethod
    def obtener_estaciones_sitva(self) -> pd.DataFrame:
        pass


class IModelArtifactRepository(ABC):
    """Contrato para persistir y recuperar el modelo compilado de producción."""

    @abstractmethod
    def guardar_artefacto(self, artefacto: Dict[str, Any]) -> Path:
        pass

    @abstractmethod
    def cargar_artefacto(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def existe_artefacto(self) -> bool:
        pass


# ==============================================================================
# 2. IMPLEMENTACIONES CONCRETAS (Infraestructura Basada en PostgreSQL / Archivos / Joblib)
# ==============================================================================
class PostgresDatasetRepository(IDatasetRepository):
    """
    Implementación concreta de producción que extrae el dataset de entrenamiento
    directamente desde la tabla `properties` en PostgreSQL (`habita_db`).

    Cumple el Principio Abierto/Cerrado (OCP) e Inversión de Dependencias (DIP):
    sustituye a `CsvDatasetRepository` sin modificar ni una sola línea de
    `PreprocesamientoControl` ni del Patrón GoF Template Method en `ReentrenamientoControl`.
    """

    _QUERY_ENTRENAMIENTO = text(
        """
        SELECT
            portal,
            title,
            tipo_inmueble,
            area,
            estrato,
            comuna,
            barrio,
            habitaciones,
            banos,
            parqueaderos,
            estado,
            precio_publicado,
            valor_administracion,
            incluye_administracion,
            amoblado,
            imagen_url,
            url_origen,
            latitud,
            longitud,
            antiguedad
        FROM properties
        WHERE url_origen IS NOT NULL
          AND precio_publicado IS NOT NULL
          AND area IS NOT NULL
        ORDER BY id ASC
        """
    )

    def __init__(self, config: MLServiceConfig):
        self._config = config
        self._engine = create_engine(
            self._config.database_url,
            pool_pre_ping=True,
        )

    def cargar_datos_entrenamiento(self) -> pd.DataFrame:
        with self._engine.connect() as conn:
            df = pd.read_sql_query(self._QUERY_ENTRENAMIENTO, conn)

        if df.empty:
            raise ValueError(
                "La tabla 'properties' en PostgreSQL (habita_db) está vacía. "
                "Ejecute primero los crawlers antes de iniciar el entrenamiento ML."
            )

        # Normalizar el identificador de portal ('Finca Raíz' -> 'fincaraiz', etc.)
        # para mantener simetría con ModeloPredictivoService (inferencia) y OneHotEncoder
        df["portal"] = (
            df["portal"]
            .fillna("fincaraiz")
            .astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "", regex=False)
            .str.replace("í", "i", regex=False)
        )
        df["estado"] = df["estado"].fillna("Usado").astype(str)
        df["incluye_administracion"] = df["incluye_administracion"].fillna(False).astype(int)
        df["amoblado"] = df["amoblado"].fillna(False).astype(int)
        return df


class CsvDatasetRepository(IDatasetRepository):
    """
    Implementación concreta que carga y unifica los CSV extraídos de los portales
    ubicados en 'ml_service/data/raw/'.
    Cuando el Backend conecte PostgreSQL, se podrá crear 'SqlDatasetRepository(IDatasetRepository)'
    sin modificar ni una línea del Template Method de entrenamiento (Principio OCP).
    """

    def __init__(self, config: MLServiceConfig):
        self._config = config
        self._archivos_portales = {
            "ciencuadras": "medellin_arriendo_ciencuadras.csv",
            "fincaraiz": "medellin_arriendo_fincaraiz.csv",
            "metrocuadrado": "medellin_arriendo_metrocuadrado.csv",
        }

    def cargar_datos_entrenamiento(self) -> pd.DataFrame:
        dataframes = []
        for nombre_portal, nombre_archivo in self._archivos_portales.items():
            ruta_csv = self._config.raw_data_dir / nombre_archivo
            if not ruta_csv.exists():
                raise FileNotFoundError(
                    f"No se encontró el archivo de entrenamiento requerido: {ruta_csv}"
                )
            df_portal = pd.read_csv(ruta_csv, sep=",", quotechar='"')
            df_portal["portal"] = nombre_portal
            dataframes.append(df_portal)

        return pd.concat(dataframes, axis=0, ignore_index=True)


class FileGeoReferenceRepository(IGeoReferenceRepository):
    """
    Carga los archivos estáticos de referencia ('comunas_y_corregimientos_.geojson'
    y 'estaciones_sitva_medellin.csv') desde 'ml_service/data/reference/' y los
    mantiene en caché en memoria RAM para garantizar latencia cero en inferencia (RNF-05).
    """

    def __init__(self, config: MLServiceConfig):
        self._config = config
        self._mapa_cache: Optional[gpd.GeoDataFrame] = None
        self._sitva_cache: Optional[pd.DataFrame] = None

    def obtener_mapa_comunas(self) -> gpd.GeoDataFrame:
        if self._mapa_cache is None:
            if not self._config.geojson_path.exists():
                raise FileNotFoundError(
                    f"No se encontró el archivo GeoJSON en: {self._config.geojson_path}"
                )
            mapa = gpd.read_file(self._config.geojson_path)
            if mapa.crs != "EPSG:4326":
                mapa = mapa.to_crs("EPSG:4326")
            self._mapa_cache = mapa
        return self._mapa_cache

    def obtener_estaciones_sitva(self) -> pd.DataFrame:
        if self._sitva_cache is None:
            if not self._config.sitva_path.exists():
                raise FileNotFoundError(
                    f"No se encontró el catálogo SITVA en: {self._config.sitva_path}"
                )
            self._sitva_cache = pd.read_csv(self._config.sitva_path, sep=",")
        return self._sitva_cache


class JoblibModelArtifactRepository(IModelArtifactRepository):
    """
    Gestiona la lectura y escritura atómica del diccionario de artefactos
    entrenados ('modelos_habita.joblib') dentro de 'ml_service/artifacts/'.
    Incluye compresión LZ4/Zlib nivel 3, escritura en archivo temporal (.tmp)
    y conservación de respaldo previo ('modelos_habita.prev.joblib') para Rollback.
    """

    def __init__(self, config: MLServiceConfig):
        self._config = config

    def existe_artefacto(self) -> bool:
        return self._config.model_artifact_path.exists()

    def guardar_artefacto(self, artefacto: Dict[str, Any]) -> Path:
        self._config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        ruta_final = self._config.model_artifact_path
        ruta_respaldo = self._config.model_backup_path
        ruta_temporal = ruta_final.with_suffix(".joblib.tmp")

        # 1. Escribir primero en un archivo temporal comprimido (evita corrupción si hay lectura concurrente)
        joblib.dump(artefacto, ruta_temporal, compress=3)

        # 2. Si ya existe un modelo en producción, conservar una copia de respaldo (.prev.joblib) para Rollback
        if ruta_final.exists():
            shutil.copy2(ruta_final, ruta_respaldo)

        # 3. Reemplazo atómico del sistema operativo (POSIX / Windows MoveFileEx)
        os.replace(ruta_temporal, ruta_final)
        return ruta_final

    def cargar_artefacto(self) -> Dict[str, Any]:
        if not self.existe_artefacto():
            raise FileNotFoundError(
                f"Aún no existe un modelo compilado en producción en: {self._config.model_artifact_path}. "
                "Ejecute primero el proceso de entrenamiento/reentrenamiento."
            )
        return joblib.load(self._config.model_artifact_path)
