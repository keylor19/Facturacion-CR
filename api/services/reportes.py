"""
Reportes para contadores: resumen de IVA del mes (insumo para la
declaración D-104) y libros de ventas y compras.

Solo cuentan los documentos ACEPTADOS por Hacienda. Los montos se
convierten a colones con el tipo de cambio de cada comprobante y las notas
de crédito restan.

⚠️ Es un insumo de trabajo: la declaración tiene casillas y reglas
(prorrata, proporcionalidad, etc.) que el contador debe revisar.
"""
import csv
import io
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.models.database import DocumentoRecibido, Emisor, EstadoFactura, Factura
from api.models.schemas import TARIFAS_IVA, TIPOS_COMPROBANTE
from api.services.fechas import zona_cr

CERO = Decimal("0")
TIPOS_VENTA = ("01", "02", "03", "04", "09")


def _r(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rango_mes(anio: int, mes: int) -> tuple[datetime, datetime]:
    tz = zona_cr()
    inicio = datetime(anio, mes, 1, tzinfo=tz)
    fin = datetime(anio + (mes == 12), mes % 12 + 1, 1, tzinfo=tz)
    return inicio, fin


def _signo(tipo_documento: str) -> int:
    return -1 if tipo_documento == "03" else 1


def _tc(valor) -> Decimal:
    return Decimal(valor) if valor else Decimal("1")


def _ventas(db: Session, emisor: Emisor, desde: datetime, hasta: datetime):
    return db.scalars(
        select(Factura)
        .options(selectinload(Factura.detalles))
        .where(
            Factura.emisor_id == emisor.id,
            Factura.estado == EstadoFactura.ACEPTADO,
            Factura.tipo_documento.in_(TIPOS_VENTA),
            Factura.fecha_emision >= desde,
            Factura.fecha_emision < hasta,
        )
        .order_by(Factura.fecha_emision)
    ).all()


def _compras(db: Session, emisor: Emisor, desde: datetime, hasta: datetime):
    return db.scalars(
        select(DocumentoRecibido).where(
            DocumentoRecibido.emisor_id == emisor.id,
            DocumentoRecibido.estado == EstadoFactura.ACEPTADO,
            DocumentoRecibido.mensaje.in_(("1", "2")),
            DocumentoRecibido.fecha_emision >= desde,
            DocumentoRecibido.fecha_emision < hasta,
        ).order_by(DocumentoRecibido.fecha_emision)
    ).all()


def _facturas_compra(db: Session, emisor: Emisor, desde: datetime, hasta: datetime):
    return db.scalars(
        select(Factura).where(
            Factura.emisor_id == emisor.id,
            Factura.estado == EstadoFactura.ACEPTADO,
            Factura.tipo_documento == "08",
            Factura.fecha_emision >= desde,
            Factura.fecha_emision < hasta,
        )
    ).all()


def resumen_iva(db: Session, emisor: Emisor, anio: int, mes: int) -> dict:
    desde, hasta = rango_mes(anio, mes)

    # --- Ventas por tarifa ---
    por_tarifa = defaultdict(lambda: {"base": CERO, "iva": CERO, "exonerado": CERO})
    totales_ventas = defaultdict(lambda: CERO)
    cantidad_por_tipo = defaultdict(int)
    for f in _ventas(db, emisor, desde, hasta):
        factor = _tc(f.tipo_cambio) * _signo(f.tipo_documento)
        cantidad_por_tipo[f.tipo_documento] += 1
        totales_ventas["venta_neta"] += (f.total_venta - f.total_descuentos) * factor
        totales_ventas["gravado"] += f.total_gravado * factor
        totales_ventas["exento"] += f.total_exento * factor
        totales_ventas["exonerado"] += f.total_exonerado * factor
        totales_ventas["iva"] += f.monto_impuesto * factor
        totales_ventas["otros_cargos"] += f.total_otros_cargos * factor
        totales_ventas["total"] += f.monto_total * factor
        for d in f.detalles:
            fila = por_tarifa[d.codigo_tarifa_iva or "sin_iva"]
            fila["base"] += d.subtotal * factor
            fila["iva"] += d.impuesto_neto * factor
            fila["exonerado"] += d.monto_exonerado * factor

    # --- Compras (mensajes receptor aceptados) por condición del impuesto ---
    por_condicion = defaultdict(lambda: {"documentos": 0, "total": CERO, "iva": CERO, "iva_acreditable": CERO, "gasto_aplicable": CERO})
    for d in _compras(db, emisor, desde, hasta):
        factor = _tc(d.tipo_cambio) * _signo(d.tipo_documento)
        fila = por_condicion[d.condicion_impuesto or "sin_impuesto"]
        fila["documentos"] += 1
        fila["total"] += d.total_comprobante * factor
        fila["iva"] += d.total_impuesto * factor
        fila["iva_acreditable"] += (d.monto_impuesto_acreditar or CERO) * factor
        fila["gasto_aplicable"] += (d.monto_gasto_aplicable or CERO) * factor

    fec_total = fec_iva = CERO
    fecs = _facturas_compra(db, emisor, desde, hasta)
    for f in fecs:
        fec_total += f.monto_total * _tc(f.tipo_cambio)
        fec_iva += f.monto_impuesto * _tc(f.tipo_cambio)

    # Recibos electrónicos de pago (cobro de ventas a crédito 08/10)
    rep_por_tarifa = defaultdict(lambda: {"base": CERO, "iva": CERO})
    reps = db.scalars(
        select(Factura).options(selectinload(Factura.detalles)).where(
            Factura.emisor_id == emisor.id, Factura.estado == EstadoFactura.ACEPTADO,
            Factura.tipo_documento == "10", Factura.fecha_emision >= desde, Factura.fecha_emision < hasta,
        )
    ).all()
    for r in reps:
        for d in r.detalles:
            fila = rep_por_tarifa[d.codigo_tarifa_iva or "sin_iva"]
            fila["base"] += d.subtotal * _tc(r.tipo_cambio)
            fila["iva"] += d.impuesto_neto * _tc(r.tipo_cambio)

    iva_debito = totales_ventas["iva"]
    iva_credito = sum((c["iva_acreditable"] for c in por_condicion.values()), CERO)

    return {
        "emisor": {"id": str(emisor.id), "identificacion": emisor.numero_identificacion, "nombre": emisor.nombre},
        "periodo": f"{anio:04d}-{mes:02d}",
        "moneda": "CRC",
        "ventas": {
            "documentos": {TIPOS_COMPROBANTE[t]: n for t, n in sorted(cantidad_por_tipo.items())},
            **{k: _r(v) for k, v in totales_ventas.items()},
            "por_tarifa": [
                {
                    "codigo_tarifa_iva": codigo,
                    "tarifa": str(TARIFAS_IVA.get(codigo, "")),
                    "base": _r(v["base"]), "iva": _r(v["iva"]), "exonerado": _r(v["exonerado"]),
                }
                for codigo, v in sorted(por_tarifa.items())
            ],
        },
        "compras": {
            "por_condicion_impuesto": [
                {"condicion_impuesto": c, "documentos": v["documentos"],
                 **{k: _r(v[k]) for k in ("total", "iva", "iva_acreditable", "gasto_aplicable")}}
                for c, v in sorted(por_condicion.items())
            ],
            "facturas_compra_emitidas": {"documentos": len(fecs), "total": _r(fec_total), "iva": _r(fec_iva)},
        },
        "recibos_pago": {
            "documentos": len(reps),
            "nota": "IVA cobrado mediante recibos de pago de ventas a crédito (condición 08/10); "
                    "el contador define en qué periodo se declara.",
            "por_tarifa": [
                {"codigo_tarifa_iva": c, "base": _r(v["base"]), "iva": _r(v["iva"])}
                for c, v in sorted(rep_por_tarifa.items())
            ],
        },
        "iva_debito_fiscal": _r(iva_debito),
        "iva_credito_fiscal": _r(iva_credito),
        "iva_neto_estimado": _r(iva_debito - iva_credito),
        "advertencia": "Insumo para la declaración D-104; revisar prorrata, proporcionalidad y demás ajustes.",
    }


def _csv(encabezados: list[str], filas) -> str:
    salida = io.StringIO()
    salida.write("﻿")  # BOM para que Excel reconozca UTF-8
    writer = csv.writer(salida, delimiter=";")
    writer.writerow(encabezados)
    writer.writerows(filas)
    return salida.getvalue()


def libro_ventas_csv(db: Session, emisor: Emisor, anio: int, mes: int) -> str:
    desde, hasta = rango_mes(anio, mes)
    filas = []
    for f in _ventas(db, emisor, desde, hasta):
        factor = _tc(f.tipo_cambio) * _signo(f.tipo_documento)
        filas.append([
            f.fecha_emision.astimezone(zona_cr()).strftime("%Y-%m-%d %H:%M"),
            TIPOS_COMPROBANTE.get(f.tipo_documento, f.tipo_documento), f.numero_consecutivo, f.clave,
            f.receptor_identificacion or "", f.receptor_nombre or "", f.moneda, f.tipo_cambio or 1,
            _r(f.total_gravado * factor), _r(f.total_exento * factor), _r(f.total_exonerado * factor),
            _r(f.total_descuentos * factor), _r(f.monto_impuesto * factor), _r(f.total_otros_cargos * factor),
            _r(f.monto_total * factor),
        ])
    return _csv(
        ["Fecha", "Tipo", "Consecutivo", "Clave", "Identificación receptor", "Receptor", "Moneda", "Tipo cambio",
         "Gravado CRC", "Exento CRC", "Exonerado CRC", "Descuentos CRC", "IVA CRC", "Otros cargos CRC", "Total CRC"],
        filas,
    )


def libro_compras_csv(db: Session, emisor: Emisor, anio: int, mes: int) -> str:
    desde, hasta = rango_mes(anio, mes)
    mensajes = {"1": "Aceptado", "2": "Aceptado parcial", "3": "Rechazado"}
    filas = []
    for d in _compras(db, emisor, desde, hasta):
        factor = _tc(d.tipo_cambio) * _signo(d.tipo_documento)
        filas.append([
            d.fecha_emision.astimezone(zona_cr()).strftime("%Y-%m-%d %H:%M") if d.fecha_emision else "",
            TIPOS_COMPROBANTE.get(d.tipo_documento, d.tipo_documento), d.clave,
            d.proveedor_identificacion, d.proveedor_nombre or "", d.moneda, d.tipo_cambio or 1,
            _r(d.total_impuesto * factor), _r((d.monto_impuesto_acreditar or CERO) * factor),
            _r((d.monto_gasto_aplicable or CERO) * factor), _r(d.total_comprobante * factor),
            mensajes.get(d.mensaje, ""), d.condicion_impuesto or "", d.consecutivo_receptor or "",
        ])
    return _csv(
        ["Fecha", "Tipo", "Clave", "Identificación proveedor", "Proveedor", "Moneda", "Tipo cambio",
         "IVA CRC", "IVA acreditable CRC", "Gasto aplicable CRC", "Total CRC", "Mensaje", "Condición impuesto",
         "Consecutivo receptor"],
        filas,
    )


def estadisticas(db: Session, emisor: Emisor, anio: int, mes: int) -> dict:
    """Números del mes para el tablero del panel."""
    desde, hasta = rango_mes(anio, mes)
    filtro = (Factura.emisor_id == emisor.id, Factura.fecha_emision >= desde, Factura.fecha_emision < hasta)

    por_estado = dict(db.execute(
        select(Factura.estado, func.count()).where(*filtro).group_by(Factura.estado)
    ).all())
    por_tipo = dict(db.execute(
        select(Factura.tipo_documento, func.count()).where(*filtro).group_by(Factura.tipo_documento)
    ).all())

    ventas = impuesto = CERO
    for f in _ventas(db, emisor, desde, hasta):
        factor = _tc(f.tipo_cambio) * _signo(f.tipo_documento)
        ventas += f.monto_total * factor
        impuesto += f.monto_impuesto * factor

    recibidos_pendientes = db.scalar(select(func.count()).select_from(DocumentoRecibido).where(
        DocumentoRecibido.emisor_id == emisor.id, DocumentoRecibido.estado.is_(None)
    ))
    con_error = db.scalar(select(func.count()).select_from(Factura).where(
        Factura.emisor_id == emisor.id,
        Factura.estado.in_((EstadoFactura.ERROR_COMUNICACION, EstadoFactura.RECHAZADO)),
        Factura.fecha_emision >= desde, Factura.fecha_emision < hasta,
    ))
    return {
        "periodo": f"{anio:04d}-{mes:02d}",
        "comprobantes_por_estado": {e.value: n for e, n in por_estado.items()},
        "comprobantes_por_tipo": {TIPOS_COMPROBANTE.get(t, t): n for t, n in por_tipo.items()},
        "ventas_aceptadas_crc": _r(ventas),
        "iva_ventas_crc": _r(impuesto),
        "recibidos_sin_responder": recibidos_pendientes or 0,
        "con_error_o_rechazados": con_error or 0,
    }
