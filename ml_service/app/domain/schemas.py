from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


class InmuebleInputSchema(BaseModel):
    """
    Contrato de entrada para estimar el canon de arriendo de un inmueble (RF-03).
    Usado tanto en predicción individual como en lote (RF-02).
    """
    id_inmueble: Optional[str] = Field(default=None, description="ID opcional para trazabilidad en lotes")
    comuna: str = Field(..., description="Nombre de la comuna en Medellín, ej: 'el poblado', 'laureles estadio', 'belén'")
    barrio: Optional[str] = Field(default="desconocido", description="Barrio específico del inmueble")
    tipo_inmueble: str = Field(default="Apartamento", description="Apartamento, Casa o Apartaestudio")
    area: float = Field(..., gt=0, description="Área construida en metros cuadrados (m2)")
    habitaciones: int = Field(..., ge=0, description="Número de habitaciones")
    banos: int = Field(..., ge=1, description="Número de baños")
    parqueaderos: int = Field(default=0, ge=0, description="Número de parqueaderos")
    estrato: int = Field(..., ge=1, le=6, description="Estrato socioeconómico (1 a 6)")
    estado: str = Field(default="Usado", description="Estado del inmueble: 'Usado' o 'Nuevo'")
    incluye_administracion: bool = Field(default=True, description="True si el canon incluye administración")
    amoblado: bool = Field(default=False, description="True si el inmueble se arrienda amoblado")
    latitud: Optional[float] = Field(default=None, description="Latitud GPS opcional (si se omite, usa centroide del barrio)")
    longitud: Optional[float] = Field(default=None, description="Longitud GPS opcional")
    titulo_o_descripcion: Optional[str] = Field(default="", description="Título o descripción para extraer palabras clave")
    portal: str = Field(default="fincaraiz", description="Portal de referencia")


class BatchPredictionRequestSchema(BaseModel):
    """Contrato para predicción en lote cuando BusquedaControl ordena por 'Mejor Oferta' (RF-02)."""
    inmuebles: List[InmuebleInputSchema] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Lista de inmuebles a evaluar en lote (máximo 500 registros por petición)",
    )


class PrediccionOutputSchema(BaseModel):
    """
    Contrato de salida que entrega el Servicio ML a la Fachada del Backend (PropertyValuationFacade).
    """
    id_inmueble: Optional[str] = None
    precio_estimado_cop: float
    precio_m2_estimado_cop: float
    modelo_utilizado: str
    version_modelo: str = "v1_inicial"
    mape_validacion_modelo: float
    coordenadas_aplicadas: Tuple[float, float]


class ResultadoReentrenamientoSchema(BaseModel):
    """
    Contrato de salida tras ejecutar el Template Method de reentrenamiento (RF-10, RN-01).
    """
    exito: bool
    promovido_a_produccion: bool
    version_modelo: str
    mape_poblado: float
    mape_otras_comunas: float
    umbral_rn01_aplicado: float
    total_registros_entrenamiento: int
    mensaje: str
