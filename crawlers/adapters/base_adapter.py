"""
base_adapter.py — Patrón GoF Adapter (Interfaz Target `PropertyDataAdapter`).

Desacopla la estructura JSON nativa y heterogénea de cada portal inmobiliario
respecto al esquema canónico `PropertyCreate`, aplicando el filtro de trazabilidad
obligatoria RN-06 (`url_origen` válida) y cumpliendo el Principio de
Responsabilidad Única (SRP).
"""

from abc import ABC, abstractmethod
from typing import Optional

from crawlers.constants import COMUNA_SLUG_TO_CANONICAL
from crawlers.schemas import PropertyCreate


class PropertyDataAdapter(ABC):
    """
    Interfaz Target del Patrón Adapter (Ficha 2 GoF).
    Cada portal implementa su propio adaptador concreto para traducir su
    payload JSON crudo a `PropertyCreate`.
    """

    @abstractmethod
    def adapt(self, raw_data: dict, search_zone: str = "") -> Optional[PropertyCreate]:
        """
        Convierte un diccionario crudo extraído del portal al DTO canónico
        `PropertyCreate`. Retorna `None` si el registro incumple RN-06
        (carece de `url_origen`) o no tiene un canon de arrendamiento válido.
        """
        ...

    def adapt_many(
        self, raw_items: list[tuple[dict, str]]
    ) -> tuple[list[PropertyCreate], int]:
        """
        Adapta un lote de tuplas `(raw_dict, search_zone)`.

        Returns:
            Tupla `(valid_items, rejected_count)`.
        """
        valid_items: list[PropertyCreate] = []
        rejected_count = 0

        for raw_dict, search_zone in raw_items:
            adapted = self.adapt(raw_dict, search_zone=search_zone)
            if adapted is None:
                rejected_count += 1
            else:
                valid_items.append(adapted)

        return valid_items, rejected_count

    @staticmethod
    def normalize_comuna_seed(search_zone: str) -> str:
        """
        Normaliza el slug de búsqueda a la comuna canónica en Medellín
        (ej. 'laureles' y 'estadio' -> 'laureles estadio') sin ejecutar
        procesamiento geoespacial pesado (responsabilidad de ml_service).
        """
        slug = (search_zone or "").strip().lower()
        return COMUNA_SLUG_TO_CANONICAL.get(slug, slug.replace("-", " "))

    @staticmethod
    def safe_float(value) -> Optional[float]:
        """Convierte un valor numérico positivo o cero a float de forma segura."""
        try:
            if value is None or value == "":
                return None
            parsed = float(value)
            return parsed if parsed >= 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def safe_coord(value) -> Optional[float]:
        """Convierte coordenadas geográficas (latitud/longitud con signo) a float."""
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def safe_int(value) -> Optional[int]:
        """Convierte un valor a int de forma segura."""
        try:
            if value is None or value == "":
                return None
            return int(float(value))
        except (ValueError, TypeError):
            return None
