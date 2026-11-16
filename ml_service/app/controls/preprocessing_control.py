from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import geopandas as gpd
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from app.domain.config import DICCIONARIO_RESCATE_BARRIOS, MLServiceConfig
from app.infrastructure.repositories import IGeoReferenceRepository
from app.services.feature_engineering import FeatureEngineeringService


@dataclass
class DatasetPreprocesado:
    """Contenedor tipado con el resultado del PreprocesamientoControl."""
    df_poblado: pd.DataFrame
    df_otras_comunas: pd.DataFrame
    centroides_barrio: Dict[str, Dict[str, float]]
    centroides_comuna: Dict[str, Dict[str, float]]
    comunas_validas: list[str]
    total_registros_limpios: int


class PreprocesamientoControl:
    """
    Controlador <<control>> encargado de la limpieza de dominio y enriquecimiento
    previo al particionamiento de entrenamiento:
    1. Aplica RN-06 (obligatoriedad de url_origen).
    2. Ejecuta Geocodificación Inversa (Point-in-Polygon) con el GeoJSON oficial.
    3. Rescata anuncios con GPS falso mediante Fuzzy Matching e imputa sus centroides reales.
    4. Elimina duplicados cross-portal y filtra outliers por IQR (P25-P75).
    """

    def __init__(
        self,
        config: MLServiceConfig,
        geo_repo: IGeoReferenceRepository,
        feature_service: FeatureEngineeringService,
    ):
        self._config = config
        self._geo_repo = geo_repo
        self._feature_service = feature_service

    def ejecutar_limpieza_y_preparacion(self, df_crudo: pd.DataFrame) -> DatasetPreprocesado:
        df = df_crudo.copy()

        # 1. Cumplimiento estricto de RN-06: Descartar registros sin URL original o con nulos críticos
        if "url_origen" in df.columns:
            df["url_origen"] = df["url_origen"].astype(str).str.strip()
            df = df[df["url_origen"].notna() & (df["url_origen"] != "") & (df["url_origen"] != "nan")].copy()

        df = df.dropna(
            subset=["area", "estado", "latitud", "longitud", "precio_publicado"]
        ).copy()

        # 2. Geocodificación Inversa (Spatial Join Point-in-Polygon)
        df = self._asignar_comuna_geografica(df)

        # 3. Reglas de rango físico de negocio y exclusión de precios comodín
        df = self._filtrar_rangos_fisicos(df)

        # 4. Extracción inicial de texto y barrio
        df = self._feature_service.construir_texto_completo(df)
        df = self._feature_service.extraer_barrio_desde_texto(df)

        # 5. Rescate por Fuzzy Matching de inmuebles con GPS falso
        df = self._rescatar_o_descartar_gps_falsos(df)

        # 6. Deduplicación Cross-Portal (antes de imputar centroides para no colapsar rescatados)
        df = df.drop_duplicates(
            subset=["latitud", "longitud", "area", "habitaciones", "banos", "precio_publicado"]
        ).copy()

        # 7. Saneamiento Geográfico: reemplazar coordenadas falsas por el centroide real del barrio/comuna
        df, centroides_barrio, centroides_comuna = self._imputar_centroides_reales(df)

        df["incluye_administracion"] = df["incluye_administracion"].astype(int)
        df["amoblado"] = df["amoblado"].astype(int)

        # 8. Ingeniería de características deterministas (texto, distancias SITVA/polos y ratios)
        df_estaciones = self._geo_repo.obtener_estaciones_sitva()
        df = self._feature_service.agregar_banderas_texto(df)
        df = self._feature_service.agregar_distancias_geoespaciales(df, df_estaciones)
        df = self._feature_service.agregar_ratios_estructurales(df)
        df = df.dropna(subset=["distancia_sitva_km"]).copy()

        # 9. Filtro de Outliers por Rango Intercuartílico real (P25-P75) sobre Precio/m2
        df_cleaned = self._filtrar_outliers_iqr(df)

        # 10. Segmentación en los dos regímenes del modelo: El Poblado vs. Otras Comunas
        df_poblado = df_cleaned[df_cleaned["comuna"] == "el poblado"].copy()
        df_comunas = df_cleaned[df_cleaned["comuna"] != "el poblado"].copy()

        # Agrupar comunas con baja frecuencia (< 30 muestras) para permitir partición estratificada
        frecuencia_comuna = df_comunas["comuna"].value_counts()
        df_comunas["comuna"] = np.where(
            df_comunas["comuna"].map(frecuencia_comuna) < 30,
            "Otro",
            df_comunas["comuna"],
        )

        return DatasetPreprocesado(
            df_poblado=df_poblado,
            df_otras_comunas=df_comunas,
            centroides_barrio=centroides_barrio,
            centroides_comuna=centroides_comuna,
            comunas_validas=list(df_comunas["comuna"].unique()),
            total_registros_limpios=len(df_cleaned),
        )

    def _asignar_comuna_geografica(self, df: pd.DataFrame) -> pd.DataFrame:
        mapa_medellin = self._geo_repo.obtener_mapa_comunas()
        puntos = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(df.longitud, df.latitud), crs="EPSG:4326"
        )
        unidos = gpd.sjoin(puntos, mapa_medellin, how="inner", predicate="within")
        unidos = unidos.dropna(subset=["nombre"]).copy()
        unidos["comuna"] = unidos["nombre"].str.lower()

        cols_geo = [
            "geometry", "index_right", "OBJECTID", "codigo", "nombre",
            "identificacion", "limitemunicipioid", "subtipo_comunacorregimiento",
            "fecha_actualizacion", "Shape_Length", "Shape_Area",
        ]
        cols_borrar = [c for c in cols_geo if c in unidos.columns]
        return pd.DataFrame(unidos.drop(columns=cols_borrar)).reset_index(drop=True)

    def _filtrar_rangos_fisicos(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self._config
        df = df[df["area"].between(cfg.min_area_m2, cfg.max_area_m2, inclusive="right")]
        df = df[
            df["precio_publicado"].between(cfg.min_precio_cop, cfg.max_precio_cop, inclusive="both")
            & (df["precio_publicado"] != cfg.precio_comodin_falso)
        ]
        df = df[df["banos"].between(0, cfg.max_banos, inclusive="right")]
        df = df[df["habitaciones"].between(0, cfg.max_habitaciones, inclusive="right")]
        df = df[df["estrato"].between(1, 6, inclusive="both")].copy()
        df["parqueaderos"] = df["parqueaderos"].fillna(0).clip(0, cfg.max_parqueaderos)
        return df

    @staticmethod
    def _rescatar_comuna_barrio_fuzzy(titulo: Any) -> Optional[Tuple[str, str]]:
        if not isinstance(titulo, str):
            return None
        match = process.extractOne(
            titulo.lower(), list(DICCIONARIO_RESCATE_BARRIOS.keys()), scorer=fuzz.partial_ratio
        )
        if match and match[1] >= 90:
            barrio_key = match[0]
            return (DICCIONARIO_RESCATE_BARRIOS[barrio_key], barrio_key)
        return None

    def _rescatar_o_descartar_gps_falsos(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        mask_falsos = (
            (df["comuna"].isin(["popular", "santa cruz", "manrique", "aranjuez", "villa hermosa"]) & (df["estrato"] >= 4))
            | (df["comuna"].isin(["doce de octubre", "san javier"]) & (df["estrato"] >= 5))
            | ((df["comuna"] == "la candelaria") & (df["estrato"] >= 5))
        )
        df["es_rescatado"] = 0

        if "title" in df.columns:
            rescates = df.loc[mask_falsos, "title"].apply(self._rescatar_comuna_barrio_fuzzy)
            idx_rescatados = rescates[rescates.notna()].index
            df.loc[idx_rescatados, "comuna"] = rescates[idx_rescatados].apply(lambda x: x[0])
            df.loc[idx_rescatados, "barrio"] = rescates[idx_rescatados].apply(lambda x: x[1])
            df.loc[idx_rescatados, "es_rescatado"] = 1

            idx_irrescatables = rescates[rescates.isna()].index
            df = df.drop(idx_irrescatables)
        else:
            df = df.drop(df[mask_falsos].index)

        # Excluir municipios fuera de Medellín ("otro")
        return df[df["comuna"] != "otro"].copy()

    @staticmethod
    def _imputar_centroides_reales(
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
        """
        Imputa de forma vectorizada las coordenadas medianas del barrio o comuna
        calculadas exclusivamente sobre anuncios con GPS verificado (es_rescatado == 0).
        """
        df = df.copy()
        gps_reales = df[df["es_rescatado"] == 0]
        df_cent_barrio = gps_reales.groupby("barrio")[["latitud", "longitud"]].median()
        df_cent_comuna = gps_reales.groupby("comuna")[["latitud", "longitud"]].median()

        mask_rescatados = df["es_rescatado"] == 1
        if mask_rescatados.any():
            barrios_resc = df.loc[mask_rescatados, "barrio"]
            comunas_resc = df.loc[mask_rescatados, "comuna"]

            lat_barrio = barrios_resc.map(df_cent_barrio["latitud"]).where(barrios_resc != "desconocido")
            lon_barrio = barrios_resc.map(df_cent_barrio["longitud"]).where(barrios_resc != "desconocido")

            lat_comuna = comunas_resc.map(df_cent_comuna["latitud"])
            lon_comuna = comunas_resc.map(df_cent_comuna["longitud"])

            df.loc[mask_rescatados, "latitud"] = (
                lat_barrio.fillna(lat_comuna).fillna(df.loc[mask_rescatados, "latitud"])
            )
            df.loc[mask_rescatados, "longitud"] = (
                lon_barrio.fillna(lon_comuna).fillna(df.loc[mask_rescatados, "longitud"])
            )

        return (
            df,
            df_cent_barrio.to_dict(orient="index"),
            df_cent_comuna.to_dict(orient="index"),
        )

    @staticmethod
    def _filtrar_outliers_iqr(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["precio_m2"] = df["precio_publicado"] / df["area"]
        indices_validos = []

        # Precalculamos cuantiles por estrato como respaldo para comunas con < 20 registros
        q1_estrato = df.groupby("estrato")["precio_m2"].quantile(0.25)
        q3_estrato = df.groupby("estrato")["precio_m2"].quantile(0.75)

        for (_, estrato_val), subset in df.groupby(["comuna", "estrato"]):
            if len(subset) >= 20:
                q1 = subset["precio_m2"].quantile(0.25)
                q3 = subset["precio_m2"].quantile(0.75)
            else:
                q1 = q1_estrato[estrato_val]
                q3 = q3_estrato[estrato_val]
            iqr = q3 - q1
            filtro = (subset["precio_m2"] >= q1 - 1.5 * iqr) & (subset["precio_m2"] <= q3 + 1.5 * iqr)
            indices_validos.extend(subset[filtro].index)

        return df.loc[indices_validos].copy()
