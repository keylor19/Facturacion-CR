"""Cliente Redis compartido (tokens de Hacienda y caché de consultas públicas)."""
import json
import logging
from functools import lru_cache

import redis

from config.settings import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def redis_client() -> redis.Redis:
    return redis.from_url(get_settings().REDIS_URL, decode_responses=True, socket_timeout=5)


def obtener_json(clave: str):
    """Lee del caché; si Redis no está disponible se comporta como un fallo de caché."""
    try:
        valor = redis_client().get(clave)
    except redis.RedisError:
        logger.warning("Redis no disponible leyendo %s", clave)
        return None
    return json.loads(valor) if valor else None


def guardar_json(clave: str, valor, ttl: int) -> None:
    try:
        redis_client().set(clave, json.dumps(valor, default=str), ex=ttl)
    except redis.RedisError:
        logger.warning("Redis no disponible guardando %s", clave)
