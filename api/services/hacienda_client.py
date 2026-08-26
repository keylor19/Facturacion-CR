"""
Cliente hacia el API de Recepción de Comprobantes Electrónicos de Hacienda.

Base real: https://api.comprobanteselectronicos.go.cr/recepcion/v1/
Auth: Bearer token OIDC (ver hacienda_auth.py)

El POST /recepcion espera JSON (no el XML crudo como archivo) con el XML
firmado codificado en Base64 dentro del campo "comprobanteXml", más un
"callbackUrl" opcional para que Hacienda te avise cuando termine de
procesar en vez de que hagas polling.
"""
import base64
import requests

from config.settings import get_settings
from api.services.hacienda_auth import obtener_token, invalidar_token_cache

settings = get_settings()


class HaciendaClientError(Exception):
    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _headers():
    return {
        "Authorization": f"Bearer {obtener_token()}",
        "Content-Type": "application/json",
    }


def enviar_comprobante(
    clave: str,
    fecha_iso: str,
    emisor_tipo_identificacion: str,
    emisor_numero_identificacion: str,
    receptor_tipo_identificacion: str | None,
    receptor_numero_identificacion: str | None,
    xml_firmado: str,
    callback_path: str = "/api/v1/hacienda/callback",
) -> requests.Response:
    """
    Envía el comprobante a Hacienda. Devuelve la respuesta cruda de requests
    para que el llamador decida cómo interpretarla (Hacienda responde 201/202
    de aceptación de RECEPCIÓN, que NO es lo mismo que aceptación fiscal del
    comprobante — eso llega luego por el callback o por consulta de estado).
    """
    xml_b64 = base64.b64encode(xml_firmado.encode("utf-8")).decode("utf-8")

    body = {
        "clave": clave,
        "fecha": fecha_iso,
        "emisor": {
            "tipoIdentificacion": emisor_tipo_identificacion,
            "numeroIdentificacion": emisor_numero_identificacion,
        },
        "comprobanteXml": xml_b64,
        "callbackUrl": f"{settings.CALLBACK_BASE_URL}{callback_path}",
    }

    if receptor_numero_identificacion:
        body["receptor"] = {
            "tipoIdentificacion": receptor_tipo_identificacion,
            "numeroIdentificacion": receptor_numero_identificacion,
        }

    resp = requests.post(
        f"{settings.HACIENDA_API_BASE}/recepcion",
        json=body,
        headers=_headers(),
        timeout=30,
    )

    if resp.status_code == 401:
        # Token vencido a mitad de operación: renovar y reintentar UNA vez
        invalidar_token_cache()
        resp = requests.post(
            f"{settings.HACIENDA_API_BASE}/recepcion",
            json=body,
            headers=_headers(),
            timeout=30,
        )

    return resp


def consultar_estado(clave: str) -> dict:
    """GET /recepcion/{clave} — consulta el estado actual de un comprobante."""
    resp = requests.get(
        f"{settings.HACIENDA_API_BASE}/recepcion/{clave}",
        headers=_headers(),
        timeout=15,
    )

    if resp.status_code == 404:
        raise HaciendaClientError(
            f"Hacienda no tiene registro de la clave {clave}",
            status_code=404,
        )
    if resp.status_code != 200:
        raise HaciendaClientError(
            f"Error consultando estado en Hacienda: {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text,
        )

    return resp.json()
