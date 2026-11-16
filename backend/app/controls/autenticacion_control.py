"""Controlador de caso de uso AutenticacionControl (Capa Control - <<control>>).

Implementa el flujo del Diagrama de Actividades F7 (Autenticar Administrador):
1. Verifica si la cuenta está bloqueada temporalmente (RN-05 -> HTTP 423 Locked).
2. Valida las credenciales contra el hash Bcrypt en PostgreSQL (RNF-01).
3. Si falla, incrementa `intentos_fallidos` en BD; al llegar a 3 fallos consecutivos,
   bloquea la cuenta durante 30 minutos (RN-05) y registra el evento en `LogAuditoria` (RNF-09).
4. Si acierta, reinicia el contador de intentos y emite un token JWT firmado.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from backend.app.domain.config import (
    JWT_EXPIRE_MINUTES,
    LOCKOUT_DURATION_MINUTES,
    MAX_FAILED_LOGIN_ATTEMPTS,
)
from backend.app.domain.interfaces.repositories import IAdminRepository
from backend.app.domain.schemas.auth_schemas import (
    AuthFailureDetailSchema,
    LoginRequestSchema,
    TokenResponseSchema,
)
from backend.app.infrastructure.security import create_access_token, verify_password


class AutenticacionControl:
    """Orquestador <<control>> para inicio de sesión administrativo y regla RN-05."""

    def __init__(self, admin_repo: IAdminRepository) -> None:
        self._admin_repo = admin_repo

    def autenticar_admin(self, solicitud: LoginRequestSchema) -> TokenResponseSchema:
        """Verifica credenciales, aplica bloqueo RN-05 y emite JWT."""
        admin = self._admin_repo.obtener_por_username(solicitud.username)

        # Caso 1: Usuario no existe en la base de datos
        if admin is None:
            self._admin_repo.registrar_evento_auditoria(
                accion="Intento de login fallido",
                detalle=f"Usuario inexistente '{solicitud.username}'",
                estado="warn",
                usuario=solicitud.username,
            )
            detalle_error = AuthFailureDetailSchema(
                mensaje="Credenciales incorrectas. Verifica el usuario y la contraseña.",
                bloqueado=False,
                intentos_fallidos=1,
                intentos_restantes=MAX_FAILED_LOGIN_ATTEMPTS - 1,
                minutos_restantes_bloqueo=0,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=detalle_error.model_dump(mode="json"),
            )

        # Caso 2: La cuenta ya se encuentra bloqueada por RN-05 (30 minutos vigentes)
        if admin.esta_bloqueado():
            min_restantes = admin.minutos_restantes_bloqueo()
            self._admin_repo.registrar_evento_auditoria(
                accion="Intento en cuenta bloqueada (RN-05)",
                detalle=f"Acceso rechazado para '{admin.username}' ({min_restantes} min restantes)",
                estado="error",
                usuario=admin.username,
            )
            detalle_bloqueo = AuthFailureDetailSchema(
                mensaje=(
                    f"Acceso bloqueado por seguridad (RN-05) tras {MAX_FAILED_LOGIN_ATTEMPTS} "
                    f"intentos fallidos consecutivos. Intenta nuevamente en {min_restantes} minutos."
                ),
                bloqueado=True,
                intentos_fallidos=admin.intentos_fallidos,
                intentos_restantes=0,
                minutos_restantes_bloqueo=min_restantes,
                bloqueado_hasta=admin.bloqueado_hasta,
            )
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=detalle_bloqueo.model_dump(mode="json"),
            )

        # Caso 3: Contraseña incorrecta -> Incrementar contador RN-05 en PostgreSQL
        if not verify_password(solicitud.password, admin.password_hash):
            recien_bloqueado = admin.registrar_intento_fallido_rn05()
            self._admin_repo.guardar(admin)

            if recien_bloqueado:
                min_restantes = admin.minutos_restantes_bloqueo()
                self._admin_repo.registrar_evento_auditoria(
                    accion="Bloqueo de cuenta activado (RN-05)",
                    detalle=(
                        f"Cuenta '{admin.username}' bloqueada por {LOCKOUT_DURATION_MINUTES} min "
                        f"tras {MAX_FAILED_LOGIN_ATTEMPTS} intentos fallidos consecutivos"
                    ),
                    estado="error",
                    usuario=admin.username,
                )
                detalle_nuevo_bloqueo = AuthFailureDetailSchema(
                    mensaje=(
                        f"Acceso bloqueado por {LOCKOUT_DURATION_MINUTES} minutos tras "
                        f"{MAX_FAILED_LOGIN_ATTEMPTS} intentos fallidos consecutivos (RN-05)."
                    ),
                    bloqueado=True,
                    intentos_fallidos=admin.intentos_fallidos,
                    intentos_restantes=0,
                    minutos_restantes_bloqueo=min_restantes,
                    bloqueado_hasta=admin.bloqueado_hasta,
                )
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=detalle_nuevo_bloqueo.model_dump(mode="json"),
                )

            restantes = max(0, MAX_FAILED_LOGIN_ATTEMPTS - admin.intentos_fallidos)
            self._admin_repo.registrar_evento_auditoria(
                accion="Intento de login fallido",
                detalle=(
                    f"Contraseña inválida para '{admin.username}' "
                    f"(Intento {admin.intentos_fallidos}/{MAX_FAILED_LOGIN_ATTEMPTS})"
                ),
                estado="warn",
                usuario=admin.username,
            )
            detalle_fallo = AuthFailureDetailSchema(
                mensaje=(
                    f"Credenciales incorrectas. {restantes} "
                    f"{'intento restante' if restantes == 1 else 'intentos restantes'} antes del bloqueo."
                ),
                bloqueado=False,
                intentos_fallidos=admin.intentos_fallidos,
                intentos_restantes=restantes,
                minutos_restantes_bloqueo=0,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=detalle_fallo.model_dump(mode="json"),
            )

        # Caso 4: Autenticación exitosa -> Reiniciar contador y emitir JWT
        admin.resetear_intentos()
        self._admin_repo.guardar(admin)
        self._admin_repo.registrar_evento_auditoria(
            accion="Inicio de sesión administrativo",
            detalle=f"Acceso concedido con JWT a '{admin.username}'",
            estado="ok",
            usuario=admin.username,
        )

        token = create_access_token(username=admin.username, rol=admin.rol)
        return TokenResponseSchema(
            access_token=token,
            token_type="bearer",
            username=admin.username,
            rol=admin.rol,
            expires_in_minutes=JWT_EXPIRE_MINUTES,
        )

    def desbloquear_cuenta_desarrollo(self, username: str = "admin") -> dict[str, str]:
        """Permite restablecer en BD el bloqueo de 30 min durante pruebas académicas."""
        admin = self._admin_repo.obtener_por_username(username)
        if admin is not None:
            admin.resetear_intentos()
            self._admin_repo.guardar(admin)
            self._admin_repo.registrar_evento_auditoria(
                accion="Desbloqueo manual de prueba",
                detalle=f"Contador RN-05 reiniciado para '{admin.username}'",
                estado="ok",
                usuario=admin.username,
            )
        return {"status": "unlocked", "username": username}
