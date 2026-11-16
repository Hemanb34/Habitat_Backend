"""
factory.py — Patrón GoF Factory Method (`CrawlerFactory`).

Cumple con el Requisito No Funcional RNF-07 (extensibilidad de fuentes mediante
registro declarativo sin modificar el orquestador) y los principios SOLID
Open/Closed (OCP) e Inversión de Dependencias (DIP).
"""

from typing import Dict, Type

from crawlers.base import AsyncCrawler
from crawlers.spiders.ciencuadras_spider import CiencuadrasCrawler
from crawlers.spiders.fincaraiz_spider import FincaraizCrawler
from crawlers.spiders.metrocuadrado_spider import MetrocuadradoCrawler


class CrawlerFactory:
    """
    Creador del Patrón Factory Method (Ficha 1 GoF).
    Instancia dinámicamente subtipos de `AsyncCrawler` a partir del nombre del portal.
    """

    _registry: Dict[str, Type[AsyncCrawler]] = {
        "metrocuadrado": MetrocuadradoCrawler,
        "fincaraiz": FincaraizCrawler,
        "ciencuadras": CiencuadrasCrawler,
    }

    @classmethod
    def register_crawler(
        cls, portal_name: str, crawler_cls: Type[AsyncCrawler]
    ) -> None:
        """Registra un nuevo portal en la factoría sin alterar el código existente (OCP)."""
        key = (portal_name or "").strip().lower()
        if not key:
            raise ValueError("El nombre del portal no puede estar vacío.")
        if not issubclass(crawler_cls, AsyncCrawler):
            raise TypeError(f"{crawler_cls.__name__} debe heredar de AsyncCrawler.")
        cls._registry[key] = crawler_cls

    @classmethod
    def create_crawler(cls, portal_name: str, **kwargs) -> AsyncCrawler:
        """Instancia y retorna el `AsyncCrawler` configurado para el portal solicitado."""
        key = (portal_name or "").strip().lower()
        crawler_cls = cls._registry.get(key)
        if not crawler_cls:
            available = ", ".join(cls.available_portals())
            raise ValueError(
                f"Portal '{portal_name}' no soportado. Portales registrados: [{available}]."
            )
        return crawler_cls(**kwargs)

    @classmethod
    def available_portals(cls) -> list[str]:
        """Retorna la lista de identificadores de portales registrados."""
        return list(cls._registry.keys())
