"""
Cuentas por cobrar: saldo de cada factura a crédito, antigüedad (al día, 1-30,
31-60, 61-90, más de 90 días), estado de cuenta por cliente y recordatorios.

Saldo = total + notas de débito - notas de crédito - pagos. Los pagos son abonos
(crédito comercial, condición 02) o recibos electrónicos de pago (condiciones 08 y 10).
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.models.database import Abono, EstadoFactura, Factura
from api.services.fechas import ahora_cr, zona_cr

CONDICIONES_CREDITO = ("02", "08", "10")
CON_RECIBO = ("08", "10")
TRAMOS = ("al_dia", "1_30", "31_60", "61_90", "mas_90")
NOMBRE_TRAMO = {"al_dia": "Al día", "1_30": "1 a 30 días", "31_60": "31 a 60 días",
                "61_90": "61 a 90 días", "mas_90": "Más de 90 días"}
# Días de atraso en que se manda recordatorio por correo (una sola vez cada uno)
DIAS_RECORDATORIO = (1, 8, 15, 30, 60)
CENTIMO = Decimal("0.01")


def plazo(f: Factura) -> int:
    try:
        return int((f.json_original or {}).get("plazo_credito") or 0)
    except (TypeError, ValueError):
        return 0


def vencimiento(f: Factura) -> date:
    return f.fecha_emision.astimezone(zona_cr()).date() + timedelta(days=plazo(f))


def tramo(dias_vencida: int) -> str:
    if dias_vencida <= 0:
        return "al_dia"
    if dias_vencida <= 30:
        return "1_30"
    if dias_vencida <= 60:
        return "31_60"
    if dias_vencida <= 90:
        return "61_90"
    return "mas_90"


def _movimientos(db: Session, facturas: list[Factura]) -> tuple[dict, dict, dict]:
    """Notas (± por factura), pagos con recibo y abonos, en pocas consultas."""
    ids = [f.id for f in facturas]
    por_clave = {f.clave: f.id for f in facturas}
    notas: dict[str, Decimal] = defaultdict(Decimal)
    recibos: dict[str, Decimal] = defaultdict(Decimal)
    abonos: dict[str, Decimal] = defaultdict(Decimal)
    if not ids:
        return notas, recibos, abonos
    for n in db.scalars(select(Factura).where(
        Factura.tipo_documento.in_(("02", "03")), Factura.estado != EstadoFactura.RECHAZADO,
        or_(Factura.factura_origen_id.in_(ids), Factura.referencia_clave.in_(list(por_clave))),
    )):
        destino = n.factura_origen_id if n.factura_origen_id in ids else por_clave.get(n.referencia_clave)
        if destino:
            notas[destino] += n.monto_total if n.tipo_documento == "02" else -n.monto_total
    for r in db.scalars(select(Factura).where(
        Factura.tipo_documento == "10", Factura.estado != EstadoFactura.RECHAZADO, Factura.factura_origen_id.in_(ids),
    )):
        recibos[r.factura_origen_id] += r.monto_total
    for a in db.scalars(select(Abono).where(Abono.factura_id.in_(ids), Abono.anulado.is_(False))):
        abonos[a.factura_id] += a.monto
    return notas, recibos, abonos


def _fila(f: Factura, notas: Decimal, pagado: Decimal, hoy: date) -> dict:
    vence = vencimiento(f)
    dias = (hoy - vence).days
    saldo = (f.monto_total + notas - pagado).quantize(CENTIMO)
    return {
        "factura_id": str(f.id), "consecutivo": f.numero_consecutivo, "clave": f.clave,
        "fecha": f.fecha_emision.astimezone(zona_cr()).date().isoformat(), "vence": vence.isoformat(),
        "plazo": plazo(f), "dias_vencida": max(dias, 0), "tramo": tramo(dias),
        "condicion_venta": f.condicion_venta, "con_recibo": f.condicion_venta in CON_RECIBO,
        "cliente": f.receptor_nombre, "identificacion": f.receptor_identificacion, "correo": f.receptor_correo,
        "moneda": f.moneda, "total": str(f.monto_total.quantize(CENTIMO)), "notas": str(notas.quantize(CENTIMO)),
        "pagado": str(pagado.quantize(CENTIMO)), "saldo": str(saldo), "estado": f.estado.value,
    }


def facturas_a_credito(db: Session, emisor_id: str, identificacion: str | None = None) -> list[Factura]:
    query = select(Factura).where(
        Factura.emisor_id == emisor_id, Factura.tipo_documento.in_(("01", "09")),
        Factura.condicion_venta.in_(CONDICIONES_CREDITO), Factura.estado != EstadoFactura.RECHAZADO,
    ).order_by(Factura.fecha_emision)
    if identificacion:
        query = query.where(Factura.receptor_identificacion == identificacion)
    return list(db.scalars(query))


def detalle(db: Session, facturas: list[Factura], hoy: date | None = None) -> list[dict]:
    hoy = hoy or ahora_cr().date()
    notas, recibos, abonos = _movimientos(db, facturas)
    return [_fila(f, notas[f.id], recibos[f.id] + abonos[f.id], hoy) for f in facturas]


def cartera(db: Session, emisor_id: str, hoy: date | None = None) -> dict:
    """Facturas con saldo pendiente, totales por antigüedad (por moneda) y por cliente."""
    filas = [x for x in detalle(db, facturas_a_credito(db, emisor_id), hoy) if Decimal(x["saldo"]) > 0]
    resumen: dict[str, dict[str, Decimal]] = defaultdict(lambda: {t: Decimal("0") for t in TRAMOS})
    clientes: dict[tuple, dict] = {}
    for x in filas:
        monto = Decimal(x["saldo"])
        resumen[x["moneda"]][x["tramo"]] += monto
        clave = (x["identificacion"] or x["cliente"] or "", x["moneda"])
        c = clientes.setdefault(clave, {"identificacion": x["identificacion"], "cliente": x["cliente"],
                                        "correo": x["correo"], "moneda": x["moneda"], "saldo": Decimal("0"),
                                        "vencido": Decimal("0"), "facturas": 0, "mas_atraso": 0})
        c["saldo"] += monto
        c["facturas"] += 1
        if x["tramo"] != "al_dia":
            c["vencido"] += monto
        c["mas_atraso"] = max(c["mas_atraso"], x["dias_vencida"])
    return {
        "facturas": filas,
        "resumen": {m: {t: str(v) for t, v in tramos.items()} | {"total": str(sum(tramos.values()))}
                    for m, tramos in resumen.items()},
        "clientes": sorted(({**c, "saldo": str(c["saldo"]), "vencido": str(c["vencido"])} for c in clientes.values()),
                           key=lambda c: -Decimal(c["vencido"])),
    }


def estado_de_cuenta(db: Session, emisor_id: str, identificacion: str, hoy: date | None = None) -> dict:
    """Todas las facturas a crédito de un cliente (pagadas o no) con sus abonos."""
    facturas = facturas_a_credito(db, emisor_id, identificacion)
    filas = detalle(db, facturas, hoy)
    ids = [f.id for f in facturas]
    pagos = defaultdict(list)
    if ids:
        for a in db.scalars(select(Abono).where(Abono.factura_id.in_(ids), Abono.anulado.is_(False)).order_by(Abono.fecha)):
            pagos[a.factura_id].append({"fecha": a.fecha.isoformat(), "monto": str(a.monto.quantize(CENTIMO)),
                                        "medio_pago": a.medio_pago, "referencia": a.referencia})
        for r in db.scalars(select(Factura).where(Factura.tipo_documento == "10", Factura.factura_origen_id.in_(ids),
                                                  Factura.estado != EstadoFactura.RECHAZADO)):
            pagos[r.factura_origen_id].append({"fecha": r.fecha_emision.astimezone(zona_cr()).date().isoformat(),
                                               "monto": str(r.monto_total.quantize(CENTIMO)), "medio_pago": None,
                                               "referencia": f"Recibo {r.numero_consecutivo}"})
    totales: dict[str, Decimal] = defaultdict(Decimal)
    for x in filas:
        x["pagos"] = pagos.get(x["factura_id"], [])
        totales[x["moneda"]] += Decimal(x["saldo"])
    ultima = facturas[-1] if facturas else None
    return {
        "identificacion": identificacion,
        "cliente": ultima.receptor_nombre if ultima else None,
        "correo": ultima.receptor_correo if ultima else None,
        "facturas": filas,
        "saldo": {m: str(v) for m, v in totales.items()},
    }


def saldo_factura(db: Session, f: Factura) -> Decimal:
    notas, recibos, abonos = _movimientos(db, [f])
    return (f.monto_total + notas[f.id] - recibos[f.id] - abonos[f.id]).quantize(CENTIMO)
