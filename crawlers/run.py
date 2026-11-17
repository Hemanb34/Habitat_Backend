"""
run.py — Script CLI para ejecutar y verificar la arquitectura de Crawlers.

Ejemplos de uso desde la raíz del proyecto (`C:\\Users\\heman\\Proyecto_Habita`):
  1. Prueba rápida (smoke test consultando solo 2 zonas por portal en paralelo):
       .venv\\Scripts\\python.exe -m crawlers.run --max-zones 2

  2. Probar un solo portal (ej. metrocuadrado con 2 zonas):
       .venv\\Scripts\\python.exe -m crawlers.run metrocuadrado --max-zones 2

  3. Corrida completa de los 3 portales en paralelo (17 zonas):
       .venv\\Scripts\\python.exe -m crawlers.run
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Garantiza que la raíz del proyecto esté en sys.path aunque se ejecute `python crawlers/run.py`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawlers.factory import CrawlerFactory
from crawlers.orchestrator_control import CrawlerOrquestadorControl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orquestador de Crawlers Asíncronos — Proyecto Habita"
    )
    parser.add_argument(
        "portals",
        nargs="*",
        default=[],
        help=f"Portales a ejecutar ({', '.join(CrawlerFactory.available_portals())}). Vacío = todos en paralelo.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fuerza refresco de caché de ubicaciones en FincaRaíz.",
    )
    parser.add_argument(
        "--max-zones",
        type=int,
        default=None,
        help="Límite de comunas/zonas a consultar por portal (ideal para pruebas rápidas).",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    portals = args.portals or CrawlerFactory.available_portals()

    orchestrator = CrawlerOrquestadorControl()
    summary = await orchestrator.ejecutar_extraccion(
        portals=portals,
        force_refresh_cache=args.refresh,
        max_zones=args.max_zones,
    )

    print("\n" + "=" * 88)
    print("RESUMEN DE ORQUESTACIÓN PARALELA (FORK/JOIN + FACTORY METHOD + ADAPTER + RN-06)")
    print("=" * 88)
    print(
        f"{'PORTAL':<16} {'ESTADO':<10} {'CRUDOS':>8} {'DESCARTADOS':>13} "
        f"{'DUPLICADOS':>12} {'ÚNICOS VÁLIDOS':>16} {'TIEMPO':>8}"
    )
    print("-" * 88)
    for rep in summary.portal_reports:
        print(
            f"{rep.portal:<16} {rep.status:<10} {rep.raw_extracted:>8} "
            f"{rep.rejected_rn06_or_invalid:>13} {rep.duplicates_removed:>12} "
            f"{rep.valid_unique_items:>16} {rep.elapsed_seconds:>7.2f}s"
        )
    print("-" * 88)
    print(
        f"{'TOTAL GLOBAL':<16} {'OK':<10} {summary.total_raw_extracted:>8} "
        f"{summary.total_rejected:>13} {summary.total_duplicates_removed:>12} "
        f"{summary.total_valid_unique:>16} {summary.elapsed_seconds:>7.2f}s"
    )
    print("=" * 88)

    if summary.items:
        sample = summary.items[0]
        print("\nEjemplo de DTO canónico validado (PropertyCreate):")
        print(sample.model_dump_json(indent=2))

        from backend.app.controls.admin_orchestrator_control import (
            MAPA_NOMBRE_PORTAL_UI,
            AdminOrchestratorControl,
        )
        from backend.app.domain.entities.crawler_job_entity import CrawlerJob
        from backend.app.infrastructure.database import SessionLocal
        from backend.app.infrastructure.repositories.audit_repository import (
            AuditRepository,
        )
        from backend.app.infrastructure.repositories.property_repository import (
            PropertyRepository,
        )

        with SessionLocal() as db:
            audit_repo = AuditRepository(db)
            control = AdminOrchestratorControl(
                property_repo=PropertyRepository(db),
                audit_repo=audit_repo,
            )
            insertados, actualizados = control.construir_y_persistir_inmuebles(
                summary.items
            )
            for rep in summary.portal_reports:
                audit_repo.actualizar_estado_portal(
                    rep.portal,
                    estado="idle" if rep.status == "SUCCESS" else "error",
                )
                audit_repo.registrar_crawler_job(
                    CrawlerJob(
                        portal=rep.portal,
                        dia_etiqueta="Hoy",
                        estado=rep.status,
                        registros_extraidos=rep.raw_extracted,
                        registros_validos_rn06=rep.valid_unique_items,
                        duplicados_omitidos=rep.duplicates_removed,
                        duracion_segundos=rep.elapsed_seconds,
                        mensaje_error=rep.error_message,
                    )
                )
            audit_repo.registrar_log(
                accion="Orquestación completa de Crawlers (CLI -> PostgreSQL)",
                detalle=(
                    f"Crudos: {summary.total_raw_extracted} | Válidos RN-06: {summary.total_valid_unique} | "
                    f"Nuevos en BD: {insertados} | Actualizados: {actualizados} ({summary.elapsed_seconds}s)"
                ),
                estado="ok",
                usuario="admin",
            )
            print(
                f"\n[PostgreSQL habita_db] Catálogo renovado (Opción 1A): "
                f"{insertados} vigentes insertados | {actualizados} anteriores reemplazados."
            )


if __name__ == "__main__":
    asyncio.run(main())
