"""
base.py — Clase base abstracta `AsyncCrawler` (Producto Abstracto de Factory Method).

Responsabilidad Única (SRP):
  Gestionar el transporte HTTP asíncrono (`httpx.AsyncClient`), el control de
  concurrencia (`asyncio.Semaphore`), los reintentos con *exponential backoff*
  ante fallos transitorios de red, y delegar la transformación del JSON crudo
  al `PropertyDataAdapter` correspondiente (Patrón Adapter).

Nota SOLID (ISP / SRP):
  Se eliminó `to_csv()` de esta clase; los crawlers extraen exclusivamente en
  memoria devolviendo objetos validados `PropertyCreate`.
"""

import asyncio
import logging
import ssl
from abc import ABC, abstractmethod
from typing import Optional

import httpx
import truststore

from crawlers.adapters.base_adapter import PropertyDataAdapter
from crawlers.constants import USER_AGENT
from crawlers.schemas import PropertyCreate

logger = logging.getLogger(__name__)

# Timeout por petición: 30s total, 10s para establecer conexión
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Contexto SSL del sistema operativo instanciado una sola vez a nivel de módulo
_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class AsyncCrawler(ABC):
    """
    Producto Abstracto del Patrón Factory Method (Ficha 1 GoF).
    Cada spider concreto implementa `fetch_raw()` y declara su `adapter`.
    """

    name: str = ""

    def __init__(
        self,
        adapter: PropertyDataAdapter,
        concurrency: int = 10,
        delay: float = 0.15,
        max_retries: int = 2,
        max_zones: Optional[int] = None,
    ) -> None:
        """
        Args:
            adapter:     Instancia de `PropertyDataAdapter` para traducir el JSON nativo.
            concurrency: Número máximo de peticiones HTTP simultáneas por portal.
            delay:       Pausa de cortesía (segundos) entre peticiones.
            max_retries: Reintentos automáticos con exponential backoff ante errores 5xx/red.
            max_zones:   Límite opcional de zonas/comunas a consultar (útil para pruebas rápidas).
        """
        self.adapter = adapter
        self.concurrency = concurrency
        self.delay = delay
        self.max_retries = max_retries
        self.max_zones = max_zones
        self._semaphore = asyncio.Semaphore(concurrency)

        # Métricas de la última corrida para auditoría (RNF-09)
        self.last_raw_count: int = 0
        self.last_rejected_count: int = 0

    # ------------------------------------------------------------------
    # Interfaz pública
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch_raw(self) -> list[tuple[dict, str]]:
        """
        Extrae los diccionarios JSON crudos desde la API del portal.

        Returns:
            Lista de tuplas `(raw_dict, search_zone_slug)`.
        """
        ...

    async def run(self) -> list[PropertyCreate]:
        """
        Ejecuta la extracción HTTP (`fetch_raw`) y delega la normalización y
        el filtrado RN-06 al `PropertyDataAdapter`.

        Returns:
            Lista de esquemas `PropertyCreate` validados.
        """
        raw_items = await self.fetch_raw()
        self.last_raw_count = len(raw_items)

        valid_items, rejected_count = self.adapter.adapt_many(raw_items)
        self.last_rejected_count = rejected_count

        logger.info(
            "[%s] Extraídos=%d | Válidos (RN-06)=%d | Descartados=%d",
            self.name,
            self.last_raw_count,
            len(valid_items),
            self.last_rejected_count,
        )
        return valid_items

    # ------------------------------------------------------------------
    # Helpers internos de HTTP con concurrencia y reintentos
    # ------------------------------------------------------------------

    def _build_client(self) -> httpx.AsyncClient:
        """Crea el cliente HTTP compartido reutilizando `_SSL_CONTEXT`."""
        return httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"user-agent": USER_AGENT},
            verify=_SSL_CONTEXT,
            limits=httpx.Limits(
                max_connections=self.concurrency,
                max_keepalive_connections=self.concurrency,
            ),
        )

    async def _request_with_retry(
        self,
        method: str,
        client: httpx.AsyncClient,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Ejecuta una petición HTTP regulada por semáforo con reintentos y
        *exponential backoff* para errores transitorios (Timeouts, 429, 5xx).
        """
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                backoff = 0.5 * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

            async with self._semaphore:
                if self.delay > 0:
                    await asyncio.sleep(self.delay)
                try:
                    response = await client.request(method, url, **kwargs)
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                        logger.warning(
                            "[%s] HTTP %d en %s (reintento %d/%d)",
                            self.name,
                            response.status_code,
                            url,
                            attempt + 1,
                            self.max_retries,
                        )
                        continue
                    response.raise_for_status()
                    return response
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                    last_exc = exc
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500 and exc.response.status_code != 429:
                        raise
                    if attempt < self.max_retries:
                        logger.warning(
                            "[%s] Error de red en %s: %s (reintento %d/%d)",
                            self.name,
                            url,
                            exc,
                            attempt + 1,
                            self.max_retries,
                        )

        assert last_exc is not None
        raise last_exc

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """GET asíncrono con control de concurrencia y reintentos."""
        return await self._request_with_retry("GET", client, url, **kwargs)

    async def _post(
        self,
        client: httpx.AsyncClient,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """POST asíncrono con control de concurrencia y reintentos."""
        return await self._request_with_retry("POST", client, url, **kwargs)
