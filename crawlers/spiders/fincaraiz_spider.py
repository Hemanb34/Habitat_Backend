"""
fincaraiz_spider.py — Spider asíncrono para fincaraiz.com.co (SRP).

Responsabilidad Única:
  Resolver los IDs de ubicación (desde `spiders/cache/fincaraiz_locations.json`
  o vía autocomplete) y paginar en paralelo `/api/v1/properties/search`
  retornando los JSON crudos. La normalización la realiza `FincaraizAdapter`.
"""

import asyncio
import json
import logging
import math
import unicodedata
from pathlib import Path
from typing import Optional

import httpx

from crawlers.adapters.fincaraiz_adapter import FincaraizAdapter
from crawlers.base import AsyncCrawler
from crawlers.constants import SEARCH_ZONES_MEDELLIN

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / "cache"
_LOCATIONS_CACHE = _CACHE_DIR / "fincaraiz_locations.json"


def _normalize_ascii(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
        .lower()
    )


class FincaraizCrawler(AsyncCrawler):
    """Spider concreto para FincaRaíz."""

    name = "fincaraiz"

    AUTOCOMPLETE_URL = (
        "https://search-service.fincaraiz.com.co/api/v1/locations/infofinca-autocomplete"
    )
    SEARCH_URL = "https://search-service.fincaraiz.com.co/api/v1/properties/search"

    ESTATE = {
        "name": "Antioquia",
        "id": "2d63ee80-421b-488f-992a-0e07a3264c3e",
        "slug": "state-colombia-05-antioquia",
    }

    ROWS = 21

    SOLO_BARRIO = {
        "robledo",
        "laureles",
        "estadio",
        "la-america",
        "el-poblado",
        "belen",
    }

    def __init__(
        self,
        concurrency: int = 25,
        delay: float = 0.04,
        force_refresh_cache: bool = False,
        max_zones: Optional[int] = None,
    ) -> None:
        super().__init__(
            adapter=FincaraizAdapter(),
            concurrency=concurrency,
            delay=delay,
            max_zones=max_zones,
        )
        self.force_refresh_cache = force_refresh_cache

    async def fetch_raw(self) -> list[tuple[dict, str]]:
        zones = (
            SEARCH_ZONES_MEDELLIN[: self.max_zones]
            if self.max_zones
            else SEARCH_ZONES_MEDELLIN
        )

        async with self._build_client() as client:
            locations = await self._load_locations(client, zones)
            zones_ok = [z for z in zones if z in locations]
            tasks = [
                self._fetch_zone(client, zone, locations[zone])
                for zone in zones_ok
            ]
            results_per_zone = await asyncio.gather(*tasks, return_exceptions=True)

        raw_items: list[tuple[dict, str]] = []
        for zone, result in zip(zones_ok, results_per_zone):
            if isinstance(result, Exception):
                logger.error("[fincaraiz] %s -> error: %s", zone, result)
                continue
            raw_items.extend(result)

        return raw_items

    async def _load_locations(
        self, client: httpx.AsyncClient, target_zones: list[str]
    ) -> dict:
        cache: dict = {}

        if not self.force_refresh_cache and _LOCATIONS_CACHE.exists():
            cache = json.loads(_LOCATIONS_CACHE.read_text(encoding="utf-8"))

        missing = [z for z in target_zones if z not in cache]
        if missing:
            logger.info("[fincaraiz] Resolviendo %d ubicaciones vía autocomplete", len(missing))
            tasks = [self._resolve_location(client, z) for z in missing]
            resolved = await asyncio.gather(*tasks, return_exceptions=True)

            for zone, result in zip(missing, resolved):
                if isinstance(result, Exception):
                    logger.error("[fincaraiz] Error resolviendo '%s': %s", zone, result)
                elif result is not None:
                    cache[zone] = result

            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _LOCATIONS_CACHE.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return cache

    async def _resolve_location(
        self, client: httpx.AsyncClient, zone: str
    ) -> Optional[dict]:
        nombre = zone.replace("-", " ")
        try:
            response = await self._post(
                client,
                self.AUTOCOMPLETE_URL,
                json={
                    "operationName": "Location",
                    "variables": {"strSearch": nombre},
                    "query": "",
                },
                headers=self._autocomplete_headers(zone),
            )
        except Exception as exc:
            logger.error("[fincaraiz] Autocomplete '%s' -> %s", zone, exc)
            return None

        results = (response.json().get("data") or {}).get("searchLocation") or []
        objetivo = _normalize_ascii(nombre)
        match = None

        if zone not in self.SOLO_BARRIO:
            for loc in results:
                if loc.get("type") != "COMMUNE":
                    continue
                ciudades = [c.get("name", "") for c in (loc.get("city") or [])]
                if any(c in ("Medellín", "Medellin") for c in ciudades):
                    match = loc
                    break

        if not match:
            for loc in results:
                if loc.get("type") != "NEIGHBOURHOOD":
                    continue
                ciudades = [c.get("name", "") for c in (loc.get("city") or [])]
                if not any(c in ("Medellín", "Medellin") for c in ciudades):
                    continue
                if _normalize_ascii(loc.get("name", "")) == objetivo:
                    match = loc
                    break

        if not match:
            return None

        entry: dict = {
            "type": match["type"],
            "id": match["id"],
            "name": match["name"],
            "estate": match.get("estate") or self.ESTATE,
        }
        if match["type"] != "COMMUNE":
            if match.get("city"):
                entry["city"] = match["city"]
            if match.get("slug"):
                entry["slug"] = match["slug"]
        return entry

    async def _fetch_zone(
        self,
        client: httpx.AsyncClient,
        zone: str,
        location_entry: dict,
    ) -> list[tuple[dict, str]]:
        try:
            data = await self._fetch_page(client, zone, location_entry, page=1)
        except Exception as exc:
            logger.error("[fincaraiz] %s / p1 -> %s", zone, exc)
            return []

        hits_block = data.get("hits") or {}
        total = (hits_block.get("total") or {}).get("value", 0)
        hits = hits_block.get("hits") or []

        collected: list[tuple[dict, str]] = [
            ((h.get("_source") or {}).get("listing") or {}, zone)
            for h in hits
        ]

        total_pages = math.ceil(total / self.ROWS) if total else 1
        if total_pages <= 1:
            return collected

        tasks = [
            self._fetch_page(client, zone, location_entry, page=p)
            for p in range(2, total_pages + 1)
        ]
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for page_num, page_data in zip(range(2, total_pages + 1), pages):
            if isinstance(page_data, Exception):
                logger.error("[fincaraiz] %s / p%d -> %s", zone, page_num, page_data)
                continue
            for h in (page_data.get("hits") or {}).get("hits") or []:
                listing = (h.get("_source") or {}).get("listing") or {}
                collected.append((listing, zone))

        return collected

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        zone: str,
        location_entry: dict,
        page: int,
    ) -> dict:
        response = await self._post(
            client,
            self.SEARCH_URL,
            json={
                "variables": {
                    "rows": self.ROWS,
                    "params": {
                        "page": page,
                        "order": 2,
                        "bedroomsExactMode": False,
                        "bathroomsExactMode": False,
                        "roomsExactMode": False,
                        "operation_type_id": 2,
                        "property_type_id": [1, 2, 14],
                        "locations": [location_entry],
                        "currencyID": 4,
                        "m2Currency": 4,
                    },
                    "page": page,
                    "source": 10,
                },
                "query": "",
            },
            headers=self._search_headers(zone),
        )
        return response.json()

    @staticmethod
    def _autocomplete_headers(zone: str) -> dict:
        return {
            "accept": "*/*",
            "accept-language": "es-419,es;q=0.9,en;q=0.8",
            "content-type": "application/json",
            "origin": "https://www.fincaraiz.com.co",
            "referer": (
                "https://www.fincaraiz.com.co/arriendo/"
                f"casas-y-apartamentos-y-apartaestudios/{zone}/medellin"
            ),
            "x-origin": "www.fincaraiz.com.co",
        }

    def _search_headers(self, zone: str) -> dict:
        return {**self._autocomplete_headers(zone), "x-ranking": "v2"}
