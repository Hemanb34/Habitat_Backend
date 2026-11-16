import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import KFold
from sklearn.neighbors import KNeighborsRegressor


def min_haversine_vectorizado(
    lat_arr: np.ndarray,
    lon_arr: np.ndarray,
    ref_lats: np.ndarray,
    ref_lons: np.ndarray,
) -> np.ndarray:
    """
    Calcula de forma 100% vectorizada (NumPy broadcasting) la distancia mínima
    en kilómetros sobre la esfera terrestre desde un conjunto de inmuebles
    hacia un conjunto de puntos de referencia (estaciones SITVA o polos urbanos).
    """
    radio_tierra_km = 6371.0

    # Convertimos grados decimales a radianes y redimensionamos a matriz (N, 1) y (1, M)
    lat1 = np.radians(lat_arr)[:, None]
    lon1 = np.radians(lon_arr)[:, None]
    lat2 = np.radians(ref_lats)[None, :]
    lon2 = np.radians(ref_lons)[None, :]

    # Diferencias angulares (genera una matriz de N inmuebles x M referencias)
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Fórmula trigonométrica de Haversine
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    c = 2.0 * np.arcsin(np.sqrt(a))
    matriz_distancias_km = radio_tierra_km * c

    # Retornamos para cada inmueble (axis=1) únicamente la distancia al punto más cercano
    return np.min(matriz_distancias_km, axis=1)


def peso_suave_distancia(distancias: np.ndarray) -> np.ndarray:
    """
    Kernel de ponderación espacial inversa suavizada: w = 1 / (d + 0.05).
    Evita divisiones por cero cuando dos apartamentos están en el mismo edificio (d = 0)
    e impide que un único vecino a distancia cero acapare el 100% del peso.
    """
    return 1.0 / (distancias + 0.05)


class SpatialKNNFeatures(BaseEstimator, TransformerMixin):
    """
    Transformador personalizado de Scikit-Learn que calcula variables de contexto
    espacial local basadas en los K vecinos más cercanos.

    Cumple estrictamente RN-02 (Prohibición de Data Leakage):
    - En fit(): Aprende exclusivamente del conjunto de entrenamiento (X_train, y_train)
      usando solo inmuebles con coordenadas reales verificadas (es_rescatado == 0).
    - En fit_transform(): Utiliza validación cruzada interna (Out-of-Fold KFold) para que
      ningún inmueble de entrenamiento use su propio precio al calcular sus vecinos.
    - En transform(): Evalúa nuevos inmuebles (Validación o Inferencia API) consultando
      únicamente los vecinos almacenados de X_train con n_jobs=1 para evitar overhead de hilos.
    """

    def __init__(self, n_neighbors: int = 20, n_splits: int = 5, n_jobs: int = 1):
        self.n_neighbors = n_neighbors
        self.n_splits = n_splits
        self.n_jobs = n_jobs

    def _construir_espacio_busqueda(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """
        Convierte (latitud, longitud, estrato, area) a una escala métrica comparable (~km).
        1 grado de latitud/longitud en Medellín equivale aproximadamente a 111 km.
        """
        lat_km = X["latitud"].values * 111.0
        lon_km = X["longitud"].values * 111.0
        estrato_pond = X["estrato"].values * 0.4
        area_log_pond = np.log1p(X["area"].values) * 0.4

        # Espacio 1: Vecinos geográficos del mismo estrato (para estimar log(precio/m2) de la micro-zona)
        coords_geo_estrato = np.column_stack([lat_km, lon_km, estrato_pond])
        # Espacio 2: Vecinos geográficos de igual estrato y tamaño similar (para estimar log(precio total))
        coords_similares = np.column_stack([lat_km, lon_km, estrato_pond, area_log_pond])
        return coords_geo_estrato, coords_similares

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        # Filtramos solo inmuebles con GPS original verificado para construir el mapa de referencia
        mask_gps_real = X["es_rescatado"].values == 0
        if np.sum(mask_gps_real) < 50:
            mask_gps_real = np.ones(len(X), dtype=bool)

        X_real = X.iloc[np.where(mask_gps_real)[0]]
        c_geo, c_sim = self._construir_espacio_busqueda(X_real)

        # Nota: 'y' llega ya en escala logarítmica log1p(precio) desde TransformedTargetRegressor.
        # Por propiedades de logaritmos: log(precio / area) = log(precio) - log(area)
        log_area_real = np.log(X_real["area"].values)
        y_real = np.asarray(y)[mask_gps_real]
        log_precio_m2_real = y_real - log_area_real

        k = min(self.n_neighbors, len(c_geo) - 1)
        self.knn_geo_ = KNeighborsRegressor(
            n_neighbors=k, weights=peso_suave_distancia, n_jobs=self.n_jobs
        ).fit(c_geo, log_precio_m2_real)

        self.knn_sim_ = KNeighborsRegressor(
            n_neighbors=k, weights=peso_suave_distancia, n_jobs=self.n_jobs
        ).fit(c_sim, y_real)
        return self

    def fit_transform(self, X: pd.DataFrame, y: np.ndarray) -> pd.DataFrame:
        # 1. Ajustamos los modelos finales de referencia para futuras llamadas a transform()
        self.fit(X, y)

        # 2. Calculamos predicciones Out-of-Fold (K-Fold) para X_train evitando auto-contaminación
        c_geo, c_sim = self._construir_espacio_busqueda(X)
        log_area = np.log(X["area"].values)
        y_arr = np.asarray(y)
        log_pm2 = y_arr - log_area
        es_real_arr = X["es_rescatado"].values == 0

        oof_log_pm2 = np.zeros(len(X))
        oof_log_y_sim = np.zeros(len(X))

        kf = KFold(n_splits=self.n_splits, shuffle=True, random_state=42)
        for tr_idx, val_idx in kf.split(X):
            # En cada fold entrenamos el KNN solo con los puntos de GPS real de ese sub-fold
            tr_real_idx = tr_idx[es_real_arr[tr_idx]]
            if len(tr_real_idx) < 30:
                tr_real_idx = tr_idx

            k = min(self.n_neighbors, len(tr_real_idx) - 1)
            modelo_geo = KNeighborsRegressor(
                n_neighbors=k, weights=peso_suave_distancia, n_jobs=self.n_jobs
            ).fit(c_geo[tr_real_idx], log_pm2[tr_real_idx])

            modelo_sim = KNeighborsRegressor(
                n_neighbors=k, weights=peso_suave_distancia, n_jobs=self.n_jobs
            ).fit(c_sim[tr_real_idx], y_arr[tr_real_idx])

            oof_log_pm2[val_idx] = modelo_geo.predict(c_geo[val_idx])
            oof_log_y_sim[val_idx] = modelo_sim.predict(c_sim[val_idx])

        X_out = X.copy()
        X_out["knn_log_pm2"] = oof_log_pm2
        X_out["knn_log_precio_est"] = oof_log_pm2 + log_area
        X_out["knn_log_y_sim"] = oof_log_y_sim
        return X_out

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        c_geo, c_sim = self._construir_espacio_busqueda(X)
        log_area = np.log(X["area"].values)

        pred_log_pm2 = self.knn_geo_.predict(c_geo)
        pred_log_y_sim = self.knn_sim_.predict(c_sim)

        X_out = X.copy()
        X_out["knn_log_pm2"] = pred_log_pm2
        X_out["knn_log_precio_est"] = pred_log_pm2 + log_area
        X_out["knn_log_y_sim"] = pred_log_y_sim
        return X_out
