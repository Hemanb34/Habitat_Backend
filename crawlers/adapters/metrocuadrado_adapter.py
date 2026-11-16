"""
metrocuadrado_adapter.py — Adaptador concreto para Metrocuadrado (Patrón Adapter).

Traduce el objeto JSON nativo devuelto por el endpoint `/rest-search/search`
de metrocuadrado.com al modelo canónico `PropertyCreate`, validando RN-06.
"""

from typing import Optional
from pydantic import ValidationError

from crawlers.adapters.base_adapter import PropertyDataAdapter
from crawlers.schemas import PropertyCreate


class MetrocuadradoAdapter(PropertyDataAdapter):
    """Adaptador concreto de Metrocuadrado -> PropertyCreate."""

    PORTAL_NAME = "metrocuadrado"

    def adapt(self, raw_data: dict, search_zone: str = "") -> Optional[PropertyCreate]:
        if not raw_data or not isinstance(raw_data, dict):
            return None

        # Regla RN-06: URL original obligatoria
        link = (raw_data.get("link") or "").strip()
        if not link:
            return None
        url_origen = (
            link
            if link.startswith("http")
            else f"https://www.metrocuadrado.com{link}"
        )

        # Canon de arrendamiento obligatorio (> 0)
        precio_publicado = self.safe_float(raw_data.get("mvalorarriendo"))
        if not precio_publicado or precio_publicado <= 0:
            return None

        # Tipo de inmueble
        tipo_raw = raw_data.get("mtipoinmueble")
        if isinstance(tipo_raw, dict):
            tipo_inmueble = tipo_raw.get("nombre") or tipo_raw.get("name")
        else:
            tipo_inmueble = str(tipo_raw) if tipo_raw else None

        # Características adicionales (featured)
        featured = raw_data.get("featured") or []
        featured_str = "".join(str(x) for x in featured).lower()
        amoblado = (
            "amoblado" in featured_str
            or "amoblado" in str(raw_data.get("comment") or "").lower()
            or "amoblado" in str(raw_data.get("title") or "").lower()
        )
        incluye_administracion = "conadmin:s" in featured_str

        antiguedad: Optional[str] = None
        for feat in featured:
            feat_str = str(feat)
            if "tiempoConstruido:" in feat_str:
                antiguedad = feat_str.split("tiempoConstruido:", 1)[1].strip()
                break

        localizacion = raw_data.get("localizacion") or {}
        data_block = raw_data.get("data") or {}
        valor_administracion = self.safe_float(data_block.get("mvaloradministracion"))

        barrio_raw = (
            raw_data.get("mbarrio")
            or raw_data.get("mnombrecomuna")
            or None
        )

        try:
            return PropertyCreate(
                portal=self.PORTAL_NAME,
                title=raw_data.get("title"),
                tipo_inmueble=tipo_inmueble,
                area=self.safe_float(raw_data.get("marea") or raw_data.get("mareac")),
                estrato=self.safe_int(raw_data.get("estrato")),
                comuna=self.normalize_comuna_seed(search_zone),
                barrio=str(barrio_raw).strip() if barrio_raw else None,
                habitaciones=self.safe_int(raw_data.get("mnrocuartos")),
                banos=self.safe_int(raw_data.get("mnrobanos")),
                parqueaderos=self.safe_int(raw_data.get("mnrogarajes")) or 0,
                estado=raw_data.get("mestadoinmueble"),
                imagen_url=raw_data.get("imageLink"),
                precio_publicado=precio_publicado,
                url_origen=url_origen,
                incluye_administracion=incluye_administracion,
                amoblado=amoblado,
                latitud=self.safe_coord(localizacion.get("lat")),
                longitud=self.safe_coord(localizacion.get("lon")),
                antiguedad=antiguedad,
                valor_administracion=valor_administracion,
            )
        except ValidationError:
            return None
