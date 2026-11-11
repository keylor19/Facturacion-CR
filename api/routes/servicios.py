"""
Mis servicios: precio de cada mensualidad, activarla o cancelarla, y las facturas mensuales.
Para el dueño de una empresa (servicios de la empresa) y para el contador (su cuenta).
No exige tener el sistema en línea activo: aquí es justamente donde se activa.
"""
from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import CobroMensual, Emisor, Usuario, get_db
from api.security import Principal, autenticar, require_admin
from api.services import administracion, auditoria, mensualidades, permisos
from api.services.fechas import ahora_cr

router = APIRouter(prefix="/api/v1/servicios", tags=["mis servicios"])
admin = APIRouter(prefix="/api/v1/admin/mensualidades", tags=["administración de paquetes"],
                  dependencies=[Depends(require_admin)])

Servicio = Literal["facturacion_web", "contabilidad", "contador"]


class PagoRequest(BaseModel):
    referencia: str = Field(min_length=3, max_length=100, description="Número del comprobante del SINPE o la transferencia")


class ConfirmarRequest(BaseModel):
    referencia: Optional[str] = Field(default=None, max_length=100)


class PeriodoRequest(BaseModel):
    anio: int = Field(ge=2024, le=2100)
    mes: int = Field(ge=1, le=12)


def _cliente(principal: Principal, db: Session) -> dict:
    """Quién paga: el contador (su cuenta) o la empresa (solo su dueño maneja los servicios)."""
    if principal.es_contador:
        return {"usuario_id": principal.usuario_id}
    if not principal.usuario_id or principal.es_admin or not principal.emisor_id:
        raise HTTPException(status_code=403, detail="Los servicios los maneja el dueño de la empresa o el contador")
    if not permisos.tiene(principal.rol, "configuracion"):
        raise HTTPException(status_code=403, detail="Solo el dueño de la empresa maneja los servicios")
    return {"emisor_id": principal.emisor_id}


