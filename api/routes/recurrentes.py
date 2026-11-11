"""Facturación recurrente: plantillas de comprobantes que se emiten solos cada cierto tiempo."""
from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Emisor, FacturaRecurrente, get_db
from api.routes.facturas import _encolar_envio
from api.security import Principal, emisor_actual, permiso
from api.services import auditoria, emision, recurrentes
from api.services.fechas import ahora_cr

router = APIRouter(prefix="/api/v1/recurrentes", tags=["facturación recurrente"],
                   dependencies=[Depends(permiso("emitir"))])

Frecuencia = Literal["semanal", "quincenal", "mensual", "anual"]


class RecurrenteRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=120, description="Para reconocerla, p. ej. «Alquiler local 3»")
    datos: dict = Field(description="El mismo cuerpo de POST /facturas (sin referencia_externa)")
    frecuencia: Frecuencia = "mensual"
    proxima: date = Field(description="Primera fecha de emisión")
    hasta: Optional[date] = Field(default=None, description="Última fecha (vacío = sin fin)")
    activa: bool = True


def _dict(r: FacturaRecurrente) -> dict:
    d = r.datos or {}
    receptor = d.get("receptor") or {}
    return {
        "id": str(r.id), "nombre": r.nombre, "frecuencia": r.frecuencia, "proxima": r.proxima.isoformat(),
        "hasta": r.hasta.isoformat() if r.hasta else None, "activa": r.activa, "emitidas": r.emitidas,
        "ultima_factura_id": str(r.ultima_factura_id) if r.ultima_factura_id else None,
        "ultimo_error": r.ultimo_error, "creada_por": r.creada_por, "datos": d,
        "cliente": receptor.get("nombre"), "tipo_documento": d.get("tipo_documento", "01"),
        "moneda": d.get("moneda", "CRC"),
    }


def _validar(payload: RecurrenteRequest) -> None:
    try:
        recurrentes.validar_datos(payload.datos)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=[{**e, "loc": ["datos", *e["loc"]]} for e in exc.errors(
            include_url=False, include_context=False)])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if payload.hasta and payload.hasta < payload.proxima:
        raise HTTPException(status_code=422, detail="La fecha final es anterior a la primera emisión")
    if payload.frecuencia in ("mensual", "anual") and payload.proxima.day > 28:
        raise HTTPException(status_code=422, detail="Para emitir cada mes o cada año use un día del 1 al 28 "
                                                    "(todos los meses lo tienen)")


def _buscar(db: Session, emisor: Emisor, rid: UUID) -> FacturaRecurrente:
    r = db.get(FacturaRecurrente, str(rid))
    if not r or r.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Factura recurrente no encontrada")
    return r


@router.get("")
def listar(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    return [_dict(r) for r in db.scalars(select(FacturaRecurrente).where(FacturaRecurrente.emisor_id == emisor.id)
                                          .order_by(FacturaRecurrente.activa.desc(), FacturaRecurrente.proxima))]


@router.post("", status_code=201)
def crear(payload: RecurrenteRequest, request: Request, principal: Principal = Depends(permiso("emitir")),
          emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    _validar(payload)
    if payload.proxima < ahora_cr().date():
        raise HTTPException(status_code=422, detail="La primera fecha de emisión no puede ser pasada")
    r = FacturaRecurrente(emisor_id=emisor.id, nombre=payload.nombre, datos=payload.datos, frecuencia=payload.frecuencia,
                          proxima=payload.proxima, hasta=payload.hasta, activa=payload.activa,
                          creada_por=auditoria.nombre_actor(db, principal))
    db.add(r)
    db.commit()
    auditoria.registrar(db, "recurrente.crear", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{r.nombre} ({r.frecuencia}, desde {r.proxima:%d/%m/%Y})")
    return _dict(r)


@router.get("/{rid}")
def obtener(rid: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    return _dict(_buscar(db, emisor, rid))


@router.put("/{rid}")
def actualizar(rid: UUID, payload: RecurrenteRequest, request: Request, principal: Principal = Depends(permiso("emitir")),
               emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    r = _buscar(db, emisor, rid)
    _validar(payload)
    for campo in ("nombre", "datos", "frecuencia", "proxima", "hasta", "activa"):
        setattr(r, campo, getattr(payload, campo))
    if payload.activa:
        r.ultimo_error = None
    db.commit()
    auditoria.registrar(db, "recurrente.actualizar", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{r.nombre} (activa={r.activa})")
    return _dict(r)


@router.delete("/{rid}", status_code=204)
def eliminar(rid: UUID, request: Request, principal: Principal = Depends(permiso("emitir")),
             emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Borra la plantilla. Las facturas ya emitidas no se tocan."""
    r = _buscar(db, emisor, rid)
    nombre = r.nombre
    db.delete(r)
    db.commit()
    auditoria.registrar(db, "recurrente.eliminar", principal=principal, request=request, emisor_id=emisor.id, detalle=nombre)


@router.post("/{rid}/emitir-ahora", status_code=202)
def emitir_ahora(rid: UUID, response: Response, request: Request, principal: Principal = Depends(permiso("emitir")),
                 emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Emite hoy el comprobante de la plantilla (fuera de calendario). No cambia la próxima fecha."""
    r = _buscar(db, emisor, rid)
    try:
        factura, creada = recurrentes.emitir_una(db, r, ahora_cr().date())
    except emision.EmisionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    if creada:
        r.emitidas += 1
        r.ultima_factura_id = factura.id
        db.commit()
        _encolar_envio(str(factura.id))
        auditoria.registrar(db, "recurrente.emitir_ahora", principal=principal, request=request, emisor_id=emisor.id,
                            detalle=f"{r.nombre}: {factura.numero_consecutivo}")
    else:
        response.status_code = 200
    return {"factura_id": str(factura.id), "clave": factura.clave, "estado": factura.estado.value, "nueva": creada}
