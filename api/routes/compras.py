"""Compras reportadas por el cliente (SINPE Móvil / transferencia) y su aprobación por el administrador."""
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Emisor, SolicitudCompra, get_db
from api.routes.saldo import _comprobante_venta
from api.security import Principal, emisor_actual, permiso, require_admin
from api.services import administracion, auditoria, compras, correo

router = APIRouter(prefix="/api/v1/compras", tags=["comprar documentos"])
admin = APIRouter(prefix="/api/v1/admin/solicitudes", tags=["administración de paquetes"],
                  dependencies=[Depends(require_admin)])


class AprobarRequest(BaseModel):
    comprobante: Optional[Literal["01", "04"]] = Field(default=None, description="Emitir factura (01) o tiquete (04) por la venta")
    medio_pago: Optional[str] = Field(default=None, pattern=r"^\d{2}$")


class RechazarRequest(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


def _avisar(destino: str | None, asunto: str, cuerpo: str) -> None:
    """Aviso por correo que no detiene la operación si el correo no está configurado o falla."""
    if not destino:
        return
    try:
        correo.enviar(correo.mensaje_simple(destino, asunto, cuerpo))
    except correo.CorreoError:
        pass


@router.get("/opciones")
def opciones(db: Session = Depends(get_db), emisor: Emisor = Depends(emisor_actual)):
    """Paquetes a la venta, precio del sistema web e instrucciones de pago."""
    return compras.opciones(db)


@router.get("")
def mis_solicitudes(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    lista = db.scalars(select(SolicitudCompra).where(SolicitudCompra.emisor_id == emisor.id)
                       .order_by(SolicitudCompra.created_at.desc()).limit(50))
    return [compras.a_dict(s) for s in lista]


@router.post("", status_code=201)
def solicitar(
    request: Request,
    plan_id: Optional[str] = Form(default=None),
    meses_web: int = Form(default=0, ge=0, le=12),
    medio_pago: Literal["04", "06"] = Form(default="06", description="04 transferencia, 06 SINPE Móvil"),
    referencia: str = Form(min_length=3, max_length=100, description="Número de comprobante del pago"),
    comprobante: Optional[UploadFile] = File(default=None),
    principal: Principal = Depends(permiso("configuracion")),
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """El cliente avisa que pagó; queda pendiente hasta que el administrador revise el pago."""
    contenido = comprobante.file.read(compras.MAX_BYTES_COMPROBANTE + 1) if comprobante else None
    try:
        if plan_id:
            UUID(plan_id)
        sol = compras.crear(db, emisor, plan_id=plan_id or None, meses_web=meses_web, medio_pago=medio_pago,
                            referencia=referencia, comprobante=contenido or None,
                            comprobante_tipo=comprobante.content_type if comprobante else None,
                            quien=auditoria.nombre_actor(db, principal))
    except ValueError:
        raise HTTPException(status_code=422, detail="Paquete inválido")
    except compras.CompraError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    auditoria.registrar(db, "compra.solicitud", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{sol.moneda} {sol.monto} ref {sol.referencia}")
    a = administracion.ajustes(db)
    _avisar(a.correo_avisos, f"Pago por revisar: {emisor.nombre}",
            f"{emisor.nombre} reportó un pago de {sol.moneda} {sol.monto:,.2f} (referencia {sol.referencia}) por "
            f"{sol.documentos} documentos y {sol.meses_web} mes(es) del sistema web.\n\n"
            "Revíselo en el panel: Ventas → Pagos por revisar.")
    return compras.a_dict(sol)


# --- Administrador ---------------------------------------------------------------------

def _solicitud(db: Session, sid: UUID) -> SolicitudCompra:
    s = db.get(SolicitudCompra, str(sid))
    if s is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return s


@admin.get("")
def listar(estado: Optional[Literal["PENDIENTE", "APROBADA", "RECHAZADA"]] = None, db: Session = Depends(get_db)):
    query = select(SolicitudCompra).order_by(SolicitudCompra.created_at.desc()).limit(200)
    if estado:
        query = query.where(SolicitudCompra.estado == estado)
    lista = db.scalars(query).all()
    nombres = {e.id: e for e in db.scalars(select(Emisor).where(Emisor.id.in_({s.emisor_id for s in lista})))} if lista else {}
    return [compras.a_dict(s, nombres.get(s.emisor_id)) for s in lista]


@admin.get("/{sid}/comprobante")
def ver_comprobante(sid: UUID, db: Session = Depends(get_db)):
    s = _solicitud(db, sid)
    if not s.comprobante:
        raise HTTPException(status_code=404, detail="La solicitud no trae comprobante")
    return Response(bytes(s.comprobante), media_type=s.comprobante_tipo or "application/octet-stream",
                    headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"})


@admin.post("/{sid}/aprobar")
def aprobar(sid: UUID, payload: AprobarRequest, request: Request, principal: Principal = Depends(require_admin),
            db: Session = Depends(get_db)):
    """Acredita lo pagado y, si se pide, emite la factura o tiquete por la venta."""
    s = _solicitud(db, sid)
    try:
        ventas = compras.aprobar(db, s, auditoria.nombre_actor(db, principal))
    except compras.CompraError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    emisor = db.get(Emisor, s.emisor_id)
    comprobantes = [_comprobante_venta(db, v, emisor, payload.comprobante, payload.medio_pago or s.medio_pago)
                    for v in ventas]
    auditoria.registrar(db, "compra.aprobada", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"{s.moneda} {s.monto} ref {s.referencia}")
    _avisar(emisor.correo, "Su compra fue aprobada",
            f"Recibimos su pago de {s.moneda} {s.monto:,.2f} (referencia {s.referencia}).\n\n"
            + (f"Se acreditaron {s.documentos} documentos.\n" if s.documentos else "")
            + (f"Se activaron {s.meses_web} mes(es) del sistema web.\n" if s.meses_web else "")
            + "\n¡Gracias por su compra!")
    return {**compras.a_dict(s, emisor), "comprobantes": comprobantes}


@admin.post("/{sid}/rechazar")
def rechazar(sid: UUID, payload: RechazarRequest, request: Request, principal: Principal = Depends(require_admin),
             db: Session = Depends(get_db)):
    s = _solicitud(db, sid)
    try:
        compras.rechazar(db, s, payload.motivo, auditoria.nombre_actor(db, principal))
    except compras.CompraError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    emisor = db.get(Emisor, s.emisor_id)
    auditoria.registrar(db, "compra.rechazada", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=payload.motivo)
    _avisar(emisor.correo, "No pudimos confirmar su pago",
            f"Revisamos el pago con referencia {s.referencia} por {s.moneda} {s.monto:,.2f} y no lo pudimos confirmar.\n\n"
            f"Motivo: {payload.motivo}\n\nSi cree que es un error, responda a este correo con el comprobante.")
    return compras.a_dict(s, emisor)
