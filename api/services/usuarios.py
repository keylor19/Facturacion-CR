"""
Usuarios del panel web: contraseñas con scrypt, bloqueo por intentos
fallidos y sesiones con token aleatorio (solo se guarda su hash).
"""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.models.database import Sesion, Usuario, utcnow
from api.models.schemas import UsuarioResponse
from config.settings import get_settings

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
# Hash de referencia para que un email inexistente tarde lo mismo que uno real
_HASH_FICTICIO = None


class LoginError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(dk)}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        esquema, n, r, p, salt, dk = almacenado.split("$")
        if esquema != "scrypt":
            return False
        calculado = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
            dklen=len(base64.b64decode(dk)),
        )
        return hmac.compare_digest(calculado, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def a_respuesta(u: Usuario) -> UsuarioResponse:
    return UsuarioResponse(
        id=str(u.id), email=u.email, nombre=u.nombre, es_admin=u.es_admin,
        emisor_id=str(u.emisor_id) if u.emisor_id else None, activo=u.activo, ultimo_login=u.ultimo_login,
    )


def crear_usuario(db: Session, email: str, nombre: str, password: str, es_admin: bool, emisor_id: str | None) -> Usuario:
    u = Usuario(email=email.strip().lower(), nombre=nombre, password_hash=hash_password(password),
                es_admin=es_admin, emisor_id=emisor_id)
    db.add(u)
    db.commit()
    return u


def iniciar_sesion(db: Session, email: str, password: str, ip: str | None) -> tuple[str, Sesion]:
    """Valida credenciales y crea una sesión. Mensaje genérico ante cualquier fallo."""
    global _HASH_FICTICIO
    s = get_settings()
    ahora = utcnow()
    usuario = db.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))

    if usuario is None:
        # Igualar el tiempo de respuesta para no revelar qué correos existen
        _HASH_FICTICIO = _HASH_FICTICIO or hash_password("ficticio")
        verificar_password(password, _HASH_FICTICIO)
        raise LoginError("Correo o contraseña incorrectos")
    if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
        raise LoginError("Usuario bloqueado temporalmente por intentos fallidos; intente más tarde")
    if not verificar_password(password, usuario.password_hash) or not usuario.activo:
        usuario.intentos_fallidos += 1
        if usuario.intentos_fallidos >= s.MAX_INTENTOS_LOGIN:
            usuario.bloqueado_hasta = ahora + timedelta(minutes=s.MINUTOS_BLOQUEO_LOGIN)
            usuario.intentos_fallidos = 0
        db.commit()
        raise LoginError("Correo o contraseña incorrectos")

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.ultimo_login = ahora
    # Limpieza de sesiones vencidas del usuario
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario.id, Sesion.expira < ahora))

    token = "ses_" + secrets.token_urlsafe(32)
    sesion = Sesion(usuario_id=usuario.id, token_hash=_hash_token(token),
                    expira=ahora + timedelta(hours=s.SESION_HORAS), ip=(ip or "")[:64])
    db.add(sesion)
    db.commit()
    return token, sesion


def usuario_de_token(db: Session, token: str) -> Usuario | None:
    sesion = db.scalar(select(Sesion).where(Sesion.token_hash == _hash_token(token)))
    if sesion is None or sesion.expira < utcnow():
        return None
    usuario = sesion.usuario
    if not usuario.activo:
        return None
    return usuario


def cerrar_sesion(db: Session, token: str) -> None:
    db.execute(delete(Sesion).where(Sesion.token_hash == _hash_token(token)))
    db.commit()


def cerrar_todas(db: Session, usuario_id: str) -> None:
    db.execute(delete(Sesion).where(Sesion.usuario_id == usuario_id))
    db.commit()
