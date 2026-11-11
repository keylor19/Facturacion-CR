"""Cuentas por cobrar: cartera por antigüedad, estado de cuenta, abonos y recordatorios."""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Abono, Emisor, EstadoFactura, Factura, get_db
from api.security import Principal, emisor_actual, permiso
from api.services import auditoria, cobros
from api.services.fechas import ahora_cr

router = APIRouter(prefix="/api/v1/cobros", tags=["cuentas por cobrar"])


class AbonoRequest(BaseModel):
    monto: Decimal = Field(gt=0, description="Monto recibido, en la moneda de la factura")
    fecha: Optional[date] = Field(default=None, description="Por defecto, hoy")
    medio_pago: Literal["01", "02", "03", "04", "05", "06", "07", "99"] = "04"
    referencia: Optional[str] = Field(default=None, max_length=100, description="Número de transferencia, SINPE o cheque")
    nota: Optional[str] = Field(default=None, max_length=250)


class AjustesCobroRequest(BaseModel):
    recordar_cobros: bool = Field(description="Enviar recordatorios por correo de las facturas vencidas")


def _abono_dict(a: Abono) -> dict:
    return {"id": str(a.id), "factura_id": str(a.factura_id), "fecha": a.fecha.isoformat(), "monto": str(a.monto),
            "medio_pago": a.medio_pago, "referencia": a.referencia, "nota": a.nota,
            "registrado_por": a.registrado_por, "anulado": a.anulado}


def _factura(db: Session, emisor: Emisor, factura_id: UUID) -> Factura:
    f = db.get(Factura, str(factura_id))
    if not f or f.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Comprobante no encontrado")
    return f


@router.get("/cartera", dependencies=[Depends(permiso("cobrar"))])
def cartera(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Facturas a crédito con saldo, totales por antigüedad y saldo por cliente."""
    return {**cobros.cartera(db, emisor.id), "recordar_cobros": emisor.recordar_cobros,
            "dias_recordatorio": list(cobros.DIAS_RECORDATORIO)}


@router.get("/estado-cuenta/{identificacion}", dependencies=[Depends(permiso("cobrar"))])
def estado_cuenta(identificacion: str, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Facturas a crédito de un cliente con sus pagos y el saldo total."""
    datos = cobros.estado_de_cuenta(db, emisor.id, identificacion.strip())
    if not datos["facturas"]:
        raise HTTPException(status_code=404, detail="Ese cliente no tiene facturas a crédito")
    return {**datos, "empresa": emisor.nombre_comercial or emisor.nombre, "fecha": ahora_cr().date().isoformat()}


@router.get("/facturas/{factura_id}", dependencies=[Depends(permiso("cobrar"))])
def cobro_factura(factura_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Saldo y abonos de una factura a crédito."""
    f = _factura(db, emisor, factura_id)
    abonos = db.scalars(select(Abono).where(Abono.factura_id == f.id).order_by(Abono.fecha, Abono.created_at))
    return {**cobros.detalle(db, [f])[0], "abonos": [_abono_dict(a) for a in abonos]}


@router.post("/facturas/{factura_id}/abonos", status_code=201)
def registrar_abono(factura_id: UUID, payload: AbonoRequest, request: Request,
                    principal: Principal = Depends(permiso("cobrar")),
                    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Registra un pago de una factura a crédito comercial (condición 02)."""
    f = _factura(db, emisor, factura_id)
    if f.condicion_venta in cobros.CON_RECIBO:
        raise HTTPException(status_code=409, detail="Esta factura se cobra con recibo electrónico de pago "
                                                    "(POST /facturas/{id}/recibo-pago)")
    if f.condicion_venta != "02" or f.tipo_documento not in ("01", "09"):
        raise HTTPException(status_code=409, detail="Solo las facturas a crédito llevan abonos")
    if f.estado == EstadoFactura.RECHAZADO:
        raise HTTPException(status_code=409, detail="La factura fue rechazada por Hacienda: no tiene saldo que cobrar")
    hoy = ahora_cr().date()
    fecha = payload.fecha or hoy
    if fecha > hoy:
        raise HTTPException(status_code=422, detail="La fecha del pago no puede ser futura")
    saldo = cobros.saldo_factura(db, f)
    if payload.monto > saldo:
        raise HTTPException(status_code=422, detail=f"El pago ({payload.monto:,.2f}) es mayor que el saldo ({saldo:,.2f})")
    a = Abono(emisor_id=emisor.id, factura_id=f.id, fecha=fecha, monto=payload.monto, medio_pago=payload.medio_pago,
              referencia=payload.referencia, nota=payload.nota, registrado_por=auditoria.nombre_actor(db, principal))
    db.add(a)
    db.commit()
    auditoria.registrar(db, "cobro.abono", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{f.numero_consecutivo}: {f.moneda} {payload.monto:,.2f}")
    return {**_abono_dict(a), "saldo": str(cobros.saldo_factura(db, f))}


@router.post("/abonos/{abono_id}/anular")
def anular_abono(abono_id: UUID, request: Request, principal: Principal = Depends(permiso("anular")),
                 emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Deja sin efecto un abono registrado por error."""
    a = db.get(Abono, str(abono_id))
    if not a or a.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Abono no encontrado")
    if a.anulado:
        raise HTTPException(status_code=409, detail="El abono ya estaba anulado")
    a.anulado = True
    db.commit()
    auditoria.registrar(db, "cobro.abono_anulado", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{a.monto:,.2f} del {a.fecha:%d/%m/%Y}")
    return _abono_dict(a)


@router.put("/ajustes")
def ajustes(payload: AjustesCobroRequest, request: Request, principal: Principal = Depends(permiso("configuracion")),
            emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Activa o desactiva los recordatorios automáticos de cobro."""
    emisor.recordar_cobros = payload.recordar_cobros
    db.commit()
    auditoria.registrar(db, "cobro.ajustes", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"recordatorios={'sí' if payload.recordar_cobros else 'no'}")
    return {"recordar_cobros": emisor.recordar_cobros}
