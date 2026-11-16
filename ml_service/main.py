import argparse
from contextlib import asynccontextmanager
from typing import AsyncIterator
import uvicorn
from fastapi import FastAPI

from app.boundary.api_router import (
    get_inference_service,
    get_retraining_control,
    precargar_recursos_al_inicio,
    router as ml_router,
)
from app.domain.schemas import InmuebleInputSchema


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Ciclo de vida de FastAPI: precarga el modelo .joblib y las estaciones SITVA
    en memoria RAM durante el arranque del servidor para que la primera petición
    a /predict responda en milisegundos (RNF-05).
    """
    precargar_recursos_al_inicio()
    yield


app = FastAPI(
    title="Habita - Servicio de Machine Learning Inmobiliario",
    description=(
        "Microservicio independiente de preprocesamiento (RN-02, RN-06), "
        "entrenamiento con Template Method y compuerta de calidad (RN-01), "
        "e inferencia de cánones de arrendamiento en Medellín (RF-02, RF-03, RNF-05)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(ml_router)


def ejecutar_entrenamiento_cli() -> None:
    """Entrena el modelo desde la consola invocando ReentrenamientoControl."""
    print("Iniciando pipeline de preprocesamiento y entrenamiento (Template Method)...")
    control = get_retraining_control()
    resultado = control.ejecutar_reentrenamiento()
    print("\n" + "=" * 65)
    print(f" ÉXITO                 : {resultado.exito}")
    print(f" PROMOVIDO PRODUCCIÓN  : {resultado.promovido_a_produccion}")
    print(f" VERSIÓN               : {resultado.version_modelo}")
    print(f" REGISTROS LIMPIOS     : {resultado.total_registros_entrenamiento}")
    print(f" MAPE EL POBLADO       : {resultado.mape_poblado * 100:.2f}%")
    print(f" MAPE OTRAS COMUNAS    : {resultado.mape_otras_comunas * 100:.2f}%")
    print(f" UMBRAL RN-01          : <= {resultado.umbral_rn01_aplicado * 100:.0f}%")
    print(f" MENSAJE               : {resultado.mensaje}")
    print("=" * 65)


def ejecutar_prueba_rapida_cli() -> None:
    """Prueba rápida de inferencia desde consola usando un diccionario."""
    servicio = get_inference_service()
    ejemplo = InmuebleInputSchema(
        comuna="el poblado",
        barrio="provenza",
        tipo_inmueble="Apartamento",
        area=95.0,
        habitaciones=2,
        banos=2,
        parqueaderos=1,
        estrato=6,
        estado="Usado",
        incluye_administracion=True,
        amoblado=True,
        titulo_o_descripcion="Apartamento remodelado en unidad cerrada cerca al Parque Lleras",
    )
    pred = servicio.predecir_individual(ejemplo)
    print("\n" + "=" * 65)
    print(" PRUEBA DE INFERENCIA DESDE DICCIONARIO / SCHEMA")
    print("=" * 65)
    print(f" Modelo utilizado   : {pred.modelo_utilizado} ({pred.version_modelo})")
    print(f" Coordenadas usadas : {pred.coordenadas_aplicadas}")
    print(f" Canon estimado     : ${pred.precio_estimado_cop:,.0f} COP / mes")
    print(f" Precio por m²      : ${pred.precio_m2_estimado_cop:,.0f} COP / m²")
    print(f" MAPE de referencia : {pred.mape_validacion_modelo * 100:.2f}%")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servicio ML Habita")
    parser.add_argument(
        "--train",
        action="store_true",
        help="Ejecuta el ciclo de preprocesamiento y entrenamiento (Template Method) por consola.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Ejecuta una predicción de prueba usando el modelo compilado en artifacts/.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Puerto HTTP para levantar el microservicio FastAPI (por defecto: 8001).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Activa recarga automática en modo desarrollo (desactivado por defecto para no recargar el modelo en RAM).",
    )
    args = parser.parse_args()

    if args.train:
        ejecutar_entrenamiento_cli()
    elif args.test:
        ejecutar_prueba_rapida_cli()
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=args.port, reload=args.reload)
