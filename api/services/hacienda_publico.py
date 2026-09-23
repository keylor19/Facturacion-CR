"""
Servicios públicos de Hacienda (https://api.hacienda.go.cr, no requieren
credenciales). Las respuestas se cachean en Redis.

  /fe/ae?identificacion=     situación tributaria y actividades económicas
  /fe/ex?autorizacion=       datos de una exoneración
  /fe/cabys?q= | ?codigo=    catálogo CABYS (con su tarifa de IVA)
  /indicadores/tc/dolar      tipo de cambio del dólar (BCCR)
  /indicadores/tc/euro       tipo de cambio del euro

⚠️ El formato de estas respuestas lo define Hacienda y puede cambiar; se
devuelven tal cual, salvo el tipo de cambio que se normaliza.
"""
import logging
import re
from decimal import Decimal, InvalidOperation

import requests

from api.services.cache import obtener_json, guardar_json
from config.settings import get_settings

logger = logging.getLogger(__name__)


class HaciendaPublicoError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _get(path: str, params: dict, cache_key: str, ttl: int):
    cached = obtener_json(cache_key)
    if cached is not None:
        return cached
    url = get_settings().HACIENDA_PUBLIC_API.rstrip("/") + path
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.RequestException as exc:
        raise HaciendaPublicoError(f"No se pudo contactar a Hacienda: {exc}") from exc
    if resp.status_code == 404:
        raise HaciendaPublicoError("No encontrado en Hacienda", status_code=404)
    if resp.status_code == 429:
        raise HaciendaPublicoError("Hacienda limitó las consultas (429); intente más tarde", status_code=503)
    if resp.status_code != 200:
        raise HaciendaPublicoError(f"Hacienda respondió HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise HaciendaPublicoError("Respuesta inválida de Hacienda") from exc
    guardar_json(cache_key, data, ttl)
    return data


def contribuyente(identificacion: str) -> dict:
    if not re.fullmatch(r"\d{9,12}", identificacion):
        raise HaciendaPublicoError("Identificación inválida", status_code=422)
    return _get("/fe/ae", {"identificacion": identificacion}, f"hp:ae:{identificacion}", ttl=3600)


def exoneracion(autorizacion: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9\-]{3,40}", autorizacion):
        raise HaciendaPublicoError("Número de autorización inválido", status_code=422)
    return _get("/fe/ex", {"autorizacion": autorizacion}, f"hp:ex:{autorizacion}", ttl=3600)


def cabys(texto: str | None = None, codigo: str | None = None, top: int = 20):
    if codigo:
        if not re.fullmatch(r"\d{1,13}", codigo):
            raise HaciendaPublicoError("Código CABYS inválido", status_code=422)
        return _get("/fe/cabys", {"codigo": codigo}, f"hp:cabys:c:{codigo}", ttl=86400)
    if not texto or len(texto.strip()) < 3:
        raise HaciendaPublicoError("Indique al menos 3 caracteres para buscar", status_code=422)
    texto = texto.strip()[:100]
    return _get("/fe/cabys", {"q": texto, "top": top}, f"hp:cabys:q:{texto.lower()}:{top}", ttl=86400)


def tipo_cambio(moneda: str) -> Decimal:
    """Tipo de cambio de referencia (venta) en colones para USD o EUR."""
    moneda = moneda.upper()
    if moneda == "USD":
        data = _get("/indicadores/tc/dolar", {}, "hp:tc:usd", ttl=3600)
        valor = (data.get("venta") or {}).get("valor")
    elif moneda == "EUR":
        data = _get("/indicadores/tc/euro", {}, "hp:tc:eur", ttl=3600)
        valor = data.get("colones")
    else:
        raise HaciendaPublicoError(f"Hacienda no publica tipo de cambio para {moneda}; indique tipo_cambio", 422)
    try:
        tc = Decimal(str(valor))
    except (InvalidOperation, TypeError) as exc:
        raise HaciendaPublicoError("Hacienda devolvió un tipo de cambio inválido") from exc
    if tc <= 0:
        raise HaciendaPublicoError("Hacienda devolvió un tipo de cambio inválido")
    return tc
