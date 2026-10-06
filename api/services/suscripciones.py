"""
Alquiler de servicios por período (mensualidades), aparte de los documentos.

Un servicio funciona si está habilitado en la empresa (casilla en su ficha) y,
cuando CONTROL_SUSCRIPCIONES está activo, si tiene una suscripción vigente
(se toleran DIAS_GRACIA_SUSCRIPCION días después del vencimiento).
"""
import calendar
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import Emisor, Suscripcion, utcnow
from api.services.fechas import zona_cr
from config.settings import get_settings

SERVICIOS = {"api": "Conexión por API", "facturacion_web": "Facturación en línea"}
# Columna de Emisor con la casilla de cada servicio
CASILLA = {"api": "acceso_api", "facturacion_web": "facturacion_web"}


def minuscula_inicial(texto: str) -> str:
    """Para usar el nombre a media oración: 'Conexión por API' -> 'conexión por API'."""
    return texto[:1].lower() + texto[1:]


def control_activo() -> bool:
    return get_settings().CONTROL_SUSCRIPCIONES


def sumar_meses(fecha: datetime, meses: int) -> datetime:
    """31/01 + 1 mes = 28/02 (o 29): se ajusta al último día del mes."""
    total = fecha.month - 1 + meses
    anio, mes = fecha.year + total // 12, total % 12 + 1
    return fecha.replace(year=anio, month=mes, day=min(fecha.day, calendar.monthrange(anio, mes)[1]))


def vence(db: Session, emisor_id: str, servicio: str) -> datetime | None:
    """Fin del período pagado más lejano (suscripciones no anuladas)."""
    return db.scalar(select(func.max(Suscripcion.hasta)).where(
        Suscripcion.emisor_id == emisor_id, Suscripcion.servicio == servicio, Suscripcion.anulada.is_(False)))


def estado(db: Session, emisor: Emisor, servicio: str) -> dict:
    ahora = utcnow()
    s = get_settings()
    habilitado = getattr(emisor, CASILLA[servicio]) is not False
    hasta = vence(db, emisor.id, servicio)
    if not control_activo():
        situacion = "ACTIVO" if habilitado else "DESHABILITADO"
    elif not habilitado:
        situacion = "DESHABILITADO"
    elif hasta is None:
        situacion = "SIN_CONTRATAR"
    elif hasta >= ahora:
        situacion = "POR_VENCER" if hasta <= ahora + timedelta(days=s.DIAS_ALERTA_SUSCRIPCION) else "ACTIVO"
    elif hasta + timedelta(days=s.DIAS_GRACIA_SUSCRIPCION) >= ahora:
        situacion = "EN_GRACIA"
    else:
        situacion = "VENCIDO"
    return {
        "servicio": servicio, "nombre": SERVICIOS[servicio], "habilitado": habilitado, "vence": hasta,
        "estado": situacion, "activo": situacion in ("ACTIVO", "POR_VENCER", "EN_GRACIA"),
    }


def estados(db: Session, emisor: Emisor) -> list[dict]:
    return [estado(db, emisor, s) for s in SERVICIOS]


def activo(db: Session, emisor: Emisor, servicio: str) -> bool:
    return estado(db, emisor, servicio)["activo"]


def motivo_inactivo(db: Session, emisor: Emisor, servicio: str) -> str:
    e = estado(db, emisor, servicio)
    nombre = minuscula_inicial(SERVICIOS[servicio])
    if e["estado"] == "VENCIDO":
        fecha = e["vence"].astimezone(zona_cr()).strftime("%d/%m/%Y")
        return f"El servicio de {nombre} venció el {fecha}; contacte a su proveedor para renovarlo"
    if e["estado"] == "SIN_CONTRATAR":
        return f"La empresa no tiene contratado el servicio de {nombre}; contacte a su proveedor"
    return f"La {nombre} no está activa para esta empresa; contacte a su proveedor"


def vender(db: Session, emisor: Emisor, servicio: str, meses: int, precio: Decimal, moneda: str,
           referencia_pago: str | None, notas: str | None, creado_por: str | None) -> Suscripcion:
    """Registra el pago de N meses. Si aún está vigente, el nuevo período empieza al terminar el actual."""
    ahora = utcnow()
    actual = vence(db, emisor.id, servicio)
    desde = actual if actual and actual > ahora else ahora
    sus = Suscripcion(
        emisor_id=emisor.id, servicio=servicio, desde=desde, hasta=sumar_meses(desde, meses), meses=meses,
        precio=precio, moneda=moneda, referencia_pago=referencia_pago, notas=notas, creado_por=creado_por,
    )
    db.add(sus)
    db.commit()
    return sus


def a_dict(s: Suscripcion) -> dict:
    ahora = utcnow()
    if s.anulada:
        situacion = "ANULADA"
    elif s.hasta < ahora:
        situacion = "VENCIDA"
    elif s.desde > ahora:
        situacion = "PROGRAMADA"
    else:
        situacion = "VIGENTE"
    return {
        "id": str(s.id), "servicio": s.servicio, "nombre": SERVICIOS.get(s.servicio, s.servicio),
        "desde": s.desde, "hasta": s.hasta, "meses": s.meses, "precio": str(s.precio), "moneda": s.moneda,
        "referencia_pago": s.referencia_pago, "notas": s.notas, "estado": situacion,
        "creado_por": s.creado_por, "fecha": s.created_at,
    }
