"""Router HTTP para Autenticación de Administrador (Capa Boundary - <<boundary>>).

Expone:
- `POST /api/v1/auth/login`  (F7 - HU-06: Login con Bcrypt, JWT y regla RN-05)
- `POST /api/v1/auth/unlock` (Auxiliar académico para limpiar el bloqueo RN-05 en BD durante pruebas)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.boundary.dependencies import get_autenticacion_control
from backend.app.controls.autenticacion_control import AutenticacionControl
from backend.app.domain.schemas.auth_schemas import (
    LoginRequestSchema,
    TokenResponseSchema,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticación Admin (F7 - RN-05)"])


@router.post("/login", response_model=TokenResponseSchema)
def login_administrador(
    payload: LoginRequestSchema,
    control: AutenticacionControl = Depends(get_autenticacion_control),
) -> TokenResponseSchema:
    """Autentica al administrador con Bcrypt + JWT o bloquea por 30 min al 3.er fallo (RN-05)."""
    return control.autenticar_admin(payload)


@router.post("/unlock")
def desbloquear_admin_prueba(
    control: AutenticacionControl = Depends(get_autenticacion_control),
) -> dict[str, str]:
    """Reinicia el bloqueo RN-05 en PostgreSQL para facilitar las pruebas interactivas."""
    return control.desbloquear_cuenta_desarrollo("admin")
