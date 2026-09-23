"""
Autenticación contra Hacienda vía OpenID Connect (OAuth2 - grant_type password),
con las credenciales de cada emisor.

Endpoints (ver config/settings.py -> HACIENDA_ENDPOINTS):
  stag: .../auth/realms/rut-stag/protocol/openid-connect/token  (client_id api-stag)
  prod: .../auth/realms/rut/protocol/openid-connect/token       (client_id api-prod)

El token dura pocos minutos, así que lo cacheamos en Redis (por emisor y
ambiente) y lo renovamos antes de que expire.
"""
import hashlib
import logging

import redis
import requests

from api.models.database import Emisor
from api.services import emisores
from api.services.cache import redis_client
from config.settings import endpoints_hacienda

logger = logging.getLogger(__name__)

MARGEN_SEGURIDAD_SEGUNDOS = 30  # renovar un poco antes de que expire


class HaciendaAuthError(Exception):
    pass


def _cache_key(emisor: Emisor) -> str:
    # El token depende del emisor, del ambiente y del usuario: nunca mezclarlos.
    usuario = hashlib.sha256((emisor.hacienda_usuario or "").encode()).hexdigest()[:16]
    return f"hacienda:{emisor.ambiente}:{emisor.id}:{usuario}:access_token"


def _solicitar_token_nuevo(emisor: Emisor) -> dict:
    try:
        usuario, password = emisores.credenciales(emisor)
    except emisores.EmisorIncompletoError as exc:
        raise HaciendaAuthError(str(exc)) from exc

    ep = endpoints_hacienda(emisor.ambiente)
    payload = {
        "grant_type": "password",
        "client_id": ep["client_id"],
        "username": usuario,
        "password": password,
    }
    try:
        resp = requests.post(ep["token_url"], data=payload, timeout=15)
    except requests.RequestException as exc:
        raise HaciendaAuthError(f"No se pudo contactar el IDP de Hacienda: {exc}") from exc

    if resp.status_code != 200:
        raise HaciendaAuthError(
            f"No se pudo autenticar contra Hacienda (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()


def obtener_token(emisor: Emisor, forzar: bool = False) -> str:
    """Devuelve un access_token válido del emisor, usando caché en Redis."""
    key = _cache_key(emisor)
    if not forzar:
        try:
            cached = redis_client().get(key)
        except redis.RedisError:
            cached = None
        if cached:
            return cached

    data = _solicitar_token_nuevo(emisor)
    access_token = data["access_token"]
    ttl = max(int(data.get("expires_in", 300)) - MARGEN_SEGURIDAD_SEGUNDOS, 30)
    try:
        redis_client().set(key, access_token, ex=ttl)
    except redis.RedisError:
        logger.warning("No se pudo cachear el token de Hacienda")
    return access_token


def invalidar_token_cache(emisor: Emisor):
    """Llamar esto si Hacienda responde 401 con el token actual, para forzar renovación."""
    try:
        redis_client().delete(_cache_key(emisor))
    except redis.RedisError:
        pass
