"""
Notificaciones salientes (webhooks) a los sistemas cliente cuando cambia el
estado de un documento.

Cada POST lleva:
  X-Facturacion-Evento: comprobante.aceptado | comprobante.rechazado | ...
  X-Facturacion-Firma:  sha256=<HMAC-SHA256 del cuerpo con el secreto del webhook>
El receptor debe validar la firma antes de confiar en el contenido.
"""
import hashlib
import hmac
import json

import requests

from api.models.database import DocumentoRecibido, Factura


class WebhookError(Exception):
    pass


def firmar(cuerpo: bytes, secreto: str) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def payload_factura(f: Factura, evento: str) -> dict:
    return {
        "evento": evento,
        "tipo": "comprobante",
        "id": str(f.id),
        "emisor_id": str(f.emisor_id),
        "referencia_externa": f.referencia_externa,
        "clave": f.clave,
        "tipo_documento": f.tipo_documento,
        "estado": f.estado.value,
        "estado_hacienda": f.estado_hacienda,
        "mensaje_hacienda": f.mensaje_hacienda,
        "monto_total": str(f.monto_total),
    }


def payload_recibido(d: DocumentoRecibido, evento: str) -> dict:
    return {
        "evento": evento,
        "tipo": "mensaje_receptor",
        "id": str(d.id),
        "emisor_id": str(d.emisor_id),
        "clave": d.clave,
        "consecutivo_receptor": d.consecutivo_receptor,
        "mensaje": d.mensaje,
        "estado": d.estado.value if d.estado else None,
        "estado_hacienda": d.estado_hacienda,
        "mensaje_hacienda": d.mensaje_hacienda,
    }


def enviar(url: str, secreto: str, payload: dict) -> None:
    cuerpo = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Facturacion-Evento": payload["evento"],
        "X-Facturacion-Firma": firmar(cuerpo, secreto),
        "User-Agent": "facturacion-cr-webhook/1.0",
    }
    try:
        resp = requests.post(url, data=cuerpo, headers=headers, timeout=10, allow_redirects=False)
    except requests.RequestException as exc:
        raise WebhookError(str(exc)) from exc
    if not 200 <= resp.status_code < 300:
        raise WebhookError(f"El webhook respondió HTTP {resp.status_code}")
