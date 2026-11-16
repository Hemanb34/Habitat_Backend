"""Schemas Pydantic (DTOs) para Autenticación de Administrador y Regla RN-05 (F7 - HU-06).

Define los esquemas de entrada y salida de `POST /api/v1/auth/login`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequestSchema(BaseModel):
    """Credenciales enviadas desde `AdminLogin.tsx`."""

    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponseSchema(BaseModel):
    """Respuesta exitosa con el JWT firmado cuando las credenciales son válidas."""

    access_token: str
    token_type: str = "bearer"
    username: str
    rol: str = "ADMIN"
    expires_in_minutes: int


class AuthFailureDetailSchema(BaseModel):
    """Estructura detallada devuelta en errores HTTP 401 (intento fallido) o HTTP 423 (bloqueo RN-05)."""

    mensaje: str
    bloqueado: bool
    intentos_fallidos: int
    intentos_restantes: int
    minutos_restantes_bloqueo: int = 0
    bloqueado_hasta: datetime | None = None
