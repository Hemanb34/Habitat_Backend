"""
spiders/__init__.py — Exporta los spiders concretos por portal.
"""

from crawlers.spiders.ciencuadras_spider import CiencuadrasCrawler
from crawlers.spiders.fincaraiz_spider import FincaraizCrawler
from crawlers.spiders.metrocuadrado_spider import MetrocuadradoCrawler

__all__ = [
    "MetrocuadradoCrawler",
    "FincaraizCrawler",
    "CiencuadrasCrawler",
]
