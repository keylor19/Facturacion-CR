"""Punto de venta: apertura y cierre de caja, ventas del turno y movimientos de efectivo."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Caja, Emisor, get_db
from api.models.schemas import (
    CajaAbrir, CajaCerrar, FacturaDetalleResponse, FacturaRequest, FacturaResponse, MovimientoCajaRequest,
)
from api.routes.facturas import _detalle, _emitir
from api.security import Principal, autenticar, emisor_facturacion_web, permiso
from api.services import auditoria, cajas

router = APIRouter(prefix="/api/v1/cajas", tags=["facturación en línea: punto de venta"], dependencies=[Depends(permiso("pos"))])


def _buscar(db: Session, emisor: Emisor, caja_id: UUID) -> Caja:
    caja = db.get(Caja, str(caja_id))
    if not caja or caja.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Caja no encontrada")
    return caja


def _error(exc: cajas.CajaError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("")
def listar(estado: str | None = Query(default=None, pattern="^(ABIERTA|CERRADA)$"),
           limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0),
           emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    query = select(Caja).where(Caja.emisor_id == emisor.id)
    if estado:
        query = query.where(Caja.estado == estado)
    query = query.order_by(Caja.abierta_en.desc()).limit(limit).offset(offset)
    return [cajas.a_dict(db, c) for c in db.scalars(query)]


@router.post("", status_code=201)
def abrir(payload: CajaAbrir, principal: Principal = Depends(autenticar),
          emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    try:
        caja = cajas.abrir(db, emisor, payload.sucursal, payload.terminal, payload.monto_apertura, payload.notas,
                           auditoria.nombre_actor(db, principal))
    except cajas.CajaError as exc:
        raise _error(exc)
    return cajas.a_dict(db, caja, detalle=True)


@router.get("/{caja_id}")
def obtener(caja_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    return cajas.a_dict(db, _buscar(db, emisor, caja_id), detalle=True)


@router.get("/{caja_id}/ventas", response_model=list[FacturaDetalleResponse])
def ventas(caja_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    return [_detalle(f) for f in cajas.ventas(db, _buscar(db, emisor, caja_id))]


@router.post("/{caja_id}/ventas", response_model=FacturaResponse, status_code=202)
def vender(caja_id: UUID, payload: FacturaRequest, response: Response,
           emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """Emite la venta con la sucursal y terminal de la caja y la suma al turno."""
    caja = _buscar(db, emisor, caja_id)
    if caja.estado != "ABIERTA":
        raise HTTPException(status_code=409, detail="La caja está cerrada; abra un turno nuevo para vender")
    if payload.tipo_documento not in ("01", "04"):
        raise HTTPException(status_code=422, detail="En el punto de venta solo se emiten facturas y tiquetes")
    payload.sucursal, payload.terminal = caja.sucursal, caja.terminal
    return _emitir(db, emisor, payload, response, caja_id=caja.id)


@router.post("/{caja_id}/movimientos", status_code=201)
def movimiento(caja_id: UUID, payload: MovimientoCajaRequest, principal: Principal = Depends(autenticar),
               emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    caja = _buscar(db, emisor, caja_id)
    try:
        cajas.movimiento(db, caja, payload.tipo, payload.monto, payload.motivo, auditoria.nombre_actor(db, principal))
    except cajas.CajaError as exc:
        raise _error(exc)
    return cajas.a_dict(db, caja, detalle=True)


@router.post("/{caja_id}/cerrar")
def cerrar(caja_id: UUID, payload: CajaCerrar, principal: Principal = Depends(autenticar),
           emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """Arqueo: compara el efectivo contado con el esperado y deja el resumen fijo."""
    caja = _buscar(db, emisor, caja_id)
    try:
        cajas.cerrar(db, caja, payload.monto_contado, payload.notas, auditoria.nombre_actor(db, principal))
    except cajas.CajaError as exc:
        raise _error(exc)
    return cajas.a_dict(db, caja, detalle=True)
