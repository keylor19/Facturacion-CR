"""
Endpoint que Hacienda invoca (vía el "callbackUrl" que enviamos en el POST
de recepción) cuando termina de procesar un comprobante o mensaje receptor.

Seguridad:
  - La URL lleva un token secreto (CALLBACK_TOKEN) para que no cualquiera
    pueda invocarla.
  - Aun así NO confiamos en el contenido: solo registramos el aviso y
    encolamos una consulta de estado autenticada contra Hacienda, que es la
    fuente de verdad. Así nadie puede marcar un documento como ACEPTADO
    enviando un JSON falso.

Debe ser público, HTTPS y responder rápido (2xx). Limitar el tamaño del
cuerpo en el proxy (NGINX: client_max_body_size 1m).
"""
import logging
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import get_db, DocumentoRecibido, Factura, FacturaEvento
from api.security import verificar_secreto
from config.settings import get_settings
from workers.tasks import consultar_documento

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/hacienda", tags=["hacienda-callback"], include_in_schema=False)

RE_CLAVE = re.compile(r"^(\d{50})(?:-(\d{20}))?$")


@router.post("/callback/{token}")
def recibir_callback(token: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.CALLBACK_TOKEN or not verificar_secreto(token, [settings.CALLBACK_TOKEN]):
        raise HTTPException(status_code=404)

    clave = str(payload.get("clave") or "")
    coincidencia = RE_CLAVE.match(clave)
    if not coincidencia:
        return {"ok": False, "error": "payload sin clave válida"}

    estado_reportado = str(payload.get("ind-estado") or payload.get("estado") or "")[:50]

    if coincidencia.group(2):
        # Mensaje receptor: clave-consecutivoReceptor
        doc = db.scalar(select(DocumentoRecibido).where(DocumentoRecibido.clave_consulta == clave))
        tipo, campo = "recibido", "documento_recibido_id"
    else:
        doc = db.scalar(select(Factura).where(Factura.clave == clave))
        tipo, campo = "factura", "factura_id"
        if doc is None:
            # Algunos avisos de mensaje receptor traen solo la clave del comprobante
            doc = db.scalar(select(DocumentoRecibido).where(
                DocumentoRecibido.clave == clave, DocumentoRecibido.clave_consulta.is_not(None)
            ).order_by(DocumentoRecibido.fecha_mensaje.desc()).limit(1))
            tipo, campo = "recibido", "documento_recibido_id"

    if doc is None:
        # No devolvemos 4xx/5xx para que Hacienda no reintente indefinidamente.
        logger.warning("Callback de Hacienda para clave desconocida %s", clave)
        return {"ok": True}

    db.add(FacturaEvento(**{campo: doc.id}, evento="CALLBACK_RECIBIDO", detalle=f"ind-estado={estado_reportado}"))
    db.commit()

    # Verificación contra Hacienda (autenticada) antes de cambiar el estado.
    try:
        consultar_documento.delay(tipo, str(doc.id))
    except Exception:
        logger.exception("No se pudo encolar la consulta de estado para %s", clave)

    return {"ok": True}
