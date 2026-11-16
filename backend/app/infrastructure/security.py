"""Servicios criptográficos de Infraestructura: Hashing Bcrypt y Tokens JWT (RNF-01).

Pertenece a la Capa 2 (Infrastructure). Ninguna contraseña se almacena ni se
compara en texto plano; utiliza `bcrypt` con sal aleatoria y `PyJWT` (HS256).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from backend.app.domain.config import (
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    JWT_SECRET_KEY,
)


def hash_password(plain_password: str) -> str:
    """Genera un hash seguro con sal aleatoria mediante el algoritmo Bcrypt."""
    pwd_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica en tiempo constante si la contraseña en texto plano coincide con el hash Bcrypt."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def create_access_token(username: str, rol: str = "ADMIN") -> str:
    """Emite un token JWT firmado con HS256 y tiempo de expiración."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload: dict[str, object] = {
        "sub": username,
        "rol": rol,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, object] | None:
    """Decodifica y verifica la firma y vigencia de un token JWT."""
    try:
        decoded = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return dict(decoded)
    except jwt.PyJWTError:
        return None
