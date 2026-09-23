"""
Límite de solicitudes por minuto (ventana fija en Redis). Protege el servicio
de que un cliente lo sature. Si Redis no está disponible se deja pasar: es
preferible no bloquear la facturación por una falla del limitador.
"""
import time

import redis
from fastapi import HTTPException, status

from api.services.cache import redis_client


def contar(clave: str, ventana: int = 60) -> tuple[int, int]:
    """Incrementa el contador de la ventana actual. Devuelve (conteo, segundos restantes)."""
    ahora = int(time.time())
    llave = f"lim:{clave}:{ahora // ventana}"
    try:
        r = redis_client()
        n = r.incr(llave)
        if n == 1:
            r.expire(llave, ventana + 5)
    except redis.RedisError:
        return 0, 0
    return int(n), ventana - ahora % ventana


def aplicar(clave: str, limite: int, ventana: int = 60) -> None:
    if limite <= 0:
        return
    n, restante = contar(clave, ventana)
    if n > limite:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Demasiadas solicitudes: máximo {limite} por minuto. Intente de nuevo en {restante} s.",
            headers={"Retry-After": str(max(restante, 1))},
        )
