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
from api.services import cifrado, dos_pasos
from config.settings import get_settings

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
# Hash de referencia para que un email inexistente tarde lo mismo que uno real
_HASH_FICTICIO = None


class LoginError(Exception):
    pass


class Requiere2FA(LoginError):
    """La contraseña es correcta pero falta (o es incorrecto) el código de la app autenticadora."""


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
        dos_pasos=bool(u.totp_activo),
    )


def crear_usuario(db: Session, email: str, nombre: str, password: str, es_admin: bool, emisor_id: str | None) -> Usuario:
    u = Usuario(email=email.strip().lower(), nombre=nombre, password_hash=hash_password(password),
                es_admin=es_admin, emisor_id=emisor_id)
    db.add(u)
    db.commit()
    return u


def _registrar_fallo(db: Session, usuario: Usuario, ahora) -> None:
    s = get_settings()
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos >= s.MAX_INTENTOS_LOGIN:
        usuario.bloqueado_hasta = ahora + timedelta(minutes=s.MINUTOS_BLOQUEO_LOGIN)
        usuario.intentos_fallidos = 0
    db.commit()


def iniciar_sesion(db: Session, email: str, password: str, ip: str | None,
                   codigo: str | None = None) -> tuple[str, Sesion]:
    """Valida credenciales (y el código 2FA si está activo) y crea una sesión."""
    global _HASH_FICTICIO
    s = get_settings()
    ahora = utcnow()
    usuario = db.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))

    if usuario is None:
        # Igualar el tiempo de respuesta para no revelar qué correos existen
        _HASH_FICTICIO = _HASH_FICTICIO or hash_password("ficticio")
        verificar_password(password, _HASH_FICTICIO)
        raise LoginError("Correo o contraseña incorrectos")
    bloqueado = bool(usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora)
    if not verificar_password(password, usuario.password_hash) or not usuario.activo:
        if bloqueado:
            # No se revela que la cuenta existe ni que está bloqueada
            raise LoginError("Correo o contraseña incorrectos")
        _registrar_fallo(db, usuario, ahora)
        raise LoginError("Correo o contraseña incorrectos")
    if bloqueado:
        # Solo quien conoce la contraseña se entera del bloqueo
        raise LoginError("Usuario bloqueado temporalmente por intentos fallidos; intente más tarde")

    if usuario.totp_activo:
        if not codigo:
            raise Requiere2FA("Ingrese el código de su app autenticadora")
        paso = dos_pasos.verificar(cifrado.descifrar_texto(usuario.totp_secreto_cifrado), codigo,
                                   usuario.totp_ultimo_paso)
        if paso is None:
            # Los códigos fallidos también cuentan para el bloqueo (evita adivinarlos)
            _registrar_fallo(db, usuario, ahora)
            raise Requiere2FA("Código de verificación incorrecto o ya utilizado")
        usuario.totp_ultimo_paso = paso

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


def cerrar_todas(db: Session, usuario_id: str, excepto_token: str | None = None) -> None:
    query = delete(Sesion).where(Sesion.usuario_id == usuario_id)
    if excepto_token:
        query = query.where(Sesion.token_hash != _hash_token(excepto_token))
    db.execute(query)
    db.commit()


# --- Verificación en dos pasos ----------------------------------------------

def iniciar_2fa(db: Session, usuario: Usuario) -> str:
    """Genera un secreto nuevo (pendiente de confirmar con un código)."""
    if usuario.totp_activo:
        raise LoginError("La verificación en dos pasos ya está activa")
    secreto = dos_pasos.generar_secreto()
    usuario.totp_secreto_cifrado = cifrado.cifrar(secreto)
    usuario.totp_ultimo_paso = None
    db.commit()
    return secreto


def activar_2fa(db: Session, usuario: Usuario, codigo: str) -> None:
    if usuario.totp_activo:
        raise LoginError("La verificación en dos pasos ya está activa")
    if usuario.totp_secreto_cifrado is None:
        raise LoginError("Primero genere el código QR")
    paso = dos_pasos.verificar(cifrado.descifrar_texto(usuario.totp_secreto_cifrado), codigo, None)
    if paso is None:
        raise LoginError("El código no coincide; revise la hora del teléfono e intente de nuevo")
    usuario.totp_activo = True
    usuario.totp_ultimo_paso = paso
    db.commit()


def desactivar_2fa(db: Session, usuario: Usuario, password: str, codigo: str) -> None:
    """El propio usuario la desactiva: exige contraseña y un código válido."""
    if not usuario.totp_activo:
        raise LoginError("La verificación en dos pasos no está activa")
    if not verificar_password(password, usuario.password_hash):
        raise LoginError("La contraseña no es correcta")
    paso = dos_pasos.verificar(cifrado.descifrar_texto(usuario.totp_secreto_cifrado), codigo,
                               usuario.totp_ultimo_paso)
    if paso is None:
        raise LoginError("Código de verificación incorrecto o ya utilizado")
    reiniciar_2fa(db, usuario)


def reiniciar_2fa(db: Session, usuario: Usuario) -> None:
    """Quita la verificación en dos pasos (p. ej. si el usuario perdió el teléfono)."""
    usuario.totp_secreto_cifrado = None
    usuario.totp_activo = False
    usuario.totp_ultimo_paso = None
    db.commit()
