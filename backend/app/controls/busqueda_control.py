"""Controlador de caso de uso BusquedaControl (Capa Control - <<control>>).

Orquesta la consulta del catálogo consolidado de inmuebles para el arrendatario (F5 - HU-01),
dependiendo de la abstracción `IPropertyRepository` (Principio SOLID DIP).
"""

from __future__ import annotations

from backend.app.domain.interfaces.repositories import IPropertyRepository
from backend.app.domain.schemas.property_schemas import (
    CatalogResponseSchema,
    OrdenCatalogo,
    PropertyCatalogItemSchema,
)


class BusquedaControl:
    """Orquestador <<control>> para la búsqueda, filtrado y ordenamiento del catálogo."""

    def __init__(self, property_repo: IPropertyRepository) -> None:
        self._property_repo = property_repo

    def consultar_catalogo(
        self,
        comuna: str | None = None,
        tipo_inmueble: str | None = None,
        ordenar_por: OrdenCatalogo = "mejor-oferta",
        limit: int = 60,
        offset: int = 0,
    ) -> CatalogResponseSchema:
        """Ejecuta la consulta filtrada y construye el DTO enriquecido con métricas de oferta IA."""
        entidades, total = self._property_repo.listar_catalogo(
            comuna=comuna,
            tipo_inmueble=tipo_inmueble,
            ordenar_por=ordenar_por,
            limit=limit,
            offset=offset,
        )
        comunas_disponibles, tipos_disponibles = (
            self._property_repo.obtener_filtros_disponibles()
        )

        items_dto = [
            PropertyCatalogItemSchema(
                id=inm.id,
                title=inm.title,
                comuna=inm.comuna,
                barrio=inm.barrio,
                tipo_inmueble=inm.tipo_inmueble,
                area=inm.area,
                habitaciones=inm.habitaciones,
                banos=inm.banos,
                parqueaderos=inm.parqueaderos,
                estrato=inm.estrato,
                precio_publicado=inm.precio_publicado,
                precio_estimado=inm.precio_estimado,
                portal=inm.portal,
                imagen_url=inm.imagen_url,
                url_origen=inm.url_origen,
                amoblado=inm.amoblado,
                incluye_administracion=inm.incluye_administracion,
                valor_administracion=inm.valor_administracion,
                diferencia_pct=inm.diferencia_porcentual_oferta(),
                etiqueta_oferta=inm.etiqueta_calidad_oferta(),
            )
            for inm in entidades
        ]

        return CatalogResponseSchema(
            total=total,
            comunas_disponibles=comunas_disponibles,
            tipos_disponibles=tipos_disponibles,
            items=items_dto,
        )
