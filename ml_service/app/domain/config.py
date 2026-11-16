import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

# Resuelve automáticamente la raíz de 'ml_service/' sin importar en qué PC se ejecute:
# config.py está en: ml_service/app/domain/config.py -> parents[2] es: ml_service/
ML_SERVICE_ROOT: Path = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MLServiceConfig:
    # 1. Directorios dinámicos relativos a Proyecto_Habita/ml_service y conexión PostgreSQL
    root_dir: Path = ML_SERVICE_ROOT
    reference_data_dir: Path = ML_SERVICE_ROOT / "data" / "reference"
    raw_data_dir: Path = ML_SERVICE_ROOT / "data" / "raw"
    artifacts_dir: Path = ML_SERVICE_ROOT / "artifacts"
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "HABITA_DATABASE_URL",
            "postgresql+psycopg2://admin:admin_password@localhost:5432/habita_db",
        )
    )

    # 2. Nombres de archivos estáticos, artefacto activo y respaldo (Rollback)
    geojson_filename: str = "comunas_y_corregimientos_.geojson"
    sitva_filename: str = "estaciones_sitva_medellin.csv"
    model_artifact_filename: str = "modelos_habita.joblib"
    model_backup_filename: str = "modelos_habita.prev.joblib"

    # 3. Regla de Negocio RN-01 y RNF-02:
    # "Ninguna actualización del algoritmo podrá ser desplegada a producción
    # si su margen de error (MAPE) sobre validación supera el 16% (0.16)."
    max_allowed_mape: float = 0.16

    # 4. Control de concurrencia de CPU (RNF-08) y límite de lote (RNF-05)
    # Se limita n_jobs_training a 4 núcleos para dejar capacidad libre a FastAPI durante reentrenamientos
    n_jobs_training: int = 4
    max_batch_size: int = 500

    # 5. Proporción de partición para cumplir RN-02 (80% Train / 20% Validación)
    test_size: float = 0.20
    random_state_split: int = 10

    # 6. Límites físicos de saneamiento de dominio para el entrenamiento
    min_area_m2: float = 15.0
    max_area_m2: float = 500.0
    min_precio_cop: float = 500_000.0
    max_precio_cop: float = 15_000_000.0
    precio_comodin_falso: float = 1_111_111.0
    max_banos: int = 4
    max_habitaciones: int = 5
    max_parqueaderos: int = 6

    # 7. Polos de Valorización Inmobiliaria en Medellín (Latitud, Longitud)
    polos_valorizacion: Dict[str, Tuple[float, float]] = field(
        default_factory=lambda: {
            "dist_parque_lleras_km": (6.2089, -75.5658),
            "dist_milla_oro_km": (6.1965, -75.5736),
            "dist_parque_laureles_km": (6.2458, -75.5972),
            "dist_ciudad_del_rio_km": (6.2238, -75.5744),
        }
    )

    @property
    def geojson_path(self) -> Path:
        return self.reference_data_dir / self.geojson_filename

    @property
    def sitva_path(self) -> Path:
        return self.reference_data_dir / self.sitva_filename

    @property
    def model_artifact_path(self) -> Path:
        return self.artifacts_dir / self.model_artifact_filename

    @property
    def model_backup_path(self) -> Path:
        return self.artifacts_dir / self.model_backup_filename


# Catálogo de barrios de Medellín ordenado por longitud descendente para evitar colisiones parciales en Regex
LISTA_BARRIOS_MEDELLIN: List[str] = [
    "santa maria de los angeles", "altos del poblado", "loma de los bernal", "carlos e restrepo",
    "loma del escobero", "loma del chocho", "ciudad del rio", "cuarta brigada", "florida nueva",
    "simon bolivar", "santa monica", "patio bonito", "milla de oro", "buenos aires", "villa hermosa",
    "conquistadores", "los naranjos", "las acacias", "los colores", "san joaquin", "bolivariana",
    "suramericana", "santa lucia", "el diamantito", "el castillo", "aguacatala", "el poblado",
    "las palmas", "las lomas", "los balsos", "san lucas", "el tesoro", "la florida", "alejandria",
    "castropol", "provenza", "san diego", "los parra", "el nogal", "velodromo", "la mota",
    "rodeo alto", "los alpes", "la palma", "calasanz", "floresta", "pilarica", "miraflores",
    "el salvador", "la america", "la candelaria", "aranjuez", "manrique", "robledo", "laureles",
    "estadio", "lalinde", "manila", "astorga", "lleras", "oviedo", "vizcaya", "linares",
    "lorena", "rosales", "fatima", "granada", "belen", "boston", "prado", "centro", "aures"
]

# Diccionario para rescatar por Fuzzy Matching anuncios cuyo pin GPS cayó en comunas incompatibles con su estrato
DICCIONARIO_RESCATE_BARRIOS: Dict[str, str] = {
    # El Poblado (Comuna 14)
    "el poblado": "el poblado", "castropol": "el poblado", "lalinde": "el poblado",
    "manila": "el poblado", "patio bonito": "el poblado", "astorga": "el poblado",
    "las lomas": "el poblado", "altos del poblado": "el poblado", "los balsos": "el poblado",
    "san lucas": "el poblado", "el tesoro": "el poblado", "los naranjos": "el poblado",
    "san diego": "el poblado", "las palmas": "el poblado", "provenza": "el poblado",
    "la florida": "el poblado", "lleras": "el poblado", "alejandria": "el poblado",
    "ciudad del rio": "el poblado",
    # Laureles - Estadio (Comuna 11)
    "laureles": "laureles estadio", "estadio": "laureles estadio", "conquistadores": "laureles estadio",
    "florida nueva": "laureles estadio", "velodromo": "laureles estadio", "san joaquin": "laureles estadio",
    "bolivariana": "laureles estadio", "los colores": "laureles estadio", "cuarta brigada": "laureles estadio",
    "suramericana": "laureles estadio",
    # Municipios aledaños mal etiquetados como Medellín (se excluyen en el saneamiento)
    "envigado": "otro", "sabaneta": "otro", "loma del chocho": "otro", "loma del escobero": "otro",
    "la frontera": "otro", "zuñiga": "otro", "cumbres": "otro", "san jose": "otro", "señorial": "otro",
    "las antillas": "otro", "la doctora": "otro", "aves maria": "otro", "itagui": "otro", "bello": "otro"
}
