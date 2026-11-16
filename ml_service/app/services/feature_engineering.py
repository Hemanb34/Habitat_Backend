import re
import unicodedata
from typing import Dict, List, Set, Tuple
import numpy as np
import pandas as pd

from app.domain.config import LISTA_BARRIOS_MEDELLIN, MLServiceConfig
from app.infrastructure.spatial_transformers import min_haversine_vectorizado


class FeatureEngineeringService:
    """
    Servicio sin estado (Stateless) que calcula las características derivadas
    (texto, distancias geoespaciales y ratios estructurales).
    Se reutiliza de forma idéntica durante el ETL de entrenamiento y durante
    la inferencia en tiempo real (evitando Training-Serving Skew).
    """

    # Columnas numéricas base antes del SpatialKNNFeatures
    COLUMNAS_NUMERICAS_BASE: List[str] = [
        "banos", "area", "habitaciones", "parqueaderos", "latitud", "longitud",
        "distancia_sitva_km", "dist_metro_km", "dist_cable_km", "dist_tranvia_bus_km",
        "dist_parque_lleras_km", "dist_milla_oro_km", "dist_parque_laureles_km", "dist_ciudad_del_rio_km",
        "area_por_habitacion", "banos_por_habitacion", "parqueaderos_por_habitacion",
        "total_espacios", "tiene_parqueadero", "log_area", "area_x_estrato",
        "es_penthouse_duplex", "es_estudio_loft", "es_unidad_cerrada", "es_remodelado_lujo", "es_rescatado",
    ]

    # Columnas numéricas totales tras pasar por SpatialKNNFeatures
    COLUMNAS_NUMERICAS_TOTALES: List[str] = COLUMNAS_NUMERICAS_BASE + [
        "knn_log_pm2", "knn_log_precio_est", "knn_log_y_sim"
    ]

    BARRIOS_VALIDOS_SET: Set[str] = set(LISTA_BARRIOS_MEDELLIN)

    def __init__(self, config: MLServiceConfig):
        self._config = config
        self._patron_barrios = re.compile(
            r"\b(" + "|".join(map(re.escape, LISTA_BARRIOS_MEDELLIN)) + r")\b"
        )
        # Caché en memoria de los arreglos de coordenadas SITVA por subsistema (evita filtrar en cada petición)
        self._sitva_coords_cache: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}

    @staticmethod
    def normalizar_texto(texto: str) -> str:
        """Convierte a minúsculas y elimina tildes/diacríticos (NFD)."""
        if not isinstance(texto, str):
            return ""
        texto_min = texto.lower()
        return "".join(
            c for c in unicodedata.normalize("NFD", texto_min)
            if unicodedata.category(c) != "Mn"
        )

    def construir_texto_completo(self, df: pd.DataFrame) -> pd.DataFrame:
        """Une el título y el slug de la URL original en un único campo normalizado."""
        df = df.copy()
        titulos = df["title"].fillna("").astype(str) if "title" in df.columns else ""
        urls = (
            df["url_origen"].fillna("").astype(str).str.replace("-", " ").str.replace("/", " ")
            if "url_origen" in df.columns
            else ""
        )
        df["texto_completo"] = (titulos + " " + urls).apply(self.normalizar_texto)
        return df

    def extraer_barrio_desde_texto(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Identifica el barrio específico de Medellín de forma simétrica (sin Training-Serving Skew):
        - Si la fila ya trae un barrio válido del catálogo oficial, lo respeta.
        - En caso contrario (o si es 'desconocido'), lo extrae en una sola pasada vectorizada desde 'texto_completo'.
        """
        df = df.copy()
        if "texto_completo" not in df.columns:
            df = self.construir_texto_completo(df)

        extraido_texto = (
            df["texto_completo"]
            .str.extract(self._patron_barrios, expand=False)
            .fillna("desconocido")
        )

        if "barrio" in df.columns:
            barrio_actual = df["barrio"].fillna("desconocido").astype(str).apply(self.normalizar_texto).str.strip()
            es_valido = barrio_actual.isin(self.BARRIOS_VALIDOS_SET)
            df["barrio"] = np.where(es_valido, barrio_actual, extraido_texto)
        else:
            df["barrio"] = extraido_texto

        return df

    def agregar_banderas_texto(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extrae variables binarias de valor añadido a partir de palabras clave en el anuncio."""
        df = df.copy()
        texto = df["texto_completo"]
        df["es_penthouse_duplex"] = texto.str.contains(
            r"\b(?:penthouse|duplex|ph|altillo)\b", regex=True
        ).astype(int)
        df["es_estudio_loft"] = (
            (df["tipo_inmueble"] == "Apartaestudio")
            | texto.str.contains(r"\b(?:apartaestudio|loft|estudio)\b", regex=True)
        ).astype(int)
        df["es_unidad_cerrada"] = texto.str.contains(
            r"\b(?:unidad|urbanizacion|club house|porteria|piscina)\b", regex=True
        ).astype(int)
        df["es_remodelado_lujo"] = texto.str.contains(
            r"\b(?:remodelado|lujo|moderno|exclusivo|estrenar)\b", regex=True
        ).astype(int)
        return df

    def _obtener_coordenadas_sitva_cacheadas(
        self, df_estaciones: pd.DataFrame
    ) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
        """Precalcula y cachea los arreglos NumPy de latitud/longitud por subsistema SITVA."""
        if not self._sitva_coords_cache:
            est_metro = df_estaciones[df_estaciones["sistema"] == "Metro"]
            est_cable = df_estaciones[df_estaciones["sistema"] == "Metrocable"]
            est_tranvia_bus = df_estaciones[df_estaciones["sistema"].isin(["Tranvía", "Metroplús"])]

            self._sitva_coords_cache = {
                "todas": (df_estaciones["latitud"].values, df_estaciones["longitud"].values),
                "metro": (est_metro["latitud"].values, est_metro["longitud"].values),
                "cable": (est_cable["latitud"].values, est_cable["longitud"].values),
                "tranvia_bus": (est_tranvia_bus["latitud"].values, est_tranvia_bus["longitud"].values),
            }
        return self._sitva_coords_cache

    def agregar_distancias_geoespaciales(
        self, df: pd.DataFrame, df_estaciones: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calcula distancias Haversine hacia el SITVA (desglosado por Metro, Cable y Tranvía/Metroplús)
        y hacia los 4 Polos de Valorización configurados en MLServiceConfig.
        """
        df = df.copy()
        lats = df["latitud"].values
        lons = df["longitud"].values
        coords_sitva = self._obtener_coordenadas_sitva_cacheadas(df_estaciones)

        # 1. Distancias al SITVA global y por subsistema usando arreglos precalculados
        df["distancia_sitva_km"] = min_haversine_vectorizado(lats, lons, *coords_sitva["todas"])
        df["dist_metro_km"] = min_haversine_vectorizado(lats, lons, *coords_sitva["metro"])
        df["dist_cable_km"] = min_haversine_vectorizado(lats, lons, *coords_sitva["cable"])
        df["dist_tranvia_bus_km"] = min_haversine_vectorizado(lats, lons, *coords_sitva["tranvia_bus"])

        # 2. Distancias a Polos de Valorización definidos en config.py
        for nombre_col, (polo_lat, polo_lon) in self._config.polos_valorizacion.items():
            df[nombre_col] = min_haversine_vectorizado(
                lats, lons, np.array([polo_lat]), np.array([polo_lon])
            )

        return df

    @staticmethod
    def agregar_ratios_estructurales(df: pd.DataFrame) -> pd.DataFrame:
        """Calcula relaciones físicas entre área, habitaciones, baños, parqueaderos y estrato."""
        df = df.copy()
        hab_seguras = np.maximum(df["habitaciones"], 1)

        df["area_por_habitacion"] = df["area"] / hab_seguras
        df["banos_por_habitacion"] = df["banos"] / hab_seguras
        df["parqueaderos_por_habitacion"] = df["parqueaderos"] / hab_seguras
        df["total_espacios"] = df["habitaciones"] + df["banos"] + df["parqueaderos"]
        df["tiene_parqueadero"] = (df["parqueaderos"] > 0).astype(int)
        df["log_area"] = np.log1p(df["area"])
        df["area_x_estrato"] = df["area"] * df["estrato"]
        return df
