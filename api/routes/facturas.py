"""Comprobantes emitidos: 01, 02, 03, 04, 08, 09 y recibos de pago (10)."""
import logging
from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import get_db, Emisor, Factura, EstadoFactura, ESTADOS_REENVIABLES
from api.models.schemas import (
    FacturaRequest, FacturaResponse, FacturaDetalleResponse, AnularRequest, CorreoRequest, EventoResponse,
    ReciboPagoRequest,
)
from api.security import emisor_actual
from api.services import emision, saldo
from api.services.fechas import zona_cr
from api.services.pdf import generar_pdf
from config.settings import get_settings
from workers.tasks import enviar_documento, consultar_documento, enviar_correo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/facturas", tags=["comprobantes emitidos"])


def _detalle(f: Factura) -> FacturaDetalleResponse:
    return FacturaDetalleResponse(
        factura_id=str(f.id),
        emisor_id=str(f.emisor_id),
        referencia_externa=f.referencia_externa,
        tipo_documento=f.tipo_documento,
        clave=f.clave,
        numero_consecutivo=f.numero_consecutivo,
        estado=f.estado.value,
        estado_hacienda=f.estado_hacienda,
        mensaje_hacienda=f.mensaje_hacienda,
        receptor_nombre=f.receptor_nombre,
        receptor_identificacion=f.receptor_identificacion,
        moneda=f.moneda,
        tipo_cambio=f.tipo_cambio,
        total_venta=f.total_venta,
        total_descuentos=f.total_descuentos,
        total_otros_cargos=f.total_otros_cargos,
        monto_impuesto=f.monto_impuesto,
        monto_total=f.monto_total,
        fecha_emision=f.fecha_emision,
        correo_enviado=f.correo_enviado,
        situacion=f.situacion,
        total_exento=f.total_exento,
        total_exonerado=f.total_exonerado,
        total_no_sujeto=f.total_no_sujeto,
        total_iva_devuelto=f.total_iva_devuelto,
        condicion_venta=f.condicion_venta,
        factura_origen_id=str(f.factura_origen_id) if f.factura_origen_id else None,
    )


def _respuesta(f: Factura, message: str) -> FacturaResponse:
    return FacturaResponse(factura_id=str(f.id), clave=f.clave, estado=f.estado.value, message=message)


def _encolar_envio(factura_id: str) -> None:
    """Si Redis no está disponible el comprobante queda PENDIENTE y beat lo reenvía luego."""
    try:
        enviar_documento.delay("factura", factura_id)
    except Exception:
        logger.exception("No se pudo encolar el envío de la factura %s", factura_id)


def _buscar(db: Session, emisor: Emisor, factura_id: UUID) -> Factura:
    factura = db.get(Factura, str(factura_id))
    # Aislamiento: un emisor nunca ve documentos de otro (404, no 403, para no revelar que existe)
    if not factura or factura.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    return factura


def informar_saldo(db: Session, emisor: Emisor, response: Response) -> None:
    """Encabezado X-Documentos-Disponibles para que el sistema cliente vea su saldo en cada emisión."""
    if saldo.control_activo():
        response.headers["X-Documentos-Disponibles"] = str(saldo.disponible(db, emisor.id))


def _emitir(db, emisor, datos, response: Response, factura_origen_id=None) -> FacturaResponse:
    try:
        factura, creada = emision.emitir(db, emisor, datos, factura_origen_id=factura_origen_id)
    except emision.EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    informar_saldo(db, emisor, response)
    if not creada:
        response.status_code = 200
        return _respuesta(factura, "Comprobante ya existente para esta referencia_externa.")
    _encolar_envio(str(factura.id))
    return _respuesta(factura, "Comprobante generado, firmado y encolado para envío a Hacienda.")


