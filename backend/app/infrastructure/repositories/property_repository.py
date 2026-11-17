"""Implementación SQLAlchemy del repositorio de Inmuebles (Capa Infrastructure).

Ejecuta consultas indexadas sobre la tabla `properties` en PostgreSQL
cumpliendo con:
- RNF-04: Tiempo de respuesta <= 2 segundos en búsquedas y filtros de catálogo.
- RN-03: Filtrado por los 4 criterios de comparabilidad (comuna, estrato,
         tipo_inmueble y área ±15%).
- RN-06: Garantía de trazabilidad por `url_origen`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.app.domain.entities.property_entity import Inmueble
from backend.app.domain.interfaces.repositories import IPropertyRepository
from backend.app.domain.schemas.property_schemas import OrdenCatalogo


class PropertyRepository(IPropertyRepository):
    """Repositorio concreto SQLAlchemy para la entidad `Inmueble`."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def listar_catalogo(
        self,
        comuna: str | None = None,
        tipo_inmueble: str | None = None,
        ordenar_por: OrdenCatalogo = "mejor-oferta",
        limit: int = 60,
        offset: int = 0,
    ) -> tuple[list[Inmueble], int]:
        """Consulta el catálogo aplicando filtros y ordenamiento directo en PostgreSQL."""
        stmt = select(Inmueble)
        count_stmt = select(func.count(Inmueble.id))

        if comuna and comuna.strip().lower() not in ("", "todos"):
            comuna_clean = comuna.strip().lower()
            stmt = stmt.where(func.lower(Inmueble.comuna) == comuna_clean)
            count_stmt = count_stmt.where(func.lower(Inmueble.comuna) == comuna_clean)

        if tipo_inmueble and tipo_inmueble.strip().lower() not in ("", "todos"):
            tipo_clean = tipo_inmueble.strip().lower()
            stmt = stmt.where(func.lower(Inmueble.tipo_inmueble) == tipo_clean)
            count_stmt = count_stmt.where(func.lower(Inmueble.tipo_inmueble) == tipo_clean)

        total: int = self._db.execute(count_stmt).scalar_one()

        # Ordenamiento en el motor relacional
        if ordenar_por == "mejor-oferta":
            # Mayor porcentaje de ahorro ((precio_estimado - precio_publicado) / precio_estimado) primero
            ahorro_relativo = (
                Inmueble.precio_estimado - Inmueble.precio_publicado
            ) / func.nullif(Inmueble.precio_estimado, 0.0)
            stmt = stmt.order_by(ahorro_relativo.desc(), Inmueble.id.asc())
        elif ordenar_por == "menor-precio":
            stmt = stmt.order_by(Inmueble.precio_publicado.asc(), Inmueble.id.asc())
        elif ordenar_por == "mayor-area":
            stmt = stmt.order_by(Inmueble.area.desc(), Inmueble.id.asc())

        stmt = stmt.offset(offset).limit(limit)
        items = list(self._db.execute(stmt).scalars().all())
        return items, total

    def obtener_filtros_disponibles(self) -> tuple[list[str], list[str]]:
        """Devuelve la lista ordenada de comunas y tipos de inmueble presentes en la BD."""
        comunas_stmt = (
            select(Inmueble.comuna)
            .distinct()
            .order_by(Inmueble.comuna.asc())
        )
        tipos_stmt = (
            select(Inmueble.tipo_inmueble)
            .distinct()
            .order_by(Inmueble.tipo_inmueble.asc())
        )
        comunas = [row for row in self._db.execute(comunas_stmt).scalars().all() if row]
        tipos = [row for row in self._db.execute(tipos_stmt).scalars().all() if row]
        return comunas, tipos

    def buscar_similares_rn03(
        self,
        comuna: str,
        estrato: int,
        tipo_inmueble: str,
        area_base: float,
        limit: int = 10,
    ) -> Sequence[Inmueble]:
        """Busca inmuebles competidores usando el índice compuesto `ix_properties_rn03_comparables`.

        Aplica los 4 criterios de RN-03 en SQL y verifica el invariante en la entidad.
        """
        area_min = area_base * 0.85
        area_max = area_base * 1.15

        stmt = (
            select(Inmueble)
            .where(
                func.lower(Inmueble.comuna) == comuna.strip().lower(),
                Inmueble.estrato == estrato,
                func.lower(Inmueble.tipo_inmueble) == tipo_inmueble.strip().lower(),
                Inmueble.area >= area_min,
                Inmueble.area <= area_max,
            )
            .order_by(func.abs(Inmueble.area - area_base).asc())
            .limit(limit)
        )
        candidatos = list(self._db.execute(stmt).scalars().all())
        return [
            inm
            for inm in candidatos
            if inm.es_comparable_con(comuna, estrato, tipo_inmueble, area_base)
        ]

    def contar_por_portal(self) -> dict[str, int]:
        """Devuelve cuántos inmuebles activos existen por cada portal en PostgreSQL."""
        stmt = select(Inmueble.portal, func.count(Inmueble.id)).group_by(Inmueble.portal)
        filas = self._db.execute(stmt).all()
        return {str(portal): int(total) for portal, total in filas}

    def upsert_lote_propiedades(
        self,
        nuevas_entidades: Sequence[Inmueble],
    ) -> tuple[int, int]:
        """Renueva transaccionalmente el catálogo de los portales extraídos (Opción 1A).

        1. Deduplica el lote nuevo en memoria por `url_origen` (RN-06).
        2. Si hay registros válidos (> 0), elimina los registros antiguos de los portales
           incluidos en la corrida actual (`DELETE FROM properties WHERE portal IN (...)`)
           para garantizar que no queden anuncios dados de baja ni URLs S3 caducadas.
        3. Inserta en bloque los inmuebles vigentes recién extraídos y hace `commit()` atómico.
        """
        if not nuevas_entidades:
            return 0, 0

        # 1. Deduplicar en memoria por `url_origen` conservando la última aparición válida
        por_url: dict[str, Inmueble] = {}
        for item in nuevas_entidades:
            url = (item.url_origen or "").strip()
            if url:
                por_url[url] = item

        if not por_url:
            return 0, 0

        # 2. Identificar los portales presentes en este lote y eliminar sus registros anteriores
        portales_en_lote = sorted({item.portal for item in por_url.values() if item.portal})
        reemplazados_previos: int = (
            self._db.execute(
                select(func.count(Inmueble.id)).where(
                    Inmueble.portal.in_(portales_en_lote)
                )
            ).scalar_one()
            if portales_en_lote
            else 0
        )

        if portales_en_lote:
            self._db.execute(
                delete(Inmueble).where(Inmueble.portal.in_(portales_en_lote))
            )

        # 3. Insertar en bloques de 2.000 los inmuebles vigentes normalizando cualquier imagen S3 legada
        ahora_utc = datetime.now(timezone.utc)
        filas_dict = []
        for url, item in por_url.items():
            img_clean = item.imagen_url
            if img_clean:
                img_clean = (
                    img_clean.strip()
                    .replace(
                        "https://www-img-cc.s3.amazonaws.com/",
                        "https://www.ciencuadras.com/",
                    )
                    .replace(
                        "http://www-img-cc.s3.amazonaws.com/",
                        "https://www.ciencuadras.com/",
                    )
                )
                if img_clean.startswith("http://"):
                    img_clean = "https://" + img_clean[len("http://") :]

            filas_dict.append(
                {
                    "portal": item.portal,
                    "title": item.title,
                    "tipo_inmueble": item.tipo_inmueble,
                    "area": item.area,
                    "estrato": item.estrato,
                    "comuna": item.comuna,
                    "barrio": item.barrio,
                    "habitaciones": item.habitaciones,
                    "banos": item.banos,
                    "parqueaderos": item.parqueaderos,
                    "estado": item.estado or "Usado",
                    "precio_publicado": item.precio_publicado,
                    "precio_estimado": item.precio_estimado,
                    "valor_administracion": item.valor_administracion,
                    "incluye_administracion": bool(item.incluye_administracion),
                    "amoblado": bool(item.amoblado),
                    "imagen_url": img_clean,
                    "url_origen": url,
                    "latitud": item.latitud,
                    "longitud": item.longitud,
                    "antiguedad": item.antiguedad,
                    "fecha_extraccion": item.fecha_extraccion or ahora_utc,
                }
            )

        tamano_bloque = 2000
        for i in range(0, len(filas_dict), tamano_bloque):
            lote = filas_dict[i : i + tamano_bloque]
            stmt = pg_insert(Inmueble).values(lote).on_conflict_do_nothing(
                index_elements=["url_origen"]
            )
            self._db.execute(stmt)

        self._db.commit()
        insertados = len(filas_dict)
        return insertados, reemplazados_previos
