from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from app.domain.schemas import InmuebleInputSchema, PrediccionOutputSchema
from app.infrastructure.repositories import IGeoReferenceRepository, IModelArtifactRepository
from app.services.feature_engineering import FeatureEngineeringService


class ModeloPredictivoService:
    """
    Servicio <<service>> que mantiene cargado en memoria RAM el artefacto de
    producción y ejecuta la inferencia matemática vectorizada en tiempo real (< 3s, RNF-05).
    Reutiliza FeatureEngineeringService para garantizar simetría exacta con el entrenamiento.
    """

    MAPA_TILDES_COMUNA: Dict[str, str] = {
        "belen": "belén",
        "la america": "la américa",
        "laureles": "laureles estadio",
        "laureles - estadio": "laureles estadio",
        "poblado": "el poblado",
    }

    def __init__(
        self,
        artifact_repo: IModelArtifactRepository,
        geo_repo: IGeoReferenceRepository,
        feature_service: FeatureEngineeringService,
    ):
        self._artifact_repo = artifact_repo
        self._geo_repo = geo_repo
        self._feature_service = feature_service
        self._artefacto_memoria: Optional[Dict[str, Any]] = None

    def asegurar_modelo_cargado(self) -> Dict[str, Any]:
        """Carga el modelo en RAM la primera vez (o en lifespan) y lo reutiliza en siguientes peticiones."""
        if self._artefacto_memoria is None:
            self._artefacto_memoria = self._artifact_repo.cargar_artefacto()
        return self._artefacto_memoria

    def recargar_modelo_en_caliente(self) -> Dict[str, Any]:
        """
        Actualiza la referencia en memoria RAM inmediatamente después de que
        ReentrenamientoControl promueve una nueva versión que aprobó RN-01.
        """
        self._artefacto_memoria = self._artifact_repo.cargar_artefacto()
        return self._artefacto_memoria

    def esta_cargado_en_ram(self) -> bool:
        """Indica si el artefacto ya está residente en memoria RAM."""
        return self._artefacto_memoria is not None

    def obtener_metricas_actuales(self) -> Dict[str, Any]:
        """Devuelve la metadata del modelo activo en producción para el Dashboard (RF-11)."""
        art = self.asegurar_modelo_cargado()
        return {
            "en_produccion": True,
            "version": art.get("version", "v1_inicial"),
            "fecha_entrenamiento": art.get("fecha_entrenamiento", "N/A"),
            "mape_poblado": round(float(art["mape_poblado"]), 4),
            "mape_otras_comunas": round(float(art["mape_comunas"]), 4),
            "mape_poblado_porcentaje": f"{art['mape_poblado'] * 100:.2f}%",
            "mape_otras_comunas_porcentaje": f"{art['mape_comunas'] * 100:.2f}%",
        }

    def predecir_individual(self, item: InmuebleInputSchema) -> PrediccionOutputSchema:
        """Ejecuta la estimación para un único inmueble (RF-03)."""
        return self.predecir_lote([item])[0]

    def predecir_lote(self, items: List[InmuebleInputSchema]) -> List[PrediccionOutputSchema]:
        """
        Ejecuta la estimación vectorizada para un lote de inmuebles (RF-02 - Motor de Búsqueda Inteligente)
        o para un inmueble individual.
        Construye un único DataFrame para todo el lote, calcula todas las características de una sola vez
        y ejecuta máximo dos llamadas matriciales a predict() (una por régimen).
        """
        if not items:
            return []

        artefacto = self.asegurar_modelo_cargado()
        df_estaciones = self._geo_repo.obtener_estaciones_sitva()
        centroides_barrio = artefacto["centroides_barrio"]
        centroides_comuna = artefacto["centroides_comuna"]
        comunas_validas = set(artefacto["comunas_validas_modelo"])
        version_modelo = str(artefacto.get("version", "v1_inicial"))

        filas_crudas: List[Dict[str, Any]] = []
        comunas_resueltas: List[str] = []
        coordenadas_resueltas: List[Tuple[float, float]] = []

        # 1. Pre-estructurar las entradas del lote en memoria
        for item in items:
            comuna_norm = self._feature_service.normalizar_texto(item.comuna).strip()
            comuna = self.MAPA_TILDES_COMUNA.get(comuna_norm, comuna_norm)
            comunas_resueltas.append(comuna)

            barrio_raw = item.barrio or "desconocido"
            barrio = self._feature_service.normalizar_texto(barrio_raw).strip() or "desconocido"

            lat, lon, es_rescatado = self._resolver_coordenadas(
                item.latitud, item.longitud, barrio, comuna, centroides_barrio, centroides_comuna
            )
            coordenadas_resueltas.append((lat, lon))

            estado_limpio = item.estado.capitalize() if item.estado else "Usado"
            if estado_limpio not in ["Usado", "Nuevo"]:
                estado_limpio = "Usado"

            filas_crudas.append({
                "comuna": comuna if comuna in comunas_validas else "Otro",
                "barrio": barrio,
                "tipo_inmueble": item.tipo_inmueble.capitalize(),
                "area": float(item.area),
                "habitaciones": int(item.habitaciones),
                "banos": int(item.banos),
                "parqueaderos": int(item.parqueaderos),
                "estrato": int(item.estrato),
                "estado": estado_limpio,
                "incluye_administracion": int(bool(item.incluye_administracion)),
                "amoblado": int(bool(item.amoblado)),
                "latitud": lat,
                "longitud": lon,
                "es_rescatado": es_rescatado,
                "portal": item.portal.lower(),
                "title": f"{item.tipo_inmueble} {item.titulo_o_descripcion or ''}",
                "url_origen": "",
            })

        # 2. Construir un único DataFrame y aplicar FeatureEngineeringService de forma 100% vectorizada
        df_lote = pd.DataFrame(filas_crudas)
        df_lote = self._feature_service.construir_texto_completo(df_lote)
        df_lote = self._feature_service.extraer_barrio_desde_texto(df_lote)
        df_lote = self._feature_service.agregar_banderas_texto(df_lote)
        df_lote = self._feature_service.agregar_distancias_geoespaciales(df_lote, df_estaciones)
        df_lote = self._feature_service.agregar_ratios_estructurales(df_lote)

        # 3. Predicción matricial por segmento (El Poblado vs. Otras Comunas)
        precios_estimados = np.zeros(len(items), dtype=float)
        mask_poblado = np.array([c == "el poblado" for c in comunas_resueltas], dtype=bool)

        if np.any(mask_poblado):
            df_pob = df_lote.loc[mask_poblado].drop(columns=["comuna"])
            precios_estimados[mask_poblado] = artefacto["pipeline_poblado"].predict(df_pob)

        if np.any(~mask_poblado):
            df_com = df_lote.loc[~mask_poblado]
            precios_estimados[~mask_poblado] = artefacto["pipeline_comunas"].predict(df_com)

        # 4. Construir contratos de respuesta manteniendo el orden exacto de entrada
        mape_pob = round(float(artefacto["mape_poblado"]), 4)
        mape_com = round(float(artefacto["mape_comunas"]), 4)

        resultados: List[PrediccionOutputSchema] = []
        for idx, item in enumerate(items):
            es_pob = mask_poblado[idx]
            precio_est = float(precios_estimados[idx])
            precio_m2 = precio_est / float(item.area)
            lat_aplicada, lon_aplicada = coordenadas_resueltas[idx]

            resultados.append(
                PrediccionOutputSchema(
                    id_inmueble=item.id_inmueble,
                    precio_estimado_cop=round(precio_est, -3),
                    precio_m2_estimado_cop=round(precio_m2, 0),
                    modelo_utilizado="Modelo El Poblado" if es_pob else "Modelo Otras Comunas",
                    version_modelo=version_modelo,
                    mape_validacion_modelo=mape_pob if es_pob else mape_com,
                    coordenadas_aplicadas=(round(lat_aplicada, 5), round(lon_aplicada, 5)),
                )
            )

        return resultados

    @staticmethod
    def _resolver_coordenadas(
        lat: Optional[float],
        lon: Optional[float],
        barrio: str,
        comuna: str,
        centroides_barrio: Dict[str, Dict[str, float]],
        centroides_comuna: Dict[str, Dict[str, float]],
    ) -> Tuple[float, float, int]:
        if lat is not None and lon is not None:
            return float(lat), float(lon), 0

        if barrio in centroides_barrio and barrio != "desconocido":
            return (
                float(centroides_barrio[barrio]["latitud"]),
                float(centroides_barrio[barrio]["longitud"]),
                1,
            )
        if comuna in centroides_comuna:
            return (
                float(centroides_comuna[comuna]["latitud"]),
                float(centroides_comuna[comuna]["longitud"]),
                1,
            )
        # Centroide por defecto en Medellín si ni el barrio ni la comuna están registrados
        return 6.2476, -75.5758, 1
