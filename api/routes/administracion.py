"""Panel del administrador de la plataforma: tablero, diagnóstico de empresas y facturación de ventas."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Emisor, Paquete, Suscripcion, get_db
from api.models.schemas import AjustesVentasRequest, ComprobanteVenta, MedioPagoVenta
from api.routes.facturas import _encolar_envio
from api.security import Principal, require_admin
from api.services import administracion, auditoria
from api.services.cache import guardar_json, obtener_json

router = APIRouter(prefix="/api/v1/admin", tags=["administración"], dependencies=[Depends(require_admin)])


def _emisor(db: Session, emisor_id: UUID) -> Emisor:
    e = db.get(Emisor, str(emisor_id))
    if e is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return e


def _con_cache(clave: str, calcular):
    """
    El tablero y los diagnósticos revisan todas las empresas (varias consultas por cada una):
    se guardan CACHE_TABLERO_SEGUNDOS para que recargar la página no repita todo. Las ventas
    y anulaciones borran el caché (administracion.CLAVES_CACHE_ADMIN).
    """
    guardado = obtener_json(clave)
    if guardado is not None:
        return guardado
    resultado = jsonable_encoder(calcular())
    guardar_json(clave, resultado, administracion.CACHE_TABLERO_SEGUNDOS)
    return resultado


@router.get("/tablero")
def tablero(fresco: bool = Query(default=False, description="Ignorar el caché"), db: Session = Depends(get_db)):
    """Ventas, vencimientos, mejores clientes y empresas con problemas."""
    if fresco:
        return administracion.tablero(db)
    return _con_cache("admin:tablero", lambda: administracion.tablero(db))


@router.get("/diagnosticos")
def diagnosticos(db: Session = Depends(get_db)):
    """Alertas de todas las empresas: {emisor_id: [alertas]}."""
    return _con_cache("admin:diagnosticos",
                      lambda: {e.id: administracion.diagnostico(db, e) for e in db.scalars(select(Emisor).where(Emisor.solo_contabilidad.is_(False)))})


@router.get("/emisores/{emisor_id}/diagnostico")
def diagnostico(emisor_id: UUID, db: Session = Depends(get_db)):
    return administracion.diagnostico(db, _emisor(db, emisor_id))


@router.get("/emisores/{emisor_id}/compras")
def compras(emisor_id: UUID, db: Session = Depends(get_db)):
    """Historial de paquetes y mensualidades comprados, con el comprobante de cada venta."""
    return administracion.compras(db, _emisor(db, emisor_id))


@router.get("/ajustes")
def obtener_ajustes(db: Session = Depends(get_db)):
    a = administracion.ajustes(db)
    db.commit()
    return administracion.ajustes_a_dict(a, db)


@router.put("/ajustes")
def guardar_ajustes(payload: AjustesVentasRequest, request: Request,
                    principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if payload.emisor_ventas_id:
        vendedor = _emisor(db, UUID(payload.emisor_ventas_id))
        if not vendedor.activo:
            raise HTTPException(status_code=422, detail="La empresa que emite las ventas está inactiva")
    a = administracion.ajustes(db)
    for campo, valor in payload.model_dump().items():
        setattr(a, campo, valor)
    db.commit()
    auditoria.registrar(db, "ventas.ajustes", principal=principal, request=request,
                        detalle=f"emisor {payload.emisor_ventas_id or 'ninguno'}, CABYS {payload.codigo_cabys or '-'}")
    return administracion.ajustes_a_dict(a, db)


class EmitirComprobanteRequest(BaseModel):
    tipo: ComprobanteVenta | None = None
    medio_pago: MedioPagoVenta | None = None


@router.post("/ventas/{clase}/{venta_id}/comprobante")
def emitir_comprobante(clase: Literal["paquete", "suscripcion"], venta_id: UUID, payload: EmitirComprobanteRequest,
                       db: Session = Depends(get_db)):
    """Emite (o reintenta) el comprobante de una venta ya registrada. No duplica si ya existe."""
    venta = db.get(Paquete if clase == "paquete" else Suscripcion, str(venta_id))
    if venta is None:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    factura, error = administracion.emitir_comprobante(db, venta, db.get(Emisor, venta.emisor_id),
                                                       payload.tipo, payload.medio_pago)
    if error:
        raise HTTPException(status_code=422, detail=error)
    if factura is None:
        raise HTTPException(status_code=422, detail="Esta venta no lleva comprobante (precio 0 o venta a la propia empresa)")
    _encolar_envio(str(factura.id))
    return administracion.comprobante_a_dict(db, venta)


@router.get("/contabilidad")
def contabilidad(anio: int = Query(ge=2020, le=2100), mes: int = Query(ge=1, le=12), db: Session = Depends(get_db)):
    """Ventas del mes conciliadas con sus comprobantes (para el contador)."""
    return administracion.contabilidad(db, anio, mes)
