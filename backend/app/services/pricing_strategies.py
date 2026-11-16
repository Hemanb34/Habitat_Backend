"""Patrón GoF Strategy: Estrategias Comerciales de Publicación (Capa Service - <<service>>).

Implementa el 5.º Patrón GoF del MVP (Comportamiento - Strategy) para la
funcionalidad F4 (Obtener Margen Sugerido de Publicación, RF-06 y RN-04).

Permite intercambiar en tiempo de ejecución el algoritmo financiero de
fijación del canon sugerido sin condicionales monolíticos (Principio SOLID OCP):
1. `LiquidityPricingStrategy`: Límite inferior (-5% por RN-04) modulado contra
   el piso competitivo del sector para acelerar la colocación.
2. `ProfitabilityPricingStrategy`: Límite superior (+5% por RN-04) modulado
   contra el techo competitivo del sector para maximizar el retorno mensual.
3. `MarketBalancedPricingStrategy`: Ponderación 60% Estimación IA + 40% Promedio
   de Competidores RN-03 (RF-05).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.domain.schemas.valuation_schemas import (
    EstrategiaComercialKey,
    MarketMetricsSchema,
    PricingRecommendationSchema,
)


class PricingStrategy(ABC):
    """Interfaz <<interface>> Strategy para algoritmos de recomendación de precios (RN-04)."""

    @abstractmethod
    def calcular_margen(
        self,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> PricingRecommendationSchema:
        """Calcula el precio sugerido y los límites comerciales según la estrategia."""


class LiquidityPricingStrategy(PricingStrategy):
    """ConcreteStrategy 1: Liquidez Rápida (-5% RN-04, respetando el piso del sector)."""

    def calcular_margen(
        self,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> PricingRecommendationSchema:
        banda_inferior_rn04 = round(precio_base * 0.95, 0)
        piso_mercado = metricas_mercado.precio_minimo

        # Respeta el piso de mercado si este es superior al -5%, sin superar el precio base
        if piso_mercado > 0:
            precio_sugerido = min(precio_base, max(banda_inferior_rn04, piso_mercado))
        else:
            precio_sugerido = banda_inferior_rn04

        precio_sugerido = round(precio_sugerido, 0)
        ajuste_pct = round(((precio_sugerido - precio_base) / precio_base) * 100.0, 1)

        return PricingRecommendationSchema(
            clave="liquidez",
            nombre_estrategia="Liquidez Rápida (-5%)",
            objetivo_comercial="Arrendar en el menor tiempo posible reduciendo días de vacancia",
            precio_sugerido=precio_sugerido,
            limite_inferior=banda_inferior_rn04,
            limite_superior=round(precio_base, 0),
            ajuste_aplicado_pct=ajuste_pct,
            explicacion=(
                "Aplica el margen inferior de -5% (RN-04) sobre la estimación IA, "
                "modulándolo contra el precio mínimo de los competidores del sector."
            ),
        )


class ProfitabilityPricingStrategy(PricingStrategy):
    """ConcreteStrategy 2: Máxima Rentabilidad (+5% RN-04, respetando el techo del sector)."""

    def calcular_margen(
        self,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> PricingRecommendationSchema:
        banda_superior_rn04 = round(precio_base * 1.05, 0)
        techo_mercado = metricas_mercado.precio_maximo

        # Evita quedar fuera de mercado si el techo de competidores es inferior a +5%
        if techo_mercado > 0:
            precio_sugerido = max(precio_base, min(banda_superior_rn04, techo_mercado))
        else:
            precio_sugerido = banda_superior_rn04

        precio_sugerido = round(precio_sugerido, 0)
        ajuste_pct = round(((precio_sugerido - precio_base) / precio_base) * 100.0, 1)

        return PricingRecommendationSchema(
            clave="rentabilidad",
            nombre_estrategia="Máxima Rentabilidad (+5%)",
            objetivo_comercial="Maximizar el canon mensual sin exceder el techo competitivo",
            precio_sugerido=precio_sugerido,
            limite_inferior=round(precio_base, 0),
            limite_superior=banda_superior_rn04,
            ajuste_aplicado_pct=ajuste_pct,
            explicacion=(
                "Aplica el margen superior de +5% (RN-04) sobre la estimación IA, "
                "acotado por el precio máximo observado en los competidores RN-03."
            ),
        )


class MarketBalancedPricingStrategy(PricingStrategy):
    """ConcreteStrategy 3: Balanceada de Mercado (60% IA + 40% Promedio Competidores RF-05)."""

    def calcular_margen(
        self,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> PricingRecommendationSchema:
        banda_inferior_rn04 = round(precio_base * 0.95, 0)
        banda_superior_rn04 = round(precio_base * 1.05, 0)
        promedio_sector = (
            metricas_mercado.precio_promedio
            if metricas_mercado.precio_promedio > 0
            else precio_base
        )

        # Ponderación 60% IA + 40% mercado, acotada dentro de la banda RN-04 (±5%)
        ponderado = (precio_base * 0.60) + (promedio_sector * 0.40)
        precio_sugerido = round(
            min(banda_superior_rn04, max(banda_inferior_rn04, ponderado)),
            0,
        )
        ajuste_pct = round(((precio_sugerido - precio_base) / precio_base) * 100.0, 1)

        return PricingRecommendationSchema(
            clave="balanceada",
            nombre_estrategia="Balanceada de Mercado",
            objetivo_comercial="Equilibrio óptimo entre velocidad de arriendo y retorno mensual",
            precio_sugerido=precio_sugerido,
            limite_inferior=banda_inferior_rn04,
            limite_superior=banda_superior_rn04,
            ajuste_aplicado_pct=ajuste_pct,
            explicacion=(
                "Combina 60% de la valoración IA con 40% del promedio real de "
                "competidores comparables (RF-05), manteniéndose dentro de la banda ±5% (RN-04)."
            ),
        )


class PricingMarginCalculator:
    """Contexto (Context) del Patrón GoF Strategy.

    Mantiene una referencia a una `PricingStrategy` y permite cambiarla
    dinámicamente en tiempo de ejecución mediante `set_strategy()`.
    """

    _CATALOGO_ESTRATEGIAS: dict[EstrategiaComercialKey, PricingStrategy] = {
        "liquidez": LiquidityPricingStrategy(),
        "balanceada": MarketBalancedPricingStrategy(),
        "rentabilidad": ProfitabilityPricingStrategy(),
    }

    def __init__(self, strategy: PricingStrategy | None = None) -> None:
        self._strategy: PricingStrategy = strategy or MarketBalancedPricingStrategy()

    def set_strategy(self, strategy: PricingStrategy) -> None:
        """Cambia en caliente la estrategia algorítmica activa."""
        self._strategy = strategy

    def calcular_rango(
        self,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> PricingRecommendationSchema:
        """Delega el cálculo a la estrategia actualmente configurada."""
        return self._strategy.calcular_margen(precio_base, metricas_mercado)

    def calcular_por_clave(
        self,
        clave: EstrategiaComercialKey,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> PricingRecommendationSchema:
        """Selecciona la estrategia por su clave e invoca `calcular_rango`."""
        estrategia = self._CATALOGO_ESTRATEGIAS[clave]
        self.set_strategy(estrategia)
        return self.calcular_rango(precio_base, metricas_mercado)

    def evaluar_todas_las_estrategias(
        self,
        precio_base: float,
        metricas_mercado: MarketMetricsSchema,
    ) -> dict[EstrategiaComercialKey, PricingRecommendationSchema]:
        """Evalúa las 3 estrategias comerciales para entrega inmediata al Frontend."""
        resultado: dict[EstrategiaComercialKey, PricingRecommendationSchema] = {}
        for clave, estrategia in self._CATALOGO_ESTRATEGIAS.items():
            self.set_strategy(estrategia)
            resultado[clave] = self.calcular_rango(precio_base, metricas_mercado)
        return resultado
