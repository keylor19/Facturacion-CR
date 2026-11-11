"""
Facturación recurrente: comprobantes que se emiten solos (alquiler, mensualidad,
servicio profesional). Una tarea diaria emite los que tocan y calcula la próxima fecha.

Cada emisión lleva referencia_externa REC-<id>-<fecha>: si la tarea corre dos veces
el mismo día, el API devuelve el comprobante ya emitido en vez de duplicarlo.
"""
import calendar
import logging
from datetime import date, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Emisor, FacturaRecurrente
from api.models.schemas import FacturaRequest
from api.services import emision
from api.services.fechas import ahora_cr

logger = logging.getLogger(__name__)

FRECUENCIAS = {"semanal": "Cada semana", "quincenal": "Cada 15 días", "mensual": "Cada mes", "anual": "Cada año"}


def _sumar_meses(d: date, meses: int) -> date:
    mes = d.month - 1 + meses
    anio, mes = d.year + mes // 12, mes % 12 + 1
    return date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


def siguiente(fecha: date, frecuencia: str) -> date:
    if frecuencia == "semanal":
        return fecha + timedelta(days=7)
    if frecuencia == "quincenal":
        return fecha + timedelta(days=15)
    if frecuencia == "anual":
        return _sumar_meses(fecha, 12)
    return _sumar_meses(fecha, 1)


def validar_datos(datos: dict) -> FacturaRequest:
    """El cuerpo guardado debe ser un comprobante válido (sin referencia: la pone cada emisión)."""
    datos = {k: v for k, v in datos.items() if k not in ("referencia_externa", "fecha_emision")}
    if datos.get("tipo_documento", "01") not in ("01", "04", "09"):
        raise ValueError("Solo facturas, tiquetes y facturas de exportación pueden ser recurrentes")
    return FacturaRequest(**datos)


def referencia(r: FacturaRecurrente, fecha: date) -> str:
    return f"REC-{str(r.id)[:8]}-{fecha:%Y%m%d}"


def emitir_una(db: Session, r: FacturaRecurrente, fecha: date | None = None):
    """Emite la recurrente para su fecha (o la indicada). Devuelve (factura, creada) o lanza EmisionError."""
    fecha = fecha or r.proxima
    emisor = db.get(Emisor, r.emisor_id)
    try:
        datos = validar_datos(r.datos)
    except (ValidationError, ValueError) as exc:
        raise emision.EmisionError(422, f"La plantilla ya no es válida: {exc}")
    datos.referencia_externa = referencia(r, fecha)
    return emision.emitir(db, emisor, datos)


def emitir_pendientes(db: Session, hoy: date | None = None) -> list[str]:
    """Emite todas las recurrentes que vencen hoy o antes. Devuelve los id de comprobantes nuevos."""
    hoy = hoy or ahora_cr().date()
    nuevos = []
    pendientes = db.scalars(select(FacturaRecurrente).where(
        FacturaRecurrente.activa.is_(True), FacturaRecurrente.proxima <= hoy)).all()
    for r in pendientes:
        # Se pone al día una fecha por vuelta; si se atrasó varios períodos, emite uno por cada uno
        while r.activa and r.proxima <= hoy:
            if r.hasta and r.proxima > r.hasta:
                r.activa = False
                break
            try:
                factura, creada = emitir_una(db, r)
            except emision.EmisionError as exc:
                db.rollback()
                r = db.get(FacturaRecurrente, r.id)
                r.ultimo_error = f"{r.proxima:%d/%m/%Y}: {exc.detail}"
                db.commit()
                logger.warning("Recurrente %s no se emitió: %s", r.id, exc.detail)
                break
            if creada:
                nuevos.append(str(factura.id))
                r.emitidas += 1
            r.ultima_factura_id = factura.id
            r.ultimo_error = None
            r.proxima = siguiente(r.proxima, r.frecuencia)
            if r.hasta and r.proxima > r.hasta:
                r.activa = False
            db.commit()
    return nuevos
