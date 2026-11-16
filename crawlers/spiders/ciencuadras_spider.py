"""
ciencuadras_spider.py — Spider asíncrono para ciencuadras.com (SRP).

Responsabilidad Única:
  Autenticarse con OAuth2 `client_credentials` por instancia, paginar por
  localidad en `/prod/search-results/v1` y retornar los JSON crudos.
  La normalización y el filtrado RN-06 los realiza `CiencuadrasAdapter`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from typing import Optional

import httpx

from crawlers.adapters.ciencuadras_adapter import CiencuadrasAdapter
from crawlers.base import AsyncCrawler
from crawlers.constants import CIENCUADRAS_BASIC_AUTH, USER_AGENT

logger = logging.getLogger(__name__)


class CiencuadrasCrawler(AsyncCrawler):
    """Spider concreto para CienCuadras."""

    name = "ciencuadras"

    TOKEN_URL = "https://prod-api-auth.ciencuadras.com/"
    SEARCH_URL = "https://api-backend.ciencuadras.com/prod/search-results/v1"
    ROWS = 45

    LOCALIDADES: dict[str, str] = {
        "popular": "Popular",
        "santa-cruz": "Santa Cruz",
        "manrique": "Manrique",
        "aranjuez": "Aranjuez",
        "castilla": "Castilla",
        "doce-de-octubre": "Doce de Octubre",
        "robledo": "Robledo",
        "villa-hermosa": "Villa Hermosa",
        "buenos-aires": "Buenos Aires",
        "la-candelaria": "La Candelaria",
        "laureles-estadio": "Laureles Estadio",
        "la-america": "La América",
        "san-javier": "San Javier",
        "el-poblado": "El Poblado",
        "guayabal": "Guayabal",
        "belen": "Belén",
    }

    def __init__(
        self,
        concurrency: int = 20,
        delay: float = 0.05,
        max_zones: Optional[int] = None,
    ) -> None:
        super().__init__(
            adapter=CiencuadrasAdapter(),
            concurrency=concurrency,
            delay=delay,
            max_zones=max_zones,
        )
        # Estado OAuth2 encapsulado a nivel de instancia (evita condiciones de carrera)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock: Optional[asyncio.Lock] = None

    async def fetch_raw(self) -> list[tuple[dict, str]]:
        self._token_lock = asyncio.Lock()

        localidades_items = list(self.LOCALIDADES.items())
        if self.max_zones:
            localidades_items = localidades_items[: self.max_zones]

        async with self._build_client() as client:
            await self._refresh_token(client)

            tasks = [
                self._fetch_localidad(client, slug, nombre)
                for slug, nombre in localidades_items
            ]
            results_by_localidad = await asyncio.gather(*tasks, return_exceptions=True)

        raw_items: list[tuple[dict, str]] = []
        for (slug, _), result in zip(localidades_items, results_by_localidad):
            if isinstance(result, Exception):
                logger.error("[ciencuadras] %s -> error: %s", slug, result)
                continue
            raw_items.extend(result)

        return raw_items

    async def _refresh_token(self, client: httpx.AsyncClient) -> None:
        url = f"{self.TOKEN_URL}?scope=ciencuadras-prod-api-server/read"
        response = await client.post(
            url,
            content=b"grant_type=client_credentials",
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "es-419,es;q=0.9",
                "authorization": f"Basic {CIENCUADRAS_BASIC_AUTH}",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://www.ciencuadras.com",
                "referer": "https://www.ciencuadras.com/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-site",
                "user-agent": USER_AGENT,
            },
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in - 60

    async def _ensure_token(self, client: httpx.AsyncClient) -> None:
        if time.monotonic() < self._token_expires_at:
            return
        assert self._token_lock is not None
        async with self._token_lock:
            if time.monotonic() < self._token_expires_at:
                return
            await self._refresh_token(client)

    def _auth_headers(self) -> dict:
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "es-419,es;q=0.9",
            "authorization": f"Bearer {self._token}",
            "content-type": "application/json",
            "origin": "https://www.ciencuadras.com",
            "referer": "https://www.ciencuadras.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": USER_AGENT,
            "x-ciencuadras-scope": "private",
        }

    async def _fetch_localidad(
        self,
        client: httpx.AsyncClient,
        slug: str,
        localidad: str,
    ) -> list[tuple[dict, str]]:
        try:
            data = await self._fetch_page(client, localidad, from_=0)
        except Exception as exc:
            logger.error("[ciencuadras] %s / p1 -> %s", slug, exc)
            return []

        info = data.get("data") or {}
        total = info.get("total", 0)
        raw_results = info.get("results") or []

        collected: list[tuple[dict, str]] = [(r, slug) for r in raw_results]
        total_pages = math.ceil(total / self.ROWS) if total else 1

        if total_pages <= 1:
            return collected

        # Elasticsearch en CienCuadras limita `from + size <= 10000` (máximo 222 páginas por orden).
        # Para localidades con > 9.990 anuncios (ej. El Poblado), consultamos las primeras 222 páginas
        # con sortOrder="desc" y las páginas restantes con sortOrder="asc" para extraer el 100%.
        max_es_pages = 10000 // self.ROWS  # 222 páginas (9.990 registros)
        desc_pages = min(total_pages, max_es_pages)

        tasks = [
            self._fetch_page(client, localidad, from_=page_idx * self.ROWS, sort_order="desc")
            for page_idx in range(1, desc_pages)
        ]
        if total_pages > max_es_pages:
            extra_pages = min(total_pages - max_es_pages, max_es_pages)
            tasks.extend(
                [
                    self._fetch_page(client, localidad, from_=page_idx * self.ROWS, sort_order="asc")
                    for page_idx in range(0, extra_pages)
                ]
            )

        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for page_num, page_data in enumerate(pages, start=2):
            if isinstance(page_data, Exception):
                logger.error("[ciencuadras] %s / p%d -> %s", slug, page_num, page_data)
                continue
            for r in (page_data.get("data") or {}).get("results") or []:
                collected.append((r, slug))

        return collected

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        localidad: str,
        from_: int,
        sort_order: str = "desc",
    ) -> dict:
        await self._ensure_token(client)
        response = await self._post(
            client,
            self.SEARCH_URL,
            json={
                "size": self.ROWS,
                "sizeMap": 1,
                "transactionType": "arriendo",
                "typeDevice": "desktop",
                "from": from_,
                "project": False,
                "offer": 0,
                "requestId": str(uuid.uuid4()),
                "department": "antioquia",
                "city": "medellín",
                "locality": localidad,
                "sortOrder": sort_order,
                "colombiansAbroad": False,
                "expandSearch": False,
                "realEstateType": ["apartamento", "casa", "apartaestudio"],
                "hasDevolution": False,
            },
            headers=self._auth_headers(),
        )
        return response.json()
