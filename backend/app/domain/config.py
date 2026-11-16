"""Configuración centralizada del Backend Principal (Habita).

Define las variables de entorno, rutas de conexión a PostgreSQL (en Docker),
URL del Microservicio de Machine Learning y parámetros de seguridad.
"""

from __future__ import annotations

import os
from pathlib import Path

# Rutas base del ecosistema Habita
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
RAW_CSV_DIR = PROJECT_ROOT / "ml_service" / "data" / "raw"

# 1. Configuración de Base de Datos PostgreSQL (Contenedor Docker: postgres_db)
DB_USER: str = os.getenv("HABITA_DB_USER", "admin")
DB_PASSWORD: str = os.getenv("HABITA_DB_PASSWORD", "admin_password")
DB_HOST: str = os.getenv("HABITA_DB_HOST", "localhost")
DB_PORT: str = os.getenv("HABITA_DB_PORT", "5432")
DB_NAME: str = os.getenv("HABITA_DB_NAME", "habita_db")

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
)

# 2. Comunicación con el Microservicio de Machine Learning (Puerto 8001)
ML_SERVICE_BASE_URL: str = os.getenv("ML_SERVICE_BASE_URL", "http://127.0.0.1:8001")

# 3. Parámetros de Seguridad (JWT y Regla de Negocio RN-05)
JWT_SECRET_KEY: str = os.getenv(
    "JWT_SECRET_KEY",
    "habita-super-secret-jwt-key-medellin-2026-dev",
)
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 120

# RN-05: Máximo 3 intentos fallidos consecutivos -> 30 minutos de bloqueo
MAX_FAILED_LOGIN_ATTEMPTS: int = 3
LOCKOUT_DURATION_MINUTES: int = 30

# 4. Orígenes permitidos por CORS (Frontend Vite en desarrollo)
CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
