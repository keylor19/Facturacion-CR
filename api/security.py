"""
Autenticación y autorización de la API.

- Header X-API-Key (sistemas integrados). Las llaves se guardan hasheadas
  (SHA-256) en la tabla api_keys; las de API_KEYS (.env) son llaves de
  administrador de arranque.
- Authorization: Bearer <token de sesión> (personas en el panel web).
- Llave de emisor: solo ve y opera los documentos de SU emisor.
- Llave de administrador (contador): administra emisores y opera sobre
  cualquiera indicando el header X-Emisor-Id.
Falla cerrado: sin llave válida no se accede a nada.
"""
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import ApiKey, Emisor, get_db, utcnow
from api.services import limites, suscripciones, usuarios
from config.settings import get_settings

logger = logging.getLogger(__name__)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)

PREFIJO_LLAVE = "fcr_"
# Rutas permitidas a un administrador sin 2FA (para que pueda activarla)
RUTAS_SIN_2FA = "/api/v1/auth/"


@dataclass(frozen=True)
class Principal:
    es_admin: bool
    emisor_id: str | None
    api_key_id: str | None
    usuario_id: str | None = None
    falta_2fa: bool = False     # administrador del panel que aún no activa la verificación en dos pasos


def verificar_secreto(recibido: str | None, esperados: list[str]) -> bool:
    """Comparación en tiempo constante contra todas las llaves válidas."""
    if not recibido:
        return False
    valido = False
    for esperado in esperados:
        valido |= hmac.compare_digest(recibido.encode(), esperado.encode())
    return valido


def hash_llave(llave: str) -> str:
    return hashlib.sha256(llave.encode()).hexdigest()


def generar_llave() -> str:
    return PREFIJO_LLAVE + secrets.token_urlsafe(32)


def crear_api_key(db: Session, nombre: str, es_admin: bool, emisor_id: str | None) -> tuple[ApiKey, str]:
    llave = generar_llave()
    registro = ApiKey(
        nombre=nombre, prefijo=llave[:12], hash=hash_llave(llave), es_admin=es_admin, emisor_id=emisor_id,
    )
    db.add(registro)
    db.commit()
    return registro, llave


def _no_autorizado():
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "API key inválida", headers={"WWW-Authenticate": "ApiKey"})


def autenticar(
    request: Request,
    api_key: str | None = Security(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    try:
        principal = _identificar(api_key, bearer, db)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            # Frena a quien prueba llaves o sesiones en masa desde una misma IP
            ip = request.client.host if request.client else "desconocida"
            limites.aplicar(f"fallo-auth:{ip}", get_settings().LIMITE_FALLOS_AUTH_MINUTO)
        raise
    if principal.falta_2fa and not request.url.path.startswith(RUTAS_SIN_2FA):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Active la verificación en dos pasos (Mi cuenta) para usar el panel como administrador",
                            headers={"X-Requiere-2FA": "activar"})
    # Límite de uso por llave / usuario
    quien = principal.api_key_id or principal.usuario_id or "admin-env"
    limites.aplicar(f"req:{quien}", get_settings().LIMITE_SOLICITUDES_MINUTO)
    return principal


def _identificar(api_key: str | None, bearer: HTTPAuthorizationCredentials | None, db: Session) -> Principal:
    # 1) Sesión del panel web (Authorization: Bearer ses_...)
    if bearer and not api_key:
        usuario = usuarios.usuario_de_token(db, bearer.credentials) if len(bearer.credentials) <= 200 else None
        if usuario is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o vencida",
                                headers={"WWW-Authenticate": "Bearer"})
        return Principal(es_admin=usuario.es_admin, emisor_id=usuario.emisor_id, api_key_id=None,
                         usuario_id=str(usuario.id),
                         falta_2fa=usuario.es_admin and not usuario.totp_activo and get_settings().exige_2fa_admin)

    # 2) API key (sistemas integrados)
    if not api_key or len(api_key) > 200:
        raise _no_autorizado()

    if verificar_secreto(api_key, get_settings().api_keys):
        return Principal(es_admin=True, emisor_id=None, api_key_id=None)

    registro = db.scalar(select(ApiKey).where(ApiKey.hash == hash_llave(api_key), ApiKey.activa.is_(True)))
    if registro is None:
        raise _no_autorizado()

    ahora = utcnow()
    if registro.ultimo_uso is None or ahora - registro.ultimo_uso > timedelta(minutes=5):
        registro.ultimo_uso = ahora
        db.commit()
    return Principal(es_admin=registro.es_admin, emisor_id=registro.emisor_id, api_key_id=str(registro.id))


def require_admin(principal: Principal = Depends(autenticar)) -> Principal:
    if not principal.es_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Se requiere una llave de administrador")
    return principal


def _cargar_emisor(db: Session, emisor_id: str) -> Emisor:
    try:
        uuid.UUID(emisor_id)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "X-Emisor-Id inválido")
    emisor = db.get(Emisor, emisor_id)
    if emisor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Emisor no encontrado")
    return emisor


def emisor_actual(
    principal: Principal = Depends(autenticar),
    x_emisor_id: str | None = Header(default=None, description="Obligatorio con llaves de administrador"),
    db: Session = Depends(get_db),
) -> Emisor:
    """Emisor sobre el que opera la solicitud (aislamiento entre empresas)."""
    if principal.emisor_id:
        if x_emisor_id and x_emisor_id != principal.emisor_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "La llave no tiene acceso a ese emisor")
        emisor = _cargar_emisor(db, principal.emisor_id)
    elif principal.es_admin:
        if not x_emisor_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indique el emisor en el header X-Emisor-Id")
        emisor = _cargar_emisor(db, x_emisor_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La llave no está asociada a ningún emisor")

    if not emisor.activo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "El emisor está inactivo")
    # Llave de una empresa: requiere el servicio de conexión por API (habilitado y pagado)
    if principal.api_key_id and not principal.es_admin and not suscripciones.activo(db, emisor, "api"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, suscripciones.motivo_inactivo(db, emisor, "api"))
    return emisor


def emisor_facturacion_web(
    principal: Principal = Depends(autenticar), emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
) -> Emisor:
    """
    Emitir y usar catálogos/inventario desde el panel requiere el servicio de
    facturación en línea de la empresa (habilitado y pagado). No aplica a los
    sistemas integrados por API ni a los administradores.
    """
    if principal.usuario_id and not principal.es_admin and not suscripciones.activo(db, emisor, "facturacion_web"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, suscripciones.motivo_inactivo(db, emisor, "facturacion_web"))
    return emisor
