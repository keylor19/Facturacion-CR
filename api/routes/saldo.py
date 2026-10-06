"""Saldo de documentos: consulta del cliente y administración de planes y paquetes."""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import Consumo, Emisor, Factura, Paquete, Plan, Suscripcion, get_db
from api.models.schemas import (
    AcreditarRequest, PlanActualizar, PlanCrear, PlanResponse, SuscripcionRequest, TIPOS_COMPROBANTE,
)
from api.security import Principal, emisor_actual, require_admin
from api.services import auditoria, saldo, suscripciones
from api.services.fechas import zona_cr
from api.services.reportes import rango_mes

router = APIRouter(prefix="/api/v1/saldo", tags=["saldo de documentos"])
admin = APIRouter(prefix="/api/v1", tags=["administración de paquetes"])

TIPOS_CONSUMO = {**TIPOS_COMPROBANTE, "05": "Mensaje receptor: aceptación",
                 "06": "Mensaje receptor: aceptación parcial", "07": "Mensaje receptor: rechazo"}


def _plan(p: Plan) -> PlanResponse:
    return PlanResponse(id=str(p.id), nombre=p.nombre, descripcion=p.descripcion, documentos=p.documentos,
                        precio=p.precio, moneda=p.moneda, dias_vigencia=p.dias_vigencia, activo=p.activo)


# --- Cliente: su propio saldo ------------------------------------------------

