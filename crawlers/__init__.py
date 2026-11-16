"""
crawlers/__init__.py — Paquete modular de Ingesta Asíncrona para Habita.

Integra:
  - Patrón Factory Method (`CrawlerFactory`)
  - Patrón Adapter (`PropertyDataAdapter` y adaptadores concretos)
  - Spiders asíncronos (`MetrocuadradoCrawler`, `FincaraizCrawler`, `CiencuadrasCrawler`)
  - Controlador de orquestación concurrente (`CrawlerOrquestadorControl`)
"""

from crawlers.adapters import (
    CiencuadrasAdapter,
    FincaraizAdapter,
    MetrocuadradoAdapter,
    PropertyDataAdapter,
)
from crawlers.base import AsyncCrawler
from crawlers.factory import CrawlerFactory
from crawlers.orchestrator_control import CrawlerOrquestadorControl
from crawlers.schemas import OrchestrationSummary, PortalCrawlReport, PropertyCreate
from crawlers.spiders import (
    CiencuadrasCrawler,
    FincaraizCrawler,
    MetrocuadradoCrawler,
)

__all__ = [
    "AsyncCrawler",
    "CrawlerFactory",
    "CrawlerOrquestadorControl",
    "PropertyDataAdapter",
    "MetrocuadradoAdapter",
    "FincaraizAdapter",
    "CiencuadrasAdapter",
    "MetrocuadradoCrawler",
    "FincaraizCrawler",
    "CiencuadrasCrawler",
    "PropertyCreate",
    "PortalCrawlReport",
    "OrchestrationSummary",
]
