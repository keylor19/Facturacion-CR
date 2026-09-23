"""
Cliente del API de Recepción de Comprobantes Electrónicos de Hacienda.

  POST /recepcion              envía un comprobante o un mensaje receptor
  GET  /recepcion/{clave}      estado de un comprobante
  GET  /recepcion/{clave}-{consecutivoReceptor}  estado de un mensaje receptor
  GET  /comprobantes           listado de comprobantes (emitidos o recibidos)
  GET  /comprobantes/{clave}   detalle de un comprobante

Base: api-sandbox (stag) o api (prod) según el ambiente del emisor.
Cuando Hacienda rechaza la recepción, el motivo viene en el header
"X-Error-Cause", no en el cuerpo.
"""
import base64
import logging
import re

import requests

from api.models.database import Emisor
from api.services.hacienda_auth import obtener_token, invalidar_token_cache
from api.services.xml_seguro import parsear
from config.settings import endpoints_hacienda, get_settings

logger = logging.getLogger(__name__)

RE_CLAVE_CONSULTA = re.compile(r"^\d{50}(-\d{20})?$")


class HaciendaClientError(Exception):
    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def callback_url() -> str | None:
    s = get_settings()
    if not s.CALLBACK_TOKEN:
        return None
    return f"{s.CALLBACK_BASE_URL.rstrip('/')}/api/v1/hacienda/callback/{s.CALLBACK_TOKEN}"


def error_cause(resp: requests.Response) -> str:
    """Motivo del rechazo que Hacienda envía en el header X-Error-Cause."""
    return resp.headers.get("X-Error-Cause") or resp.text[:2000] or f"HTTP {resp.status_code}"


def _base(emisor: Emisor) -> str:
    return endpoints_hacienda(emisor.ambiente)["api_base"].rstrip("/")


def _request(emisor: Emisor, method: str, path: str, **kwargs) -> requests.Response:
    """Petición autenticada; si Hacienda responde 401 renueva el token y reintenta UNA vez."""
    def _hacer():
        headers = {"Authorization": f"Bearer {obtener_token(emisor)}", "Content-Type": "application/json"}
        return requests.request(method, f"{_base(emisor)}{path}", headers=headers, **kwargs)

    resp = _hacer()
    if resp.status_code == 401:
        invalidar_token_cache(emisor)
        resp = _hacer()
    return resp


def enviar(emisor: Emisor, envio_json: dict, xml_firmado: str) -> requests.Response:
    """
    POST /recepcion. `envio_json` trae clave, fecha, emisor, receptor y
    (para mensajes receptor) consecutivoReceptor. Devuelve la respuesta cruda:
    202 = RECEPCIÓN aceptada (la aceptación fiscal llega por callback/consulta).
    """
    body = dict(envio_json)
    body["comprobanteXml"] = base64.b64encode(xml_firmado.encode("utf-8")).decode("ascii")
    url = callback_url()
    if url:
        body["callbackUrl"] = url
    return _request(emisor, "POST", "/recepcion", json=body, timeout=30)


def consultar_estado(emisor: Emisor, clave_consulta: str) -> dict:
    """GET /recepcion/{clave} (o {clave}-{consecutivoReceptor} para mensajes receptor)."""
    if not RE_CLAVE_CONSULTA.match(clave_consulta):
        raise ValueError("Clave inválida")

    resp = _request(emisor, "GET", f"/recepcion/{clave_consulta}", timeout=15)
    if resp.status_code == 404:
        raise HaciendaClientError(f"Hacienda no tiene registro de {clave_consulta}", status_code=404)
    if resp.status_code != 200:
        raise HaciendaClientError(
            f"Error consultando estado en Hacienda: {resp.status_code} {error_cause(resp)}",
            status_code=resp.status_code, body=resp.text[:2000],
        )
    return resp.json()


def listar_comprobantes(emisor: Emisor, params: dict) -> tuple[list, str | None]:
    """
    GET /comprobantes. Parámetros de Hacienda: offset, limit, emisor, receptor
    (identificaciones con formato tipo+número, p. ej. 02003101123456).
    Devuelve (lista, header Content-Range para paginar).
    """
    params = {k: v for k, v in params.items() if v not in (None, "")}
    resp = _request(emisor, "GET", "/comprobantes", params=params, timeout=30)
    if resp.status_code not in (200, 206):
        raise HaciendaClientError(
            f"Error listando comprobantes: {resp.status_code} {error_cause(resp)}", status_code=resp.status_code
        )
    return resp.json(), resp.headers.get("Content-Range")


def obtener_comprobante(emisor: Emisor, clave: str) -> dict:
    """GET /comprobantes/{clave}."""
    if not re.fullmatch(r"\d{50}", clave):
        raise ValueError("Clave inválida")
    resp = _request(emisor, "GET", f"/comprobantes/{clave}", timeout=30)
    if resp.status_code == 404:
        raise HaciendaClientError(f"Hacienda no tiene registro de {clave}", status_code=404)
    if resp.status_code != 200:
        raise HaciendaClientError(
            f"Error consultando comprobante: {resp.status_code} {error_cause(resp)}", status_code=resp.status_code
        )
    return resp.json()


def interpretar_respuesta(data: dict) -> dict:
    """
    Normaliza la respuesta de Hacienda (consulta o callback):
      {"estado": "aceptado|rechazado|procesando|recibido|error|...",
       "xml": <MensajeHacienda decodificado o None>,
       "mensaje": <DetalleMensaje o None>}
    """
    estado = str(data.get("ind-estado") or data.get("estado") or "").strip().lower()
    xml_b64 = data.get("respuesta-xml") or data.get("respuestaXml")

    xml = mensaje = None
    if xml_b64:
        try:
            xml = base64.b64decode(xml_b64, validate=True).decode("utf-8")
            root = parsear(xml)
            detalle = root.find(".//{*}DetalleMensaje")
            mensaje = detalle.text.strip() if detalle is not None and detalle.text else None
        except Exception:
            logger.warning("No se pudo decodificar respuesta-xml de Hacienda", exc_info=True)

    return {"estado": estado, "xml": xml, "mensaje": mensaje}