@router.get("")
def consultar_saldo(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Documentos disponibles, consumo del mes y paquetes adquiridos."""
    return saldo.resumen(db, emisor)


@router.get("/movimientos")
def movimientos(
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    emisor: Emisor = Depends(emisor_actual),
    db: Session = Depends(get_db),
):
    """Cada documento que consumió saldo (para conciliar contra lo facturado)."""
    query = select(Consumo).where(Consumo.emisor_id == emisor.id)
    if desde:
        query = query.where(Consumo.created_at >= datetime.combine(desde, time.min, zona_cr()))
    if hasta:
        query = query.where(Consumo.created_at <= datetime.combine(hasta, time.max, zona_cr()))
    consumos = db.scalars(query.order_by(Consumo.created_at.desc()).limit(limit).offset(offset)).all()
    return [
        {
            "fecha": c.created_at, "referencia": c.referencia, "tipo_documento": c.tipo_documento,
            "descripcion": TIPOS_CONSUMO.get(c.tipo_documento, c.tipo_documento),
            "factura_id": str(c.factura_id) if c.factura_id else None,
            "documento_recibido_id": str(c.documento_recibido_id) if c.documento_recibido_id else None,
            "paquete": c.paquete.nombre,
        }
        for c in consumos
    ]


# --- Administración: catálogo de planes -------------------------------------------

@admin.get("/planes", response_model=list[PlanResponse])
def listar_planes(activos: bool = False, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(Plan).order_by(Plan.documentos)
    if activos:
        query = query.where(Plan.activo.is_(True))
    return [_plan(p) for p in db.scalars(query)]


@admin.post("/planes", response_model=PlanResponse, status_code=201)
def crear_plan(payload: PlanCrear, request: Request, principal: Principal = Depends(require_admin),
               db: Session = Depends(get_db)):
    plan = Plan(**payload.model_dump())
    db.add(plan)
    db.commit()
    auditoria.registrar(db, "plan.crear", principal=principal, request=request,
                        detalle=f"{plan.nombre}: {plan.documentos} documentos, {plan.precio} {plan.moneda}")
    return _plan(plan)


@admin.patch("/planes/{plan_id}", response_model=PlanResponse)
def actualizar_plan(plan_id: UUID, payload: PlanActualizar, request: Request,
                    principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    plan = db.get(Plan, str(plan_id))
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    cambios = payload.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(plan, campo, valor)
    db.commit()
    auditoria.registrar(db, "plan.actualizar", principal=principal, request=request,
                        detalle=f"{plan.nombre}: " + ", ".join(f"{c}={v}" for c, v in sorted(cambios.items())))
    return _plan(plan)


# --- Administración: paquetes de cada empresa ----------------------------------------

def _emisor(db: Session, emisor_id: UUID) -> Emisor:
    emisor = db.get(Emisor, str(emisor_id))
    if emisor is None:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    return emisor


@admin.get("/emisores/{emisor_id}/paquetes")
def paquetes_emisor(emisor_id: UUID, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return saldo.resumen(db, _emisor(db, emisor_id))


@admin.post("/emisores/{emisor_id}/paquetes", status_code=201)
def acreditar_paquete(emisor_id: UUID, payload: AcreditarRequest, request: Request,
                      principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Registra la venta de un paquete (pago manual: SINPE, transferencia) o una cortesía."""
    emisor = _emisor(db, emisor_id)
    plan = None
    if payload.plan_id:
        try:
            plan = db.get(Plan, str(UUID(payload.plan_id)))
        except ValueError:
            plan = None
        if plan is None:
            raise HTTPException(status_code=404, detail="Plan no encontrado")
    quien = f"usuario:{principal.usuario_id}" if principal.usuario_id else f"llave:{principal.api_key_id or 'admin'}"
    try:
        paquete = saldo.acreditar(
            db, emisor, plan=plan, documentos=payload.documentos, precio=payload.precio, moneda=payload.moneda,
            dias_vigencia=payload.dias_vigencia, nombre=payload.nombre, referencia_pago=payload.referencia_pago,
            notas=payload.notas, creado_por=quien,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    auditoria.registrar(db, "paquete.vender", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{payload.documentos or (plan.documentos if plan else '')} documentos"
                        + (f", pago {payload.referencia_pago}" if payload.referencia_pago else ""))
    return {"paquete": saldo.paquete_a_dict(paquete), "disponible": saldo.disponible(db, emisor.id)}


@admin.post("/paquetes/{paquete_id}/anular")
def anular_paquete(paquete_id: UUID, request: Request, principal: Principal = Depends(require_admin),
                   db: Session = Depends(get_db)):
    """Anula el saldo restante de un paquete (p. ej. pago revertido). Lo ya consumido se conserva."""
    paquete = db.get(Paquete, str(paquete_id))
    if paquete is None:
        raise HTTPException(status_code=404, detail="Paquete no encontrado")
    paquete.anulado = True
    db.commit()
    auditoria.registrar(db, "paquete.anular", principal=principal, request=request, emisor_id=paquete.emisor_id,
                        detalle=f"paquete {paquete.id}")
    return saldo.paquete_a_dict(paquete)


# --- Administración: alquiler de servicios (mensualidades) ----------------------------

@admin.get("/emisores/{emisor_id}/suscripciones")
def suscripciones_emisor(emisor_id: UUID, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    emisor = _emisor(db, emisor_id)
    historial = db.scalars(select(Suscripcion).where(Suscripcion.emisor_id == emisor.id)
                           .order_by(Suscripcion.created_at.desc())).all()
    return {
        "control_activo": suscripciones.control_activo(),
        "servicios": suscripciones.estados(db, emisor),
        "historial": [suscripciones.a_dict(s) for s in historial],
    }


@admin.post("/emisores/{emisor_id}/suscripciones", status_code=201)
def vender_suscripcion(emisor_id: UUID, payload: SuscripcionRequest, request: Request,
                       principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Registra el pago del alquiler de un servicio (SINPE, transferencia) por N meses."""
    emisor = _emisor(db, emisor_id)
    sus = suscripciones.vender(
        db, emisor, payload.servicio, payload.meses, payload.precio, payload.moneda,
        payload.referencia_pago, payload.notas, auditoria.nombre_actor(db, principal),
    )
    auditoria.registrar(db, "suscripcion.vender", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{suscripciones.SERVICIOS[sus.servicio]}: {sus.meses} mes(es), {sus.precio} {sus.moneda}"
                        + (f", pago {sus.referencia_pago}" if sus.referencia_pago else ""))
    return {"suscripcion": suscripciones.a_dict(sus), "servicio": suscripciones.estado(db, emisor, sus.servicio)}


@admin.post("/suscripciones/{suscripcion_id}/anular")
def anular_suscripcion(suscripcion_id: UUID, request: Request, principal: Principal = Depends(require_admin),
                       db: Session = Depends(get_db)):
    """Anula un cobro (p. ej. pago revertido): el período deja de contar."""
    sus = db.get(Suscripcion, str(suscripcion_id))
    if sus is None:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    sus.anulada = True
    db.commit()
    auditoria.registrar(db, "suscripcion.anular", principal=principal, request=request, emisor_id=sus.emisor_id,
                        detalle=f"{suscripciones.SERVICIOS.get(sus.servicio, sus.servicio)} {sus.id}")
    return suscripciones.a_dict(sus)


@admin.get("/admin/ventas")
def ventas(anio: int = Query(ge=2020, le=2100), mes: int = Query(ge=1, le=12),
           _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Ingresos del mes (paquetes de documentos y alquiler de servicios) y consumo por empresa."""
    desde, hasta = rango_mes(anio, mes)
    vendidos = db.execute(
        select(Paquete, Emisor.nombre).join(Emisor, Emisor.id == Paquete.emisor_id)
        .where(Paquete.created_at >= desde, Paquete.created_at < hasta, Paquete.anulado.is_(False))
        .order_by(Paquete.created_at)
    ).all()
    servicios = db.execute(
        select(Suscripcion, Emisor.nombre).join(Emisor, Emisor.id == Suscripcion.emisor_id)
        .where(Suscripcion.created_at >= desde, Suscripcion.created_at < hasta, Suscripcion.anulada.is_(False))
        .order_by(Suscripcion.created_at)
    ).all()

    def sumar(montos) -> dict[str, Decimal]:
        total: dict[str, Decimal] = {}
        for moneda, precio in montos:
            total[moneda] = total.get(moneda, Decimal("0")) + precio
        return total

    ingresos_documentos = sumar((p.moneda, p.precio) for p, _ in vendidos)
    ingresos_servicios = sumar((s.moneda, s.precio) for s, _ in servicios)
    ingresos = sumar([*ingresos_documentos.items(), *ingresos_servicios.items()])

    consumo = db.execute(
        select(Emisor.id, Emisor.nombre, func.count(Consumo.id))
        .join(Consumo, Consumo.emisor_id == Emisor.id)
        .where(Consumo.created_at >= desde, Consumo.created_at < hasta)
        .group_by(Emisor.id, Emisor.nombre).order_by(func.count(Consumo.id).desc())
    ).all()
    emitidos_mes = db.scalar(select(func.count()).select_from(Factura).where(
        Factura.created_at >= desde, Factura.created_at < hasta)) or 0
    return {
        "periodo": f"{anio:04d}-{mes:02d}",
        "ingresos": {m: str(v) for m, v in ingresos.items()},
        "ingresos_documentos": {m: str(v) for m, v in ingresos_documentos.items()},
        "ingresos_servicios": {m: str(v) for m, v in ingresos_servicios.items()},
        "paquetes_vendidos": [{**saldo.paquete_a_dict(p), "empresa": nombre} for p, nombre in vendidos],
        "servicios_vendidos": [{**suscripciones.a_dict(s), "empresa": nombre} for s, nombre in servicios],
        "consumo_por_empresa": [{"emisor_id": str(i), "empresa": n, "documentos": c} for i, n, c in consumo],
        "documentos_consumidos": sum(c for _, _, c in consumo),
        "comprobantes_emitidos": emitidos_mes,
    }
