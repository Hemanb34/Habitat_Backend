"""
ciencuadras_adapter.py — Adaptador concreto para CienCuadras (Patrón Adapter).

Traduce el objeto JSON nativo devuelto por `/prod/search-results/v1` de
ciencuadras.com al modelo canónico `PropertyCreate`, validando RN-06.
"""

from typing import Optional
from pydantic import ValidationError

from crawlers.adapters.base_adapter import PropertyDataAdapter
from crawlers.schemas import PropertyCreate


class CiencuadrasAdapter(PropertyDataAdapter):
    """Adaptador concreto de CienCuadras -> PropertyCreate."""

    PORTAL_NAME = "ciencuadras"

    @staticmethod
    def _normalize_image_url(raw_img: object) -> Optional[str]:
        """Reescribe URLs legadas del bucket S3 bloqueado (www-img-cc.s3.amazonaws.com) al CDN activo."""
        if not raw_img or not isinstance(raw_img, str):
            return None
        url = raw_img.strip()
        if not url:
            return None
        if url.startswith("/"):
            return f"https://www.ciencuadras.com{url}"
        url = url.replace(
            "https://www-img-cc.s3.amazonaws.com/",
            "https://www.ciencuadras.com/",
        ).replace(
            "http://www-img-cc.s3.amazonaws.com/",
            "https://www.ciencuadras.com/",
        )
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        return url if url.startswith("https://") else None

    def adapt(self, raw_data: dict, search_zone: str = "") -> Optional[PropertyCreate]:
        if not raw_data or not isinstance(raw_data, dict):
            return None

        # Regla RN-06: URL original obligatoria
        link = (raw_data.get("url") or "").strip()
        if not link:
            return None
        url_origen = (
            link
            if link.startswith("http")
            else f"https://www.ciencuadras.com{link}"
        )

        # Canon de arrendamiento obligatorio (> 0)
        precio_publicado = self.safe_float(raw_data.get("rentPrice"))
        if not precio_publicado or precio_publicado <= 0:
            return None

        # Estado derivado de antiquity
        antiquity = self.safe_int(raw_data.get("antiquity"))
        if antiquity is None or antiquity < 0:
            estado = None
        elif antiquity == 0:
            estado = "Nuevo"
        else:
            estado = "Usado"

        comuna_canonica = self.normalize_comuna_seed(search_zone)
        barrio_raw = (
            raw_data.get("neighborhoodUser")
            or raw_data.get("neighborhood")
            or None
        )
        neighborhood_label = barrio_raw or comuna_canonica
        tipo = (raw_data.get("realEstateType") or "").strip()
        city = raw_data.get("city") or "Medellín"
        title = f"{tipo} en arriendo en {neighborhood_label}, {city}" if tipo else None

        valor_administracion = self.safe_float(raw_data.get("adminValue"))

        # Antigüedad detallada
        antiguedad_raw = raw_data.get("propertyAge") or raw_data.get("age")
        if not antiguedad_raw:
            attrs = raw_data.get("attributes") or []
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                attr_name = str(attr.get("name", "")).lower()
                if "age" in attr_name or "antiguedad" in attr_name:
                    antiguedad_raw = attr.get("value")
                    break
        antiguedad = str(antiguedad_raw).strip() if antiguedad_raw is not None else None

        coords = raw_data.get("coordinates") or {}
        latitud = self.safe_coord(coords.get("latitude"))
        longitud = self.safe_coord(coords.get("longitude"))

        try:
            return PropertyCreate(
                portal=self.PORTAL_NAME,
                title=title,
                tipo_inmueble=tipo or None,
                area=self.safe_float(raw_data.get("area")),
                estrato=self.safe_int(raw_data.get("stratum")),
                comuna=comuna_canonica,
                barrio=str(barrio_raw).strip() if barrio_raw else None,
                habitaciones=self.safe_int(raw_data.get("rooms")),
                banos=self.safe_int(raw_data.get("baths")),
                parqueaderos=self.safe_int(raw_data.get("garages")) or 0,
                estado=estado,
                imagen_url=self._normalize_image_url(raw_data.get("image")),
                precio_publicado=precio_publicado,
                url_origen=url_origen,
                incluye_administracion=(raw_data.get("adminValue", -1) == 0),
                amoblado=(
                    "amoblado" in link.lower()
                    or "amoblado" in str(title or "").lower()
                ),
                latitud=latitud,
                longitud=longitud,
                antiguedad=antiguedad,
                valor_administracion=valor_administracion,
            )
        except ValidationError:
            return None