@router.get("")
def mis_servicios(principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    cliente = _cliente(principal, db)
    a = administracion.ajustes(db)
    return {"servicios": mensualidades.servicios_de(db, **cliente), "dias_para_pagar": a.dias_para_pagar,
            "prueba_dias": a.prueba_dias, "instrucciones_pago": a.instrucciones_pago, "contacto_ventas": a.contacto_ventas,
            "precio_incluye_iva": a.precio_incluye_iva}


@router.post("/{servicio}/contratar", status_code=201)
def contratar(servicio: Servicio, request: Request, principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    """Activa el servicio de inmediato al precio actual; se cobra en la factura mensual."""
    cliente = _cliente(principal, db)
    try:
        c = mensualidades.contratar(
            db, servicio, emisor=db.get(Emisor, cliente["emisor_id"]) if "emisor_id" in cliente else None,
            usuario=db.get(Usuario, cliente["usuario_id"]) if "usuario_id" in cliente else None,
            quien=auditoria.nombre_actor(db, principal))
    except mensualidades.MensualidadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    auditoria.registrar(db, "servicio.contratar", principal=principal, request=request, emisor_id=cliente.get("emisor_id"),
                        detalle=f"{servicio}: {c.moneda} {c.precio} por mes")
    return mensualidades.a_dict(c)


@router.post("/{servicio}/cancelar")
def cancelar(servicio: Servicio, request: Request, principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    """Lo deja de usar hoy; el mes en curso se cobra proporcional a los días."""
    cliente = _cliente(principal, db)
    c = mensualidades.contrato(db, mensualidades.clave_cliente(**cliente), servicio)
    if c is None:
        raise HTTPException(status_code=404, detail="Ese servicio no está activo")
    mensualidades.cancelar(db, c)
    auditoria.registrar(db, "servicio.cancelar", principal=principal, request=request, emisor_id=cliente.get("emisor_id"),
                        detalle=servicio)
    return mensualidades.a_dict(c)


@router.get("/facturas")
def mis_facturas(principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    cliente = mensualidades.clave_cliente(**_cliente(principal, db))
    lista = db.scalars(select(CobroMensual).where(CobroMensual.cliente == cliente).order_by(CobroMensual.periodo.desc()).limit(36))
    return [mensualidades.a_dict_cobro(c) for c in lista]


@router.post("/facturas/{cobro_id}/pago")
def reportar_pago(cobro_id: UUID, payload: PagoRequest, request: Request, principal: Principal = Depends(autenticar),
                  db: Session = Depends(get_db)):
    """El cliente avisa que pagó; mientras se confirma, sus servicios no se suspenden."""
    cliente = mensualidades.clave_cliente(**_cliente(principal, db))
    c = db.get(CobroMensual, str(cobro_id))
    if c is None or c.cliente != cliente:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    try:
        mensualidades.reportar_pago(db, c, payload.referencia)
    except mensualidades.MensualidadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    auditoria.registrar(db, "mensualidad.pago_reportado", principal=principal, request=request, emisor_id=c.emisor_id,
                        detalle=f"{c.periodo:%m/%Y} ref {payload.referencia}")
    return mensualidades.a_dict_cobro(c)


# --- Administrador: supervisar y confirmar pagos ---------------------------------------------------

@admin.get("")
def listar(estado: Optional[Literal["PENDIENTE", "REPORTADO", "PAGADO", "ANULADO"]] = None, db: Session = Depends(get_db)):
    query = select(CobroMensual).order_by(CobroMensual.periodo.desc(), CobroMensual.created_at.desc()).limit(300)
    if estado:
        query = query.where(CobroMensual.estado == estado)
    return [mensualidades.a_dict_cobro(c, mensualidades.nombre_cliente(db, c)) for c in db.scalars(query)]


@admin.post("/{cobro_id}/confirmar")
def confirmar(cobro_id: UUID, payload: ConfirmarRequest, request: Request, principal: Principal = Depends(require_admin),
              db: Session = Depends(get_db)):
    c = db.get(CobroMensual, str(cobro_id))
    if c is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    try:
        mensualidades.confirmar_pago(db, c, auditoria.nombre_actor(db, principal), payload.referencia)
    except mensualidades.MensualidadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    auditoria.registrar(db, "mensualidad.pagada", principal=principal, request=request, emisor_id=c.emisor_id,
                        detalle=f"{c.periodo:%m/%Y} {c.moneda} {c.total}")
    return mensualidades.a_dict_cobro(c, mensualidades.nombre_cliente(db, c))


@admin.post("/generar")
def generar(payload: PeriodoRequest, request: Request, principal: Principal = Depends(require_admin),
            db: Session = Depends(get_db)):
    """Genera a mano las facturas de un mes (normalmente lo hace el sistema el día 1). No duplica."""
    periodo = date(payload.anio, payload.mes, 1)
    if periodo >= ahora_cr().date().replace(day=1):
        raise HTTPException(status_code=422, detail="Solo se facturan meses terminados")
    creados = mensualidades.generar(db, periodo)
    for c in creados:
        mensualidades.emitir_comprobante(db, c)
    auditoria.registrar(db, "mensualidad.generar", principal=principal, request=request,
                        detalle=f"{periodo:%m/%Y}: {len(creados)} factura(s)")
    return {"creadas": len(creados)}


@admin.get("/estimado")
def resumen(db: Session = Depends(get_db)):
    """Cuánto se va a facturar este mes si nada cambia (servicios activos a la fecha)."""
    hoy = ahora_cr().date()
    periodo = hoy.replace(day=1)
    clientes = {c.cliente for c in mensualidades.clientes_con_contratos(db, periodo)}
    total = sum((sum(float(x["monto"]) for x in mensualidades.lineas_del_mes(db, c, periodo)) for c in clientes), 0.0)
    return {"clientes": len(clientes), "estimado_mes": round(total, 2)}
