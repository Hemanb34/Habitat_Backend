"""
orchestrator_control.py — Controlador `CrawlerOrquestadorControl` (Capa Control).

Implementa el flujo del Diagrama de Actividades F1 (Orquestar Extracción de Datos):
  1. Instancia cada portal mediante `CrawlerFactory` (Patrón Factory Method).
  2. Ejecuta todos los portales en paralelo con `asyncio.gather` (Fork / Join).
  3. Recibe los DTOs `PropertyCreate` ya normalizados y filtrados por RN-06
     desde los `PropertyDataAdapter` (Patrón Adapter).
  4. Realiza deduplicación temprana en memoria por `url_origen` para eliminar
     anuncios solapados entre zonas de búsqueda vecinas (ej. 'laureles' vs 'estadio').
  5. Consolida las métricas de auditoría por portal (`PortalCrawlReport`) para
     alimentar las tablas `crawler_jobs` y `audit_logs` (RNF-09).
"""

import asyncio
import logging
import time
from typing import Optional

from crawlers.factory import CrawlerFactory
from crawlers.schemas import OrchestrationSummary, PortalCrawlReport, PropertyCreate

logger = logging.getLogger(__name__)


class CrawlerOrquestadorControl:
    """
    Controlador de orquestación concurrente multi-portal (BCE: Control).
    """

    async def ejecutar_extraccion(
        self,
        portals: Optional[list[str]] = None,
        force_refresh_cache: bool = False,
        max_zones: Optional[int] = None,
    ) -> OrchestrationSummary:
        """
        Orquesta en paralelo (Fork/Join) la extracción y normalización de los
        portales solicitados.

        Args:
            portals:             Lista de portales a ejecutar (por defecto todos).
            force_refresh_cache: Si True, fuerza refresco de caché en FincaRaíz.
            max_zones:           Límite opcional de zonas por portal (para pruebas rápidas).
        """
        target_portals = portals or CrawlerFactory.available_portals()
        t0_global = time.perf_counter()

        logger.info(
            "Iniciando orquestación paralela (Fork) para portales: %s",
            target_portals,
        )

        # Fork: lanzar todos los portales concurrentemente con asyncio.gather
        tasks = [
            self._run_single_portal(
                portal_name=p,
                force_refresh_cache=force_refresh_cache,
                max_zones=max_zones,
            )
            for p in target_portals
        ]
        results = await asyncio.gather(*tasks)

        # Join: consolidar reportes y deduplicar globalmente por url_origen
        portal_reports: list[PortalCrawlReport] = []
        global_unique_items: list[PropertyCreate] = []
        seen_urls_global: set[str] = set()

        total_raw = 0
        total_rejected = 0
        total_duplicates = 0

        for report, unique_portal_items in results:
            portal_reports.append(report)
            total_raw += report.raw_extracted
            total_rejected += report.rejected_rn06_or_invalid
            total_duplicates += report.duplicates_removed

            for item in unique_portal_items:
                if item.url_origen not in seen_urls_global:
                    seen_urls_global.add(item.url_origen)
                    global_unique_items.append(item)
                else:
                    total_duplicates += 1

        elapsed_global = round(time.perf_counter() - t0_global, 2)

        logger.info(
            "Orquestación finalizada (Join) en %.2fs | Crudos=%d | Rechazados RN-06=%d | Duplicados=%d | Únicos válidos=%d",
            elapsed_global,
            total_raw,
            total_rejected,
            total_duplicates,
            len(global_unique_items),
        )

        return OrchestrationSummary(
            total_raw_extracted=total_raw,
            total_rejected=total_rejected,
            total_duplicates_removed=total_duplicates,
            total_valid_unique=len(global_unique_items),
            elapsed_seconds=elapsed_global,
            portal_reports=portal_reports,
            items=global_unique_items,
        )

    async def _run_single_portal(
        self,
        portal_name: str,
        force_refresh_cache: bool = False,
        max_zones: Optional[int] = None,
    ) -> tuple[PortalCrawlReport, list[PropertyCreate]]:
        """Ejecuta un portal individual y deduplica sus resultados por `url_origen`."""
        t0 = time.perf_counter()
        kwargs: dict = {}
        if max_zones is not None:
            kwargs["max_zones"] = max_zones
        if portal_name.lower() == "fincaraiz" and force_refresh_cache:
            kwargs["force_refresh_cache"] = True

        try:
            crawler = CrawlerFactory.create_crawler(portal_name, **kwargs)
            valid_items = await crawler.run()

            # Deduplicación temprana en memoria por url_origen
            unique_items: list[PropertyCreate] = []
            seen_urls: set[str] = set()
            duplicates_count = 0

            for prop in valid_items:
                if prop.url_origen in seen_urls:
                    duplicates_count += 1
                else:
                    seen_urls.add(prop.url_origen)
                    unique_items.append(prop)

            elapsed = round(time.perf_counter() - t0, 2)
            report = PortalCrawlReport(
                portal=crawler.name or portal_name,
                status="SUCCESS",
                raw_extracted=crawler.last_raw_count,
                rejected_rn06_or_invalid=crawler.last_rejected_count,
                duplicates_removed=duplicates_count,
                valid_unique_items=len(unique_items),
                elapsed_seconds=elapsed,
            )
            return report, unique_items

        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 2)
            logger.error("Fallo crítico en portal '%s': %s", portal_name, exc)
            report = PortalCrawlReport(
                portal=portal_name,
                status="FAILED",
                elapsed_seconds=elapsed,
                error_message=str(exc),
            )
            return report, []
