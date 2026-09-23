"""
Manejo de fechas en hora de Costa Rica.

Los contenedores normalmente corren en UTC: usar datetime.now() "a secas" y
pegarle "-06:00" produce fechas 6 horas en el futuro (Hacienda las rechaza)
y claves con el día equivocado entre las 18:00 y las 24:00.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import get_settings


def zona_cr() -> ZoneInfo:
    return ZoneInfo(get_settings().TIMEZONE)


def ahora_cr() -> datetime:
    """Fecha/hora actual con zona horaria de Costa Rica, sin microsegundos."""
    return datetime.now(zona_cr()).replace(microsecond=0)


def a_iso_cr(dt: datetime) -> str:
    """Formato ISO 8601 con offset que exige Hacienda, p. ej. 2026-09-23T10:15:00-06:00."""
    if dt.tzinfo is None:
        raise ValueError("Se requiere un datetime con zona horaria")
    return dt.astimezone(zona_cr()).replace(microsecond=0).isoformat()
