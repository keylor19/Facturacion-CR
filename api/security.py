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

from api.models.database import ApiKey, Emisor, get_db, utcnow, UsuarioEmpresa
from api.services import limites, permisos, suscripciones, usuarios
from config.settings import get_settings

logger = logging.getLogger(__name__)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)

PREFIJO_LLAVE = "fcr_"
# Rutas permitidas a un administrador sin 2FA (para que pueda activarla)
RUTAS_SIN_2FA = "/api/v1/auth/"
# Lo único que puede usar un contador externo
RUTAS_CONTADOR = ("/api/v1/auth/", "/api/v1/contabilidad", "/api/v1/hacienda/", "/api/v1/reportes/", "/api/v1/servicios")


@dataclass(frozen=True)
class Principal:
    es_admin: bool
    emisor_id: str | None
    api_key_id: str | None
    usuario_id: str | None = None
    falta_2fa: bool = False     # administrador del panel que aún no activa la verificación en dos pasos
    rol: str = "dueno"           # usuarios de empresa: dueno, contador o cajero (ver services/permisos.py)
    # Contador externo: solo entra a la contabilidad de las empresas que tiene a cargo
    es_contador: bool = False
    empresas: tuple = ()


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
        principal = _identificar(api_key, bearer, db, request.headers.get("X-Emisor-Id"))
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            # Frena a quien prueba llaves o sesiones en masa desde una misma IP
            ip = request.client.host if request.client else "desconocida"
            limites.aplicar(f"fallo-auth:{ip}", get_settings().LIMITE_FALLOS_AUTH_MINUTO)
        raise
    # El contador externo solo usa la contabilidad (y consultas a Hacienda): no factura ni administra
    if principal.es_contador and not request.url.path.startswith(RUTAS_CONTADOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Su usuario de contador solo tiene acceso a la contabilidad")
    if principal.falta_2fa and not request.url.path.startswith(RUTAS_SIN_2FA):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Active la verificación en dos pasos (Mi cuenta) para usar el panel como administrador",
                            headers={"X-Requiere-2FA": "activar"})
    # Límite de uso por llave / usuario
    quien = principal.api_key_id or principal.usuario_id or "admin-env"
    limites.aplicar(f"req:{quien}", get_settings().LIMITE_SOLICITUDES_MINUTO)
    return principal


def _identificar(api_key: str | None, bearer: HTTPAuthorizationCredentials | None, db: Session,
                 emisor_pedido: str | None = None) -> Principal:
    # 1) Sesión del panel web (Authorization: Bearer ses_...)
    if bearer and not api_key:
        usuario = usuarios.usuario_de_token(db, bearer.credentials) if len(bearer.credentials) <= 200 else None
        if usuario is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o vencida",
                                headers={"WWW-Authenticate": "Bearer"})
        if usuario.es_contador:
            return _principal_contador(db, usuario, emisor_pedido)
        return Principal(es_admin=usuario.es_admin, emisor_id=usuario.emisor_id, api_key_id=None,
                         usuario_id=str(usuario.id), rol="dueno" if usuario.es_admin else (usuario.rol or "dueno"),
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


def permiso(nombre: str):
    """Dependencia: el usuario debe tener ese permiso según su rol (ver services/permisos.py)."""
    def verificar(principal: Principal = Depends(autenticar)) -> Principal:
        # La contabilidad es de personas (dueño o contador): ni administradores del servicio ni API keys
        if nombre == "contabilidad" and (principal.es_admin or principal.api_key_id or not principal.usuario_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "La contabilidad solo la ven el dueño de la empresa y su contador")
        if not permisos.tiene(principal.rol, nombre):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Su usuario ({permisos.ROLES.get(principal.rol, principal.rol)}) no tiene permiso para "
                                f"{permisos.DESCRIPCION[nombre]}. Pídaselo al dueño de la empresa.")
        return principal
    return verificar


def contabilidad_habilitada(principal: Principal = Depends(permiso("contabilidad")),
                            db: Session = Depends(get_db)) -> Principal:
    """
    La contabilidad tiene mensualidad: la del contador cubre todas las empresas que lleva; el
    dueño que la lleva él mismo paga la de su empresa. Sin ella (o en mora) se le dice el precio.
    """
    from api.services import mensualidades
    if principal.es_contador:
        servicio, cliente = "contador", {"usuario_id": principal.usuario_id}
    else:
        servicio, cliente = "contabilidad", {"emisor_id": principal.emisor_id}
    if not mensualidades.activo(db, servicio, **cliente):
        raise HTTPException(status.HTTP_403_FORBIDDEN, mensualidades.motivo(db, servicio, **cliente),
                            headers={"X-Requiere-Servicio": servicio})
    return principal


def empresas_del_contador(db: Session, usuario_id: str) -> list[str]:
    """Las que le asignó el administrador más las que él agregó solo para llevarles la contabilidad."""
    asignadas = db.scalars(select(UsuarioEmpresa.emisor_id).join(Emisor, Emisor.id == UsuarioEmpresa.emisor_id)
                           .where(UsuarioEmpresa.usuario_id == usuario_id, Emisor.activo.is_(True))
                           .order_by(UsuarioEmpresa.created_at)).all()
    propias = db.scalars(select(Emisor.id).where(Emisor.contador_id == usuario_id, Emisor.activo.is_(True))
                         .order_by(Emisor.created_at)).all()
    return list(dict.fromkeys([*asignadas, *propias]))


def _principal_contador(db: Session, usuario, emisor_pedido: str | None) -> Principal:
    """El contador opera sobre la empresa que pide en X-Emisor-Id (si la tiene a cargo); sin header, la primera."""
    ids = empresas_del_contador(db, str(usuario.id))
    elegido = emisor_pedido if emisor_pedido in ids else (ids[0] if ids else None)
    return Principal(es_admin=False, emisor_id=elegido, api_key_id=None, usuario_id=str(usuario.id),
                     rol="contador_externo", es_contador=True, empresas=tuple(ids))


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
    # Llave de una empresa: requiere la conexión por API habilitada (se paga con documentos, sin mensualidad)
    if principal.api_key_id and not principal.es_admin and not suscripciones.activo(db, emisor, "api"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, suscripciones.motivo_inactivo(db, emisor, "api"))
    # Usuario del panel de una empresa: el panel web es un servicio adicional (pagado o en regalía).
    # El contador externo no factura: su acceso no depende de ese servicio.
    if (principal.usuario_id and not principal.es_admin and not principal.es_contador
            and not suscripciones.activo(db, emisor, "facturacion_web")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, suscripciones.motivo_inactivo(db, emisor, "facturacion_web"))
    return emisor


def emisor_facturacion_web(emisor: Emisor = Depends(emisor_actual)) -> Emisor:
    """
    Rutas de facturación en línea (emitir, catálogos, inventario, POS). El panel
    web ya se exige en emisor_actual para todo usuario de empresa; se conserva
    este nombre para marcar las rutas que solo tienen sentido desde el panel o la API.
    """
    return emisor
