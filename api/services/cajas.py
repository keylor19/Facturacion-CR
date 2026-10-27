"""
Punto de venta: turnos de caja, movimientos de efectivo y arqueo.

El arqueo reparte el total de cada venta entre sus medios de pago: los que
traen monto suman ese monto (convertido a colones) y el resto del total va al
primer medio sin monto. El efectivo esperado es el fondo + ventas en efectivo
+ entradas - salidas.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models.database import Caja, Emisor, EstadoFactura, Factura, MovimientoCaja, utcnow

EFECTIVO = "01"
CERO = Decimal("0")
DOS = Decimal("0.01")


class CajaError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def abrir(db: Session, emisor: Emisor, sucursal: int, terminal: int, monto: Decimal, notas: str | None,
          quien: str) -> Caja:
    caja = Caja(emisor_id=emisor.id, sucursal=sucursal, terminal=terminal, monto_apertura=monto,
                notas=notas, abierta_por=quien, estado="ABIERTA")
    db.add(caja)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CajaError(409, f"Ya hay una caja abierta en la sucursal {sucursal}, terminal {terminal}")
    return caja


def ventas(db: Session, caja: Caja) -> list[Factura]:
    return list(db.scalars(select(Factura).where(Factura.caja_id == caja.id).order_by(Factura.fecha_emision)))


def _por_medio(f: Factura) -> dict[str, Decimal]:
    """Monto de una venta por medio de pago, en colones."""
    tc = Decimal(f.tipo_cambio or 1) if f.moneda != "CRC" else Decimal(1)
    total = Decimal(f.monto_total) * tc
    medios = (f.json_original or {}).get("medios_pago") or [{"tipo": EFECTIVO}]
    reparto: dict[str, Decimal] = {}
    asignado = CERO
    for m in medios:
        if m.get("monto") not in (None, ""):
            monto = Decimal(str(m["monto"])) * tc
            reparto[m["tipo"]] = reparto.get(m["tipo"], CERO) + monto
            asignado += monto
    resto = total - asignado
    if resto > 0:
        sin_monto = next((m["tipo"] for m in medios if m.get("monto") in (None, "")), medios[0]["tipo"])
        reparto[sin_monto] = reparto.get(sin_monto, CERO) + resto
    return reparto


def resumen(db: Session, caja: Caja) -> dict:
    lista = ventas(db, caja)
    por_medio: dict[str, Decimal] = {}
    total = impuesto = CERO
    rechazados = []
    for f in lista:
        tc = Decimal(f.tipo_cambio or 1) if f.moneda != "CRC" else Decimal(1)
        total += Decimal(f.monto_total) * tc
        impuesto += Decimal(f.monto_impuesto) * tc
        for medio, monto in _por_medio(f).items():
            por_medio[medio] = por_medio.get(medio, CERO) + monto
        if f.estado == EstadoFactura.RECHAZADO:
            rechazados.append(f.numero_consecutivo)
    entradas = sum((m.monto for m in caja.movimientos if m.tipo == "entrada"), CERO)
    salidas = sum((m.monto for m in caja.movimientos if m.tipo == "salida"), CERO)
    esperado = Decimal(caja.monto_apertura) + por_medio.get(EFECTIVO, CERO) + entradas - salidas
    return {
        "documentos": len(lista),
        "total_ventas": str(total.quantize(DOS)),
        "impuesto": str(impuesto.quantize(DOS)),
        "por_medio": {k: str(v.quantize(DOS)) for k, v in sorted(por_medio.items())},
        "monto_apertura": str(Decimal(caja.monto_apertura).quantize(DOS)),
        "entradas": str(entradas.quantize(DOS)),
        "salidas": str(salidas.quantize(DOS)),
        "efectivo_esperado": str(esperado.quantize(DOS)),
        "rechazados": rechazados,
    }


def movimiento(db: Session, caja: Caja, tipo: str, monto: Decimal, motivo: str, quien: str) -> MovimientoCaja:
    _abierta(caja)
    m = MovimientoCaja(caja_id=caja.id, tipo=tipo, monto=monto, motivo=motivo, usuario=quien)
    caja.movimientos.append(m)
    db.commit()
    return m


def cerrar(db: Session, caja: Caja, contado: Decimal, notas: str | None, quien: str) -> Caja:
    _abierta(caja)
    datos = resumen(db, caja)
    datos["monto_contado"] = str(Decimal(contado).quantize(DOS))
    datos["diferencia"] = str((Decimal(contado) - Decimal(datos["efectivo_esperado"])).quantize(DOS))
    caja.resumen = datos
    caja.monto_contado = contado
    caja.cerrada_por = quien
    caja.cerrada_en = utcnow()
    caja.estado = "CERRADA"
    if notas:
        caja.notas = f"{caja.notas}\n{notas}" if caja.notas else notas
    db.commit()
    return caja


def _abierta(caja: Caja) -> None:
    if caja.estado != "ABIERTA":
        raise CajaError(409, "La caja ya está cerrada")


def a_dict(db: Session, caja: Caja, detalle: bool = False) -> dict:
    datos = {
        "id": str(caja.id), "sucursal": caja.sucursal, "terminal": caja.terminal, "estado": caja.estado,
        "monto_apertura": str(caja.monto_apertura), "abierta_por": caja.abierta_por, "abierta_en": caja.abierta_en,
        "monto_contado": str(caja.monto_contado) if caja.monto_contado is not None else None,
        "cerrada_por": caja.cerrada_por, "cerrada_en": caja.cerrada_en, "notas": caja.notas,
        # Cerrada: el arqueo guardado al cierre; abierta: calculado al momento
        "resumen": caja.resumen if caja.estado == "CERRADA" else resumen(db, caja),
    }
    if detalle:
        datos["movimientos"] = [
            {"id": str(m.id), "tipo": m.tipo, "monto": str(m.monto), "motivo": m.motivo, "usuario": m.usuario, "fecha": m.fecha}
            for m in caja.movimientos
        ]
    return datos
