"""
Autenticación contra Hacienda vía OpenID Connect (OAuth2 - grant_type password).

Endpoint real:
  https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token

Usuario: cpf-01-1234-5678@comprobanteselectronicos.go.cr  (persona física)
      o: cpj-02-3101123456@comprobanteselectronicos.go.cr  (persona jurídica)
Contraseña: la que Hacienda envía al buzón electrónico tras activar el
            módulo de Comprobantes Electrónicos en ATV.

El token dura ~10 minutos (Keycloak estándar de Hacienda), así que lo
cacheamos en Redis y lo renovamos antes de que expire.
"""
import time
import requests
import redis

from config.settings import get_settings

settings = get_settings()
_redis = redis.from_url(settings.REDIS_URL, decode_responses=True)

TOKEN_CACHE_KEY = "hacienda:access_token"
MARGEN_SEGURIDAD_SEGUNDOS = 30  # renovar un poco antes de que expire


class HaciendaAuthError(Exception):
    pass


def _solicitar_token_nuevo() -> dict:
    # ⚠️ VERIFICAR: el "client_id" exacto para cada ambiente (stag/prod) debe
    # confirmarse contra el "Anexo 1 - Especificaciones técnicas" vigente que
    # descargues de ATV, ya que Hacienda lo documenta ahí y puede variar según
    # el realm. Los valores de abajo son el patrón típico reportado por
    # integradores, pero no los des por definitivos sin comprobarlos tú mismo
    # con una prueba real de `curl` contra el endpoint de token.
    payload = {
        "grant_type": "password",
        "client_id": "api-stag" if settings.AMBIENTE == "stag" else "api-prod",
        "username": settings.HACIENDA_USERNAME,
        "password": settings.HACIENDA_PASSWORD,
    }
    resp = requests.post(settings.HACIENDA_TOKEN_URL, data=payload, timeout=15)

    if resp.status_code != 200:
        raise HaciendaAuthError(
            f"No se pudo autenticar contra Hacienda ({resp.status_code}): {resp.text}"
        )

    return resp.json()


def obtener_token() -> str:
    """
    Devuelve un access_token válido. Usa caché en Redis para no pedir un
    token nuevo en cada factura (Hacienda podría empezar a rechazarte por
    exceso de solicitudes de autenticación).
    """
    cached = _redis.get(TOKEN_CACHE_KEY)
    if cached:
        return cached

    data = _solicitar_token_nuevo()
    access_token = data["access_token"]
    expires_in = int(data.get("expires_in", 300))

    ttl = max(expires_in - MARGEN_SEGURIDAD_SEGUNDOS, 30)
    _redis.set(TOKEN_CACHE_KEY, access_token, ex=ttl)

    return access_token


def invalidar_token_cache():
    """Llamar esto si Hacienda responde 401 con el token actual, para forzar renovación."""
    _redis.delete(TOKEN_CACHE_KEY)
