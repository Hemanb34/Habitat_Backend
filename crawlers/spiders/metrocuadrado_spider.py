"""
metrocuadrado_spider.py — Spider asíncrono para metrocuadrado.com (SRP).

Responsabilidad Única:
  Paginar de forma concurrente el endpoint `/rest-search/search` de
  Metrocuadrado por cada semilla de zona y retornar los JSON crudos.
  La traducción al modelo de dominio la realiza `MetrocuadradoAdapter`.
"""

import asyncio
import logging
from typing import Optional

import httpx

from crawlers.adapters.metrocuadrado_adapter import MetrocuadradoAdapter
from crawlers.base import AsyncCrawler
from crawlers.constants import METROCUADRADO_API_KEY, SEARCH_ZONES_MEDELLIN

logger = logging.getLogger(__name__)


class MetrocuadradoCrawler(AsyncCrawler):
    """Spider concreto para Metrocuadrado."""

    name = "metrocuadrado"

    API_URL = "https://www.metrocuadrado.com/rest-search/search"
    PAGE_SIZE = 50

    def __init__(
        self,
        concurrency: int = 20,
        delay: float = 0.05,
        max_zones: Optional[int] = None,
    ) -> None:
        super().__init__(
            adapter=MetrocuadradoAdapter(),
            concurrency=concurrency,
            delay=delay,
            max_zones=max_zones,
        )

    async def fetch_raw(self) -> list[tuple[dict, str]]:
        zones = (
            SEARCH_ZONES_MEDELLIN[: self.max_zones]
            if self.max_zones
            else SEARCH_ZONES_MEDELLIN
        )

        async with self._build_client() as client:
            tasks = [self._fetch_zone(client, zone) for zone in zones]
            results_per_zone = await asyncio.gather(*tasks, return_exceptions=True)

        raw_items: list[tuple[dict, str]] = []
        for zone, result in zip(zones, results_per_zone):
            if isinstance(result, Exception):
                logger.error("[metrocuadrado] %s -> error: %s", zone, result)
                continue
            raw_items.extend(result)

        return raw_items

    async def _fetch_zone(
        self, client: httpx.AsyncClient, zone: str
    ) -> list[tuple[dict, str]]:
        try:
            data = await self._fetch_page(client, zone, offset=0)
        except Exception as exc:
            logger.error("[metrocuadrado] %s / offset=0: %s", zone, exc)
            return []

        first_results = data.get("results") or []
        total = data.get("totalHits") or 0
        collected: list[tuple[dict, str]] = [(prop, zone) for prop in first_results]

        if not total or total <= self.PAGE_SIZE:
            return collected

        offsets = list(range(self.PAGE_SIZE, total, self.PAGE_SIZE))
        tasks = [self._fetch_page(client, zone, offset) for offset in offsets]
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for offset, page_result in zip(offsets, pages):
            if isinstance(page_result, Exception):
                logger.error(
                    "[metrocuadrado] %s / offset=%d: %s", zone, offset, page_result
                )
                continue
            for prop in page_result.get("results") or []:
                collected.append((prop, zone))

        return collected

    async def _fetch_page(
        self, client: httpx.AsyncClient, zone: str, offset: int
    ) -> dict:
        response = await self._get(
            client,
            self.API_URL,
            params={
                "size": self.PAGE_SIZE,
                "from": offset,
                "realEstateTypeList": "apartamento,apartaestudio,casa",
                "realEstateBusinessList": "arriendo",
                "city": "medellin",
                "neighborhood": zone,
            },
            headers={
                "accept": "*/*",
                "accept-language": "es-419,es;q=0.9,en;q=0.8",
                "referer": (
                    f"https://www.metrocuadrado.com/apartamento-apartaestudio-casa"
                    f"/arriendo/medellin/{zone}/?search=form"
                ),
                "x-api-key": METROCUADRADO_API_KEY,
            },
        )
        return response.json()
