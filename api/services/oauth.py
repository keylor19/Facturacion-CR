"""
Entrar o crear la cuenta con Google o Microsoft (OpenID Connect, flujo de código).

1. /auth/oauth/{proveedor}/inicio: se manda a la persona al proveedor con un `state` firmado
   (proveedor, tipo de cuenta, vencimiento) y una cookie con un número único que solo
   conoce ese navegador (evita que alguien le haga entrar con la cuenta de otro).
2. /auth/oauth/{proveedor}/callback: se cambia el código por un token, se leen el correo y
   el identificador de la persona, y se busca o se crea su usuario (ya confirmado: el
   proveedor verificó el correo). Se abre una sesión del panel.

Los administradores del servicio no entran por aquí: usan contraseña y verificación en dos pasos.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import Registro, Usuario, utcnow
from api.services import enlaces, usuarios
from config.settings import get_settings

VIGENCIA_STATE = 600   # segundos
COOKIE = "fcr_oauth"

PROVEEDORES = {
    "google": {
        "nombre": "Google",
        "autorizar": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "usuario": "https://openidconnect.googleapis.com/v1/userinfo",
    },
    "microsoft": {
        "nombre": "Microsoft",
        "autorizar": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "usuario": "https://graph.microsoft.com/oidc/userinfo",
    },
}


class OAuthError(Exception):
    pass


def _credenciales(proveedor: str) -> tuple[str, str]:
    s = get_settings()
    return {"google": (s.GOOGLE_CLIENT_ID, s.GOOGLE_CLIENT_SECRET),
            "microsoft": (s.MICROSOFT_CLIENT_ID, s.MICROSOFT_CLIENT_SECRET)}.get(proveedor, ("", ""))


def disponibles() -> list[str]:
    return [p for p in PROVEEDORES if all(_credenciales(p))]


def redirect_uri(proveedor: str) -> str:
    return f"{enlaces.url_base()}/api/v1/auth/oauth/{proveedor}/callback"


def _firmar(datos: dict) -> str:
    cuerpo = base64.urlsafe_b64encode(json.dumps(datos, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{cuerpo}.{_firmar_cuerpo(cuerpo)}"


def _leer(state: str) -> dict:
    try:
        cuerpo, firma = state.split(".", 1)
    except ValueError:
        raise OAuthError("estado")
    if not hmac.compare_digest(_firmar_cuerpo(cuerpo), firma):
        raise OAuthError("estado")
    datos = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    if datos.get("exp", 0) < time.time():
        raise OAuthError("vencido")
    return datos


def _firmar_cuerpo(cuerpo: str) -> str:
    llave = hmac.new((get_settings().MASTER_KEY or get_settings().JWT_SECRET).encode(), b"oauth-state", hashlib.sha256).digest()
    return hmac.new(llave, cuerpo.encode(), hashlib.sha256).hexdigest()


def inicio(proveedor: str, tipo: str) -> tuple[str, str]:
    """(URL del proveedor, valor de la cookie del navegador)."""
    if proveedor not in disponibles():
        raise OAuthError("no_disponible")
    nonce = secrets.token_urlsafe(24)
    state = _firmar({"p": proveedor, "t": tipo if tipo in ("empresa", "contador") else "empresa",
                     "n": hashlib.sha256(nonce.encode()).hexdigest(), "exp": int(time.time()) + VIGENCIA_STATE})
    cliente, _ = _credenciales(proveedor)
    url = PROVEEDORES[proveedor]["autorizar"] + "?" + urlencode({
        "client_id": cliente, "response_type": "code", "redirect_uri": redirect_uri(proveedor),
        "scope": "openid email profile", "state": state, "prompt": "select_account",
    })
    return url, nonce


def _identidad(proveedor: str, codigo: str) -> dict:
    cliente, secreto = _credenciales(proveedor)
    p = PROVEEDORES[proveedor]
    try:
        r = requests.post(p["token"], data={
            "grant_type": "authorization_code", "code": codigo, "redirect_uri": redirect_uri(proveedor),
            "client_id": cliente, "client_secret": secreto,
        }, timeout=15)
        r.raise_for_status()
        acceso = r.json()["access_token"]
        info = requests.get(p["usuario"], headers={"Authorization": f"Bearer {acceso}"}, timeout=15)
        info.raise_for_status()
        datos = info.json()
    except (requests.RequestException, KeyError, ValueError):
        raise OAuthError("proveedor")
    email = (datos.get("email") or datos.get("preferred_username") or "").strip().lower()
    if not email or "@" not in email or datos.get("email_verified") is False:
        raise OAuthError("correo")
    return {"sub": str(datos.get("sub") or ""), "email": email, "nombre": (datos.get("name") or email.split("@")[0])[:100]}


def completar(db: Session, proveedor: str, codigo: str, state: str, cookie: str | None) -> Usuario:
    """Busca o crea el usuario de esa cuenta de Google / Microsoft."""
    datos = _leer(state)
    if datos.get("p") != proveedor or not cookie or not hmac.compare_digest(hashlib.sha256(cookie.encode()).hexdigest(), datos.get("n", "")):
        raise OAuthError("estado")
    persona = _identidad(proveedor, codigo)
    u = None
    if persona["sub"]:
        u = db.scalar(select(Usuario).where(Usuario.oauth_proveedor == proveedor, Usuario.oauth_sub == persona["sub"]))
    if u is None:
        u = db.scalar(select(Usuario).where(func.lower(Usuario.email) == persona["email"]))
    if u is not None:
        if u.es_admin:
            raise OAuthError("administrador")
        if not u.activo:
            # Solo se activa la cuenta que esperaba confirmar su correo (el proveedor ya lo verificó);
            # una desactivada por el dueño o el administrador sigue desactivada
            pendiente = db.scalar(select(Registro).where(Registro.usuario_id == u.id, Registro.confirmado.is_(None)))
            if pendiente is None:
                raise OAuthError("inactivo")
            pendiente.confirmado = utcnow()
            u.activo = True
        u.oauth_proveedor, u.oauth_sub = proveedor, persona["sub"] or None
        db.commit()
        return u
    from api.services import registro   # evita importación circular
    if not registro.abierto(db):
        raise OAuthError("cerrado")
    contador = datos.get("t") == "contador"
    u = Usuario(email=persona["email"], nombre=persona["nombre"], es_admin=False, emisor_id=None,
                # Sin contraseña utilizable: entra con su proveedor (puede crear una en Mi usuario)
                password_hash=usuarios.hash_password(secrets.token_urlsafe(32)),
                es_contador=contador, rol="contador_externo" if contador else "dueno", activo=True,
                oauth_proveedor=proveedor, oauth_sub=persona["sub"] or None)
    db.add(u)
    db.commit()
    return u