@router.post("", response_model=FacturaResponse, status_code=202)
def crear_factura(
    payload: FacturaRequest, response: Response,
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    return _emitir(db, emisor, payload, response)


@router.get("", response_model=list[FacturaDetalleResponse])
def listar_facturas(
    estado: EstadoFactura | None = Query(default=None),
    tipo_documento: str | None = Query(default=None, pattern=r"^\d{2}$"),
    referencia_externa: str | None = Query(default=None, max_length=100),
    receptor: str | None = Query(default=None, max_length=20, description="Identificación del receptor"),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
):
    query = select(Factura).where(Factura.emisor_id == emisor.id)
    if estado:
        query = query.where(Factura.estado == estado)
    if tipo_documento:
        query = query.where(Factura.tipo_documento == tipo_documento)
    if referencia_externa:
        query = query.where(Factura.referencia_externa == referencia_externa)
    if receptor:
        query = query.where(Factura.receptor_identificacion == receptor)
    if desde:
        query = query.where(Factura.fecha_emision >= datetime.combine(desde, time.min, zona_cr()))
    if hasta:
        query = query.where(Factura.fecha_emision <= datetime.combine(hasta, time.max, zona_cr()))
    query = query.order_by(Factura.fecha_emision.desc()).limit(limit).offset(offset)
    return [_detalle(f) for f in db.scalars(query)]


@router.get("/{factura_id}", response_model=FacturaDetalleResponse)
def obtener_factura(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    return _detalle(_buscar(db, emisor, factura_id))


@router.get("/{factura_id}/eventos", response_model=list[EventoResponse])
def eventos_factura(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Bitácora de auditoría del comprobante."""
    factura = _buscar(db, emisor, factura_id)
    return [EventoResponse(evento=e.evento, detalle=e.detalle, fecha=e.created_at) for e in factura.eventos]


@router.get("/{factura_id}/xml")
def obtener_xml(
    factura_id: UUID,
    tipo: Literal["firmado", "respuesta"] = Query(default="firmado"),
    emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
):
    """XML firmado (para entregar al cliente) o XML de respuesta de Hacienda."""
    factura = _buscar(db, emisor, factura_id)
    contenido = factura.xml_firmado if tipo == "firmado" else factura.xml_respuesta
    if not contenido:
        raise HTTPException(status_code=404, detail="XML no disponible todavía")
    return Response(
        content=contenido, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{factura.clave}-{tipo}.xml"'},
    )


@router.get("/{factura_id}/pdf")
def obtener_pdf(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Representación gráfica del comprobante."""
    factura = _buscar(db, emisor, factura_id)
    return Response(
        content=generar_pdf(factura), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{factura.clave}.pdf"'},
    )


@router.post("/{factura_id}/anular", response_model=FacturaResponse, status_code=202)
def anular_factura(
    factura_id: UUID, payload: AnularRequest, response: Response,
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """Emite una nota de crédito que anula totalmente el comprobante."""
    original = _buscar(db, emisor, factura_id)
    if emision.notas_activas(db, original):
        raise HTTPException(status_code=409, detail="El comprobante ya tiene una nota de crédito de anulación")
    try:
        datos = emision.datos_anulacion(original, payload.razon, payload.referencia_externa)
    except emision.EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return _emitir(db, emisor, datos, response, factura_origen_id=original.id)


@router.post("/{factura_id}/recibo-pago", response_model=FacturaResponse, status_code=202)
def recibo_pago(
    factura_id: UUID, payload: ReciboPagoRequest, response: Response,
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """
    Emite un Recibo Electrónico de Pago (10) por el pago total o parcial de una
    factura a crédito al Estado (condición 08) o con IVA hasta 90 días (10).
    """
    original = _buscar(db, emisor, factura_id)
    try:
        recibo, creado = emision.emitir_recibo_pago(db, emisor, original, payload)
    except emision.EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    informar_saldo(db, emisor, response)
    if not creado:
        response.status_code = 200
        return _respuesta(recibo, "Recibo ya existente para esta referencia_externa.")
    _encolar_envio(str(recibo.id))
    return _respuesta(recibo, "Recibo electrónico de pago generado y encolado para envío a Hacienda.")


@router.get("/{factura_id}/pagos")
def pagos_factura(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Recibos de pago emitidos y saldo pendiente de una factura a crédito."""
    original = _buscar(db, emisor, factura_id)
    return {
        "total": original.monto_total,
        "saldo_pendiente": emision.saldo_pendiente(db, original),
        "recibos": [_detalle(r) for r in emision.recibos_activos(db, original)],
    }


@router.post("/{factura_id}/reenviar", response_model=FacturaResponse)
def reenviar_factura(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    factura = _buscar(db, emisor, factura_id)

    if factura.estado == EstadoFactura.ENVIADO:
        consultar_documento.delay("factura", str(factura.id))
        return _respuesta(factura, "El comprobante ya fue enviado; se encoló una consulta de estado.")

    if factura.estado not in ESTADOS_REENVIABLES:
        raise HTTPException(
            status_code=409,
            detail=f"No se puede reenviar un comprobante en estado {factura.estado.value}. "
                   "Si fue rechazado, emita un nuevo comprobante corregido.",
        )

    enviar_documento.delay("factura", str(factura.id))
    return _respuesta(factura, "Reenvío encolado.")


@router.post("/{factura_id}/consultar", response_model=FacturaResponse)
def consultar_factura(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Fuerza una consulta de estado a Hacienda."""
    factura = _buscar(db, emisor, factura_id)
    consultar_documento.delay("factura", str(factura.id))
    return _respuesta(factura, "Consulta de estado encolada.")


@router.post("/{factura_id}/correo", response_model=FacturaResponse)
def reenviar_correo(
    factura_id: UUID, payload: CorreoRequest,
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """(Re)envía el comprobante por correo al receptor o a los destinatarios indicados."""
    if not get_settings().smtp_configurado:
        raise HTTPException(status_code=503, detail="El envío de correos no está configurado (SMTP)")
    factura = _buscar(db, emisor, factura_id)
    destinos = [str(d) for d in payload.destinatarios] if payload.destinatarios else None
    if not destinos and not factura.receptor_correo:
        raise HTTPException(status_code=422, detail="El comprobante no tiene correo del receptor; indique destinatarios")
    enviar_correo.delay(str(factura.id), destinos)
    return _respuesta(factura, "Envío de correo encolado.")
