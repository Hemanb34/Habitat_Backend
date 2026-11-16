"""
adapters/__init__.py — Exporta la interfaz `PropertyDataAdapter` y los
adaptadores concretos por portal.
"""

from crawlers.adapters.base_adapter import PropertyDataAdapter
from crawlers.adapters.ciencuadras_adapter import CiencuadrasAdapter
from crawlers.adapters.fincaraiz_adapter import FincaraizAdapter
from crawlers.adapters.metrocuadrado_adapter import MetrocuadradoAdapter

__all__ = [
    "PropertyDataAdapter",
    "MetrocuadradoAdapter",
    "FincaraizAdapter",
    "CiencuadrasAdapter",
]
