"""
Compras que el cliente reporta desde el panel (pagó por SINPE Móvil o transferencia).
El precio lo calcula el sistema con los planes activos y el precio mensual del sistema
web; el cliente no puede escoger montos. El administrador aprueba o rechaza.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Emisor, Plan, SolicitudCompra, utcnow
from api.services import administracion, saldo, suscripciones

MAX_BYTES_COMPROBANTE = 3_000_000
TIPOS_COMPROBANTE = {"image/png", "image/jpeg", "image/webp", "application/pdf"}
MESES_WEB = (1, 3, 6, 12)


class CompraError(Exception):
    def __init__(self, detalle: str, status_code: int = 422):
        super().__init__(detalle)
        self.detalle = detalle
        self.status_code = status_code


def opciones(db: Session) -> dict:
    """Lo que el cliente puede comprar solo: planes activos con precio y el sistema web por mes."""
    a = administracion.ajustes(db)
    planes = db.scalars(select(Plan).where(Plan.activo.is_(True), Plan.precio > 0).order_by(Plan.documentos)).all()
    return {
        "planes": [{"id": str(p.id), "nombre": p.nombre, "documentos": p.documentos, "precio": str(p.precio),
                    "moneda": p.moneda, "dias_vigencia": p.dias_vigencia} for p in planes],
        "precio_web_mensual": str(a.precio_web_mensual) if a.precio_web_mensual else None,
        "moneda_web": a.moneda_web, "meses_web": list(MESES_WEB),
        "instrucciones_pago": a.instrucciones_pago, "contacto_ventas": a.contacto_ventas,
        "precio_incluye_iva": a.precio_incluye_iva,
    }


def cotizar(db: Session, plan_id: str | None, meses_web: int) -> tuple[Plan | None, Decimal, str]:
    a = administracion.ajustes(db)
    plan = None
    total, moneda = Decimal("0"), None
    if plan_id:
        plan = db.get(Plan, plan_id)
        if plan is None or not plan.activo or not plan.precio or plan.precio <= 0:
            raise CompraError("Ese paquete no está a la venta")
        total, moneda = Decimal(plan.precio), plan.moneda
    if meses_web:
        if meses_web not in MESES_WEB:
            raise CompraError(f"Elija {', '.join(map(str, MESES_WEB))} meses del sistema web")
        if not a.precio_web_mensual:
            raise CompraError("El sistema web no se vende en línea; escriba a ventas")
        if moneda and moneda != a.moneda_web:
            raise CompraError("El paquete y el sistema web tienen monedas distintas: cómprelos por separado")
        total += Decimal(a.precio_web_mensual) * meses_web
        moneda = a.moneda_web
    if total <= 0:
        raise CompraError("Elija un paquete de documentos o meses del sistema web")
    return plan, total.quantize(Decimal("0.01")), moneda


def crear(db: Session, emisor: Emisor, *, plan_id: str | None, meses_web: int, medio_pago: str, referencia: str,
          comprobante: bytes | None, comprobante_tipo: str | None, quien: str) -> SolicitudCompra:
    plan, monto, moneda = cotizar(db, plan_id, meses_web)
    if comprobante is not None:
        if len(comprobante) > MAX_BYTES_COMPROBANTE:
            raise CompraError("El comprobante pesa más de 3 MB", 413)
        if comprobante_tipo not in TIPOS_COMPROBANTE:
            raise CompraError("El comprobante debe ser una foto (PNG, JPEG) o un PDF")
    sol = SolicitudCompra(
        emisor_id=emisor.id, plan_id=plan.id if plan else None, documentos=plan.documentos if plan else 0,
        meses_web=meses_web, monto=monto, moneda=moneda, medio_pago=medio_pago, referencia=referencia.strip()[:100],
        comprobante=comprobante, comprobante_tipo=comprobante_tipo if comprobante else None, solicitada_por=quien,
    )
    db.add(sol)
    db.commit()
    return sol


def a_dict(s: SolicitudCompra, emisor: Emisor | None = None) -> dict:
    return {
        "id": str(s.id), "emisor_id": str(s.emisor_id), "empresa": emisor.nombre if emisor else None,
        "documentos": s.documentos, "meses_web": s.meses_web, "monto": str(s.monto), "moneda": s.moneda,
        "medio_pago": s.medio_pago, "referencia": s.referencia, "tiene_comprobante": s.comprobante is not None,
        "estado": s.estado, "motivo": s.motivo, "solicitada_por": s.solicitada_por,
        "resuelta_por": s.resuelta_por, "resuelta_en": s.resuelta_en, "created_at": s.created_at,
    }


def aprobar(db: Session, s: SolicitudCompra, quien: str) -> list:
    """Acredita lo pagado. Devuelve las ventas creadas (paquete y/o suscripción) para emitir su comprobante."""
    if s.estado != "PENDIENTE":
        raise CompraError("La solicitud ya fue resuelta", 409)
    emisor = db.get(Emisor, s.emisor_id)
    ventas = []
    referencia = f"{s.referencia} (solicitud en línea)"[:100]
    if s.plan_id:
        plan = db.get(Plan, s.plan_id)
        ventas.append(saldo.acreditar(db, emisor, plan=plan, documentos=s.documentos, referencia_pago=referencia,
                                      creado_por=quien))
    if s.meses_web:
        precio = (s.monto - (ventas[0].precio if ventas else 0)).quantize(Decimal("0.01"))
        ventas.append(suscripciones.vender(db, emisor, "facturacion_web", s.meses_web, precio, s.moneda,
                                           referencia, "Compra en línea", quien))
        if not emisor.facturacion_web:
            emisor.facturacion_web = True
    s.estado = "APROBADA"
    s.resuelta_por = quien
    s.resuelta_en = utcnow()
    db.commit()
    return ventas


def rechazar(db: Session, s: SolicitudCompra, motivo: str, quien: str) -> None:
    if s.estado != "PENDIENTE":
        raise CompraError("La solicitud ya fue resuelta", 409)
    s.estado = "RECHAZADA"
    s.motivo = motivo[:300]
    s.resuelta_por = quien
    s.resuelta_en = utcnow()
    db.commit()
