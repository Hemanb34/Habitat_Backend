"""
fincaraiz_adapter.py — Adaptador concreto para FincaRaíz (Patrón Adapter).

Traduce el objeto `listing` nativo del endpoint `/api/v1/properties/search`
de fincaraiz.com.co al modelo canónico `PropertyCreate`, validando RN-06.
"""

from typing import Optional
from pydantic import ValidationError

from crawlers.adapters.base_adapter import PropertyDataAdapter
from crawlers.schemas import PropertyCreate


class FincaraizAdapter(PropertyDataAdapter):
    """Adaptador concreto de FincaRaíz -> PropertyCreate."""

    PORTAL_NAME = "fincaraiz"

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
            else f"https://www.fincaraiz.com.co{link}"
        )

        # Canon de arrendamiento obligatorio (> 0)
        price_block = raw_data.get("price") or {}
        precio_publicado = self.safe_float(price_block.get("amount"))
        if not precio_publicado or precio_publicado <= 0:
            return None

        images = raw_data.get("images") or []
        imagen_url = images[0].get("image") if images and isinstance(images[0], dict) else None

        antiquity = raw_data.get("antiquity")
        if antiquity is None:
            estado = None
        elif antiquity == 0:
            estado = "Nuevo"
        else:
            estado = "Usado"

        tipo_inmueble = (raw_data.get("property_type") or {}).get("name")

        facilities = raw_data.get("facilities") or []
        amoblado = any(
            "amoblado" in str((f or {}).get("name", "")).lower()
            for f in facilities
            if isinstance(f, dict)
        )

        # Antigüedad desde technicalSheet o fallback a antiquity
        tech_sheet = raw_data.get("technicalSheet") or []
        antiguedad_str: Optional[str] = None
        for item in tech_sheet:
            if isinstance(item, dict) and item.get("field") == "constructionYear":
                val = item.get("value")
                if val is not None:
                    antiguedad_str = str(val).strip()
                break
        if not antiguedad_str and antiquity is not None:
            antiguedad_str = str(antiquity)

        common_expenses = raw_data.get("commonExpenses") or {}
        valor_administracion = self.safe_float(common_expenses.get("amount"))

        # Barrio reportado en locations.neighbourhoods si existe
        locations_block = raw_data.get("locations") or {}
        neighbourhoods = locations_block.get("neighbourhoods") or []
        barrio_raw = (
            neighbourhoods[0].get("name")
            if neighbourhoods and isinstance(neighbourhoods[0], dict)
            else None
        )

        try:
            return PropertyCreate(
                portal=self.PORTAL_NAME,
                title=raw_data.get("title"),
                tipo_inmueble=tipo_inmueble,
                area=self.safe_float(raw_data.get("m2") or raw_data.get("m2Built")),
                estrato=self.safe_int(raw_data.get("stratum")),
                comuna=self.normalize_comuna_seed(search_zone),
                barrio=str(barrio_raw).strip() if barrio_raw else None,
                habitaciones=self.safe_int(raw_data.get("bedrooms")),
                banos=self.safe_int(raw_data.get("bathrooms")),
                parqueaderos=self.safe_int(raw_data.get("garage")) or 0,
                estado=estado,
                imagen_url=imagen_url,
                precio_publicado=precio_publicado,
                url_origen=url_origen,
                incluye_administracion=bool(raw_data.get("include_administration", False)),
                amoblado=amoblado,
                latitud=self.safe_coord(raw_data.get("latitude")),
                longitud=self.safe_coord(raw_data.get("longitude")),
                antiguedad=antiguedad_str,
                valor_administracion=valor_administracion,
            )
        except ValidationError:
            return None
