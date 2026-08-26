"""
Endpoint que Hacienda invoca (vía el "callbackUrl" que enviamos en el POST
de recepción) cuando termina de procesar un comprobante.

⚠️ Este endpoint DEBE ser público, HTTPS, y responder rápido (2xx). Valida
el payload real contra la documentación oficial antes de producción: el
formato exacto puede variar y esto es una estructura razonable basada en
el patrón general de notificación de Hacienda.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.models.database import get_db, Factura, FacturaEvento, EstadoFactura

router = APIRouter(prefix="/api/v1/hacienda", tags=["hacienda-callback"])


@router.post("/callback")
async def recibir_callback(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()

    clave = payload.get("clave")
    if not clave:
        return {"ok": False, "error": "payload sin clave"}

    factura = db.query(Factura).filter(Factura.clave == clave).first()
    if not factura:
        # No lanzamos error 4xx/5xx para que Hacienda no reintente indefinidamente
        # algo que no podemos procesar; solo lo registramos.
        return {"ok": True, "warning": "clave no encontrada en nuestra BD"}

    estado_raw = (payload.get("estado") or payload.get("ind-estado") or "").lower()

    if "acept" in estado_raw:
        factura.estado = EstadoFactura.ACEPTADO
    elif "rechaz" in estado_raw:
        factura.estado = EstadoFactura.RECHAZADO

    factura.estado_hacienda = estado_raw
    factura.xml_respuesta = payload.get("respuestaXml")

    db.add(FacturaEvento(
        factura_id=factura.id,
        evento="CALLBACK_RECIBIDO",
        detalle=str(payload)[:2000],
    ))
    db.commit()

    # TODO: aquí es un buen lugar para notificar a tu propio cliente
    # (webhook saliente, correo, websocket) de que su factura ya tiene
    # resultado final.

    return {"ok": True}
