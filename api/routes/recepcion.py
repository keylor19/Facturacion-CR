"""Comprobantes recibidos de proveedores y Mensaje Receptor (aceptar / rechazar)."""
from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import get_db, DocumentoRecibido, Emisor, EstadoFactura, ESTADOS_REENVIABLES
from api.models.schemas import (
    DocumentoRecibidoRequest, DocumentoRecibidoResponse, MensajeReceptorRequest, EventoResponse,
)
from api.security import emisor_actual
from api.services import recepcion
from api.services.emision import EmisionError
from api.routes.facturas import informar_saldo
from api.services.fechas import zona_cr
from workers.tasks import enviar_documento, consultar_documento

router = APIRouter(prefix="/api/v1/recepcion", tags=["comprobantes recibidos"])


def _respuesta(d: DocumentoRecibido) -> DocumentoRecibidoResponse:
    return DocumentoRecibidoResponse(
        id=str(d.id), emisor_id=str(d.emisor_id), clave=d.clave, tipo_documento=d.tipo_documento,
        fecha_emision=d.fecha_emision, proveedor_identificacion=d.proveedor_identificacion,
        proveedor_nombre=d.proveedor_nombre, moneda=d.moneda, total_impuesto=d.total_impuesto,
        total_comprobante=d.total_comprobante, firma_valida=d.firma_valida, mensaje=d.mensaje,
        condicion_impuesto=d.condicion_impuesto, monto_impuesto_acreditar=d.monto_impuesto_acreditar,
        consecutivo_receptor=d.consecutivo_receptor, estado=d.estado.value if d.estado else None,
        estado_hacienda=d.estado_hacienda, mensaje_hacienda=d.mensaje_hacienda,
    )


def _buscar(db: Session, emisor: Emisor, doc_id: UUID) -> DocumentoRecibido:
    doc = db.get(DocumentoRecibido, str(doc_id))
    if not doc or doc.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


def _registrar(db, emisor, xml: bytes, respuesta: bytes | None) -> DocumentoRecibidoResponse:
    try:
        return _respuesta(recepcion.registrar_documento(db, emisor, xml, respuesta))
    except EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("", response_model=DocumentoRecibidoResponse, status_code=201)
def registrar_documento(
    payload: DocumentoRecibidoRequest, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """Registra el XML de un comprobante recibido (en base64)."""
    try:
        xml = recepcion.decodificar_base64(payload.xml_base64, "xml_base64")
        respuesta = recepcion.decodificar_base64(payload.respuesta_hacienda_base64, "respuesta_hacienda_base64") \
            if payload.respuesta_hacienda_base64 else None
    except EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return _registrar(db, emisor, xml, respuesta)


@router.post("/archivo", response_model=DocumentoRecibidoResponse, status_code=201)
def registrar_archivo(
    archivo: UploadFile = File(..., description="XML del comprobante del proveedor"),
    respuesta_hacienda: UploadFile | None = File(default=None, description="MensajeHacienda del proveedor (opcional)"),
    emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
):
    """Registra un comprobante recibido subiendo el archivo XML."""
    limite = recepcion.MAX_BYTES_XML
    xml = archivo.file.read(limite + 1)
    respuesta = respuesta_hacienda.file.read(limite + 1) if respuesta_hacienda else None
    if len(xml) > limite or (respuesta and len(respuesta) > limite):
        raise HTTPException(status_code=413, detail="Archivo demasiado grande")
    return _registrar(db, emisor, xml, respuesta)


@router.get("", response_model=list[DocumentoRecibidoResponse])
def listar_documentos(
    pendientes: bool = Query(default=False, description="Solo los que aún no tienen mensaje receptor"),
    estado: EstadoFactura | None = None,
    proveedor: str | None = Query(default=None, max_length=20),
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
):
    query = select(DocumentoRecibido).where(DocumentoRecibido.emisor_id == emisor.id)
    if pendientes:
        query = query.where(DocumentoRecibido.estado.is_(None))
    if estado:
        query = query.where(DocumentoRecibido.estado == estado)
    if proveedor:
        query = query.where(DocumentoRecibido.proveedor_identificacion == proveedor)
    if desde:
        query = query.where(DocumentoRecibido.fecha_emision >= datetime.combine(desde, time.min, zona_cr()))
    if hasta:
        query = query.where(DocumentoRecibido.fecha_emision <= datetime.combine(hasta, time.max, zona_cr()))
    query = query.order_by(DocumentoRecibido.fecha_emision.desc()).limit(limit).offset(offset)
    return [_respuesta(d) for d in db.scalars(query)]


@router.get("/{doc_id}", response_model=DocumentoRecibidoResponse)
def obtener_documento(doc_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    return _respuesta(_buscar(db, emisor, doc_id))


@router.get("/{doc_id}/eventos", response_model=list[EventoResponse])
def eventos_documento(doc_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    doc = _buscar(db, emisor, doc_id)
    return [EventoResponse(evento=e.evento, detalle=e.detalle, fecha=e.created_at) for e in doc.eventos]


@router.get("/{doc_id}/xml")
def obtener_xml(
    doc_id: UUID,
    tipo: Literal["original", "mensaje", "respuesta"] = Query(default="original"),
    emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
):
    """original = XML del proveedor, mensaje = MensajeReceptor firmado, respuesta = respuesta de Hacienda."""
    doc = _buscar(db, emisor, doc_id)
    contenido = {"original": doc.xml_original, "mensaje": doc.xml_firmado, "respuesta": doc.xml_respuesta}[tipo]
    if not contenido:
        raise HTTPException(status_code=404, detail="XML no disponible")
    return Response(content=contenido, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{doc.clave}-{tipo}.xml"'})


@router.post("/{doc_id}/mensaje", response_model=DocumentoRecibidoResponse, status_code=202)
def enviar_mensaje_receptor(
    doc_id: UUID, payload: MensajeReceptorRequest, response: Response,
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """Acepta (1), acepta parcialmente (2) o rechaza (3) el comprobante ante Hacienda. Consume 1 documento."""
    doc = _buscar(db, emisor, doc_id)
    try:
        doc = recepcion.crear_mensaje_receptor(db, doc, payload)
    except EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    informar_saldo(db, emisor, response)
    try:
        enviar_documento.delay("recibido", str(doc.id))
    except Exception:
        pass  # queda PENDIENTE y beat lo reenvía
    return _respuesta(doc)


@router.post("/{doc_id}/reenviar", response_model=DocumentoRecibidoResponse)
def reenviar_mensaje(doc_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    doc = _buscar(db, emisor, doc_id)
    if doc.estado == EstadoFactura.ENVIADO:
        consultar_documento.delay("recibido", str(doc.id))
    elif doc.estado in ESTADOS_REENVIABLES:
        enviar_documento.delay("recibido", str(doc.id))
    else:
        raise HTTPException(status_code=409, detail="No hay un mensaje receptor pendiente de envío")
    return _respuesta(doc)
