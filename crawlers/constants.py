"""
constants.py — Constantes compartidas para el módulo de Crawlers de Habita.

Define las semillas de búsqueda por zona de Medellín, el mapeo básico de
normalización de comunas (unificando 'laureles' y 'estadio' en Comuna 11
'laureles estadio' sin violar SRP con cálculos geoespaciales pesados),
y configuraciones de red/credenciales públicas leídas por entorno.
"""

import os

# ---------------------------------------------------------------------------
# Semillas de búsqueda (query seeds) usadas para paginar las APIs de los portales.
# Nota: "laureles" y "estadio" se consultan por separado porque FincaRaíz y
# Metrocuadrado los indexan como barrios independientes, pero ambos pertenecen
# a la Comuna 11 ("laureles estadio").
# ---------------------------------------------------------------------------
SEARCH_ZONES_MEDELLIN: list[str] = [
    "popular",
    "santa-cruz",
    "manrique",
    "aranjuez",
    "castilla",
    "doce-de-octubre",
    "robledo",
    "villa-hermosa",
    "buenos-aires",
    "la-candelaria",
    "laureles",
    "estadio",
    "la-america",
    "san-javier",
    "el-poblado",
    "guayabal",
    "belen",
]

# Alias de compatibilidad
COMUNAS_MEDELLIN = SEARCH_ZONES_MEDELLIN

# ---------------------------------------------------------------------------
# Mapeo canónico ligero (sin GeoPandas/OSMnx) de semilla de búsqueda -> comuna.
# La validación geoespacial Point-in-Polygon es responsabilidad exclusiva de
# PreprocesamientoControl en ml_service.
# ---------------------------------------------------------------------------
COMUNA_SLUG_TO_CANONICAL: dict[str, str] = {
    "popular": "popular",
    "santa-cruz": "santa cruz",
    "manrique": "manrique",
    "aranjuez": "aranjuez",
    "castilla": "castilla",
    "doce-de-octubre": "doce de octubre",
    "robledo": "robledo",
    "villa-hermosa": "villa hermosa",
    "buenos-aires": "buenos aires",
    "la-candelaria": "la candelaria",
    "laureles": "laureles estadio",
    "estadio": "laureles estadio",
    "laureles-estadio": "laureles estadio",
    "la-america": "la america",
    "san-javier": "san javier",
    "el-poblado": "el poblado",
    "guayabal": "guayabal",
    "belen": "belen",
}

# ---------------------------------------------------------------------------
# User-Agent compartido y credenciales públicas de APIs de portales
# (configurables mediante variables de entorno).
# ---------------------------------------------------------------------------
USER_AGENT: str = os.getenv(
    "CRAWLER_USER_AGENT",
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
)

METROCUADRADO_API_KEY: str = os.getenv(
    "METROCUADRADO_API_KEY",
    "P1MfFHfQMOtL16Zpg36NcntJYCLFm8FqFfudnavl",
)

CIENCUADRAS_BASIC_AUTH: str = os.getenv(
    "CIENCUADRAS_BASIC_AUTH",
    (
        "M3BiYTRpNmYzMzhiZ3V2ZTlxdnNoN2pkcXU6"
        "c3VwanZzN3NnaWt0YnVvYTQ4aTlrZTA0NGhzNTB2bWJhZ2NyZGcyNWhrMjExdmF2bmty"
    ),
)
