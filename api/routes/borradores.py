"""
Proformas (cotizaciones con PDF) y documentos preliminares (borradores).
Se guardan sin enviar a Hacienda ni consumir saldo; al emitirlos se generan
como cualquier comprobante y quedan enlazados.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.models.database import Borrador, Emisor, get_db
from api.models.schemas import BorradorActualizar, BorradorCrear, BorradorResponse, FacturaResponse
from api.routes.facturas import _emitir
from api.security import Principal, autenticar, emisor_facturacion_web, permiso
from api.services import auditoria, borradores
from api.services.fechas import ahora_cr

router = APIRouter(prefix="/api/v1/borradores", tags=["facturación en línea: proformas y preliminares"],
                   dependencies=[Depends(permiso("emitir"))])


def _buscar(db: Session, emisor: Emisor, borrador_id: UUID) -> Borrador:
    b = db.get(Borrador, str(borrador_id))
    if not b or b.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return b


def _editable(b: Borrador) -> None:
    if b.estado != "ABIERTO":
        raise HTTPException(status_code=409, detail=f"El documento está {b.estado.lower()} y ya no se puede modificar")


@router.get("", response_model=list[BorradorResponse])
def listar(
    clase: Literal["proforma", "preliminar"],
    estado: Literal["ABIERTO", "VENCIDO", "FACTURADO", "ANULADO"] | None = None,
    q: str | None = Query(default=None, max_length=100, description="Cliente o número de proforma"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db),
):
    query = select(Borrador).where(Borrador.emisor_id == emisor.id, Borrador.clase == clase)
    hoy = ahora_cr().date()
    if estado == "VENCIDO":
        query = query.where(Borrador.estado == "ABIERTO", Borrador.vence < hoy)
    elif estado == "ABIERTO":
        query = query.where(Borrador.estado == "ABIERTO", or_(Borrador.vence.is_(None), Borrador.vence >= hoy))
    elif estado:
        query = query.where(Borrador.estado == estado)
    if q:
        texto = q.strip().lower()
        filtros = [func.lower(Borrador.receptor_nombre).contains(texto, autoescape=True),
                   Borrador.receptor_identificacion.contains(texto, autoescape=True)]
        numero = texto.upper().removeprefix("PF-").lstrip("0")
        if numero.isdigit():
            filtros.append(Borrador.numero == int(numero))
        query = query.where(or_(*filtros))
    query = query.order_by(Borrador.created_at.desc()).limit(limit).offset(offset)
    return [borradores.a_respuesta(b) for b in db.scalars(query)]


@router.post("", response_model=BorradorResponse, status_code=201)
def crear(payload: BorradorCrear, principal: Principal = Depends(autenticar),
          emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """La proforma debe estar completa (se entrega al cliente); el preliminar puede guardarse a medias."""
    if payload.clase == "proforma":
        errores = borradores.evaluar(payload.datos)[1]
        if errores:
            raise HTTPException(status_code=422, detail=errores)
    b, _ = borradores.crear(db, emisor, payload.clase, payload.datos, payload.vence, auditoria.nombre_actor(db, principal))
    db.commit()
    return borradores.a_respuesta(b, con_datos=True)


@router.get("/{borrador_id}", response_model=BorradorResponse)
def obtener(borrador_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    return borradores.a_respuesta(_buscar(db, emisor, borrador_id), con_datos=True)


@router.put("/{borrador_id}", response_model=BorradorResponse)
def actualizar(borrador_id: UUID, payload: BorradorActualizar,
               emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    b = _buscar(db, emisor, borrador_id)
    _editable(b)
    if payload.datos is not None:
        if b.clase == "proforma":
            errores = borradores.evaluar(payload.datos)[1]
            if errores:
                raise HTTPException(status_code=422, detail=errores)
        borradores.aplicar_datos(b, payload.datos)
    if payload.vence is not None and b.clase == "proforma":
        b.vence = payload.vence
    db.commit()
    return borradores.a_respuesta(b, con_datos=True)


@router.delete("/{borrador_id}", status_code=204)
def eliminar(borrador_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """El preliminar se borra; la proforma se anula para conservar su número."""
    b = _buscar(db, emisor, borrador_id)
    _editable(b)
    if b.clase == "proforma":
        b.estado = "ANULADO"
    else:
        db.delete(b)
    db.commit()


@router.post("/{borrador_id}/emitir", response_model=FacturaResponse, status_code=202)
def emitir(borrador_id: UUID, response: Response,
           emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """
    Emite el comprobante con los datos guardados. Es idempotente: si ya se
    emitió (o se reintenta tras un error de red) devuelve el mismo comprobante.
    """
    b = _buscar(db, emisor, borrador_id)
    if b.estado == "ANULADO":
        raise HTTPException(status_code=409, detail="La proforma está anulada")
    req, errores = borradores.evaluar(b.datos)
    if not req:
        raise HTTPException(status_code=422, detail=errores)
    if not req.referencia_externa:
        req.referencia_externa = f"borrador-{b.id}"
    respuesta = _emitir(db, emisor, req, response)
    if b.estado != "FACTURADO":
        b.estado = "FACTURADO"
        b.factura_id = respuesta.factura_id
        db.commit()
    return respuesta


@router.get("/{borrador_id}/pdf")
def pdf(borrador_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """PDF de la proforma para enviar al cliente (sin valor fiscal)."""
    b = _buscar(db, emisor, borrador_id)
    if b.clase != "proforma":
        raise HTTPException(status_code=404, detail="Solo las proformas tienen PDF")
    try:
        contenido = borradores.pdf_proforma(b, emisor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return Response(content=contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="proforma-{borradores.numero_visible(b)}.pdf"'})
