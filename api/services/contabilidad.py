"""
Contabilidad de las empresas que atiende un contador: catálogo de cuentas, asientos
(manuales y automáticos desde los comprobantes), cierre de meses y reportes
(libro diario, mayor, balance de comprobación, balance general, estado de resultados).

Todo se lleva en colones: los comprobantes en otra moneda se convierten con su tipo de cambio.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from api.models.database import (
    Abono, Asiento, AsientoLinea, CuentaContable, DocumentoRecibido, EstadoFactura, Factura, MovimientoInventario,
    PeriodoCerrado,
)
from api.services.fechas import zona_cr

CENTIMO = Decimal("0.01")
CERO = Decimal("0")
TIPOS = ("activo", "pasivo", "patrimonio", "ingreso", "costo", "gasto")
DEUDORAS = ("activo", "costo", "gasto")       # su saldo es debe - haber

# Catálogo base (NIIF para PYMES, simplificado para Costa Rica). Editable por el contador.
# (código, nombre, tipo, acepta movimientos, clave que usan los asientos automáticos)
CATALOGO_BASE = [
    ("1", "Activo", "activo", False, None),
    ("1.1", "Activo corriente", "activo", False, None),
    ("1.1.01", "Caja y bancos", "activo", True, "caja_bancos"),
    ("1.1.02", "Cuentas por cobrar a clientes", "activo", True, "clientes"),
    ("1.1.03", "IVA crédito fiscal", "activo", True, "iva_credito"),
    ("1.1.04", "Inventario de mercadería", "activo", True, "inventario"),
    ("1.1.05", "Otras cuentas por cobrar", "activo", True, None),
    ("1.1.06", "Gastos pagados por adelantado", "activo", True, None),
    ("1.2", "Activo no corriente", "activo", False, None),
    ("1.2.01", "Mobiliario y equipo", "activo", True, None),
    ("1.2.02", "Equipo de cómputo", "activo", True, None),
    ("1.2.03", "Vehículos", "activo", True, None),
    ("1.2.04", "Depreciación acumulada", "activo", True, None),
    ("2", "Pasivo", "pasivo", False, None),
    ("2.1", "Pasivo corriente", "pasivo", False, None),
    ("2.1.01", "Cuentas por pagar a proveedores", "pasivo", True, "proveedores"),
    ("2.1.02", "IVA débito fiscal por pagar", "pasivo", True, "iva_debito"),
    ("2.1.03", "Impuesto sobre la renta por pagar", "pasivo", True, None),
    ("2.1.04", "Cargas sociales por pagar", "pasivo", True, None),
    ("2.1.05", "Salarios por pagar", "pasivo", True, None),
    ("2.1.06", "Otras cuentas por pagar", "pasivo", True, None),
    ("2.2", "Pasivo no corriente", "pasivo", False, None),
    ("2.2.01", "Préstamos bancarios a largo plazo", "pasivo", True, None),
    ("3", "Patrimonio", "patrimonio", False, None),
    ("3.1", "Capital social", "patrimonio", True, None),
    ("3.2", "Reserva legal", "patrimonio", True, None),
    ("3.3", "Utilidades acumuladas", "patrimonio", True, "utilidades_acumuladas"),
    ("4", "Ingresos", "ingreso", False, None),
    ("4.1", "Ventas de bienes y servicios", "ingreso", True, "ventas"),
    ("4.2", "Devoluciones y descuentos sobre ventas", "ingreso", True, "devoluciones_ventas"),
    ("4.3", "Otros ingresos", "ingreso", True, "otros_ingresos"),
    ("5", "Costos", "costo", False, None),
    ("5.1", "Costo de ventas", "costo", True, "costo_ventas"),
    ("6", "Gastos", "gasto", False, None),
    ("6.1", "Gastos de operación", "gasto", False, None),
    ("6.1.01", "Compras y gastos generales", "gasto", True, "compras_gastos"),
    ("6.1.02", "Salarios", "gasto", True, None),
    ("6.1.03", "Cargas sociales", "gasto", True, None),
    ("6.1.04", "Alquileres", "gasto", True, None),
    ("6.1.05", "Servicios públicos", "gasto", True, None),
    ("6.1.06", "Honorarios profesionales", "gasto", True, None),
    ("6.1.07", "Depreciación", "gasto", True, None),
    ("6.1.08", "IVA no acreditable", "gasto", True, "iva_no_acreditable"),
    ("6.2", "Gastos financieros", "gasto", False, None),
    ("6.2.01", "Intereses y comisiones bancarias", "gasto", True, None),
    ("6.2.02", "Diferencias de cambio", "gasto", True, None),
    ("6.9", "Otros gastos", "gasto", True, "otros_gastos"),
]


class ContabilidadError(Exception):
    def __init__(self, detalle: str, status_code: int = 422):
        super().__init__(detalle)
        self.detalle = detalle
        self.status_code = status_code


def q(valor) -> Decimal:
    return Decimal(valor or 0).quantize(CENTIMO)


def mes_de(fecha: date) -> date:
    return fecha.replace(day=1)


def fecha_cr(dt: datetime) -> date:
    return dt.astimezone(zona_cr()).date()


# --- Catálogo -----------------------------------------------------------------------------

def tiene_catalogo(db: Session, emisor_id: str) -> bool:
    return bool(db.scalar(select(func.count()).select_from(CuentaContable).where(CuentaContable.emisor_id == emisor_id)))


def crear_catalogo_base(db: Session, emisor_id: str) -> int:
    if tiene_catalogo(db, emisor_id):
        raise ContabilidadError("La empresa ya tiene catálogo de cuentas", 409)
    for codigo, nombre, tipo, acepta, clave in CATALOGO_BASE:
        db.add(CuentaContable(emisor_id=emisor_id, codigo=codigo, nombre=nombre, tipo=tipo,
                              acepta_movimientos=acepta, clave_sistema=clave))
    db.commit()
    return len(CATALOGO_BASE)


def cuentas(db: Session, emisor_id: str) -> list[CuentaContable]:
    return list(db.scalars(select(CuentaContable).where(CuentaContable.emisor_id == emisor_id)))


def ordenar(lista: list[CuentaContable]) -> list[CuentaContable]:
    """Orden natural del código: 1.1.2 antes que 1.1.10."""
    return sorted(lista, key=lambda c: [int(p) if p.isdigit() else p for p in c.codigo.split(".")])


def cuenta_sistema(db: Session, emisor_id: str, clave: str) -> CuentaContable:
    c = db.scalar(select(CuentaContable).where(CuentaContable.emisor_id == emisor_id, CuentaContable.clave_sistema == clave,
                                               CuentaContable.activa.is_(True)))
    if c is None:
        raise ContabilidadError(f"Falta la cuenta para «{clave}» en el catálogo (márquela en la cuenta que corresponda)")
    return c


def padre(codigo: str) -> str | None:
    return codigo.rsplit(".", 1)[0] if "." in codigo else None


# --- Períodos -------------------------------------------------------------------------------

def mes_cerrado(db: Session, emisor_id: str, fecha: date) -> bool:
    return db.get(PeriodoCerrado, (emisor_id, mes_de(fecha))) is not None


def _exigir_abierto(db: Session, emisor_id: str, fecha: date) -> None:
    if mes_cerrado(db, emisor_id, fecha):
        raise ContabilidadError(f"El mes {fecha:%m/%Y} está cerrado. Ábralo para hacer cambios.", 409)


# --- Asientos -------------------------------------------------------------------------------

def _siguiente_numero(db: Session, emisor_id: str) -> int:
    return (db.scalar(select(func.max(Asiento.numero)).where(Asiento.emisor_id == emisor_id)) or 0) + 1


def _validar_lineas(db: Session, emisor_id: str, lineas: list[dict]) -> list[dict]:
    limpias = []
    for ln in lineas:
        debe, haber = q(ln.get("debe")), q(ln.get("haber"))
        if debe < 0 or haber < 0 or (debe and haber) or not (debe or haber):
            raise ContabilidadError("Cada línea lleva un monto en el debe o en el haber (positivo, no ambos)")
        c = db.get(CuentaContable, str(ln["cuenta_id"]))
        if c is None or c.emisor_id != emisor_id:
            raise ContabilidadError("Hay una cuenta que no es de esta empresa")
        if not c.acepta_movimientos or not c.activa:
            raise ContabilidadError(f"La cuenta {c.codigo} {c.nombre} no acepta movimientos (es de grupo o está inactiva)")
        limpias.append({"cuenta_id": c.id, "debe": debe, "haber": haber, "detalle": (ln.get("detalle") or None)})
    if len(limpias) < 2:
        raise ContabilidadError("Un asiento necesita al menos dos líneas")
    if sum(x["debe"] for x in limpias) != sum(x["haber"] for x in limpias):
        raise ContabilidadError("El asiento no cuadra: el total del debe debe ser igual al del haber")
    return limpias


def crear_asiento(db: Session, emisor_id: str, fecha: date, descripcion: str, lineas: list[dict], *,
                  origen: str = "manual", documento_ref: str | None = None, quien: str | None = None,
                  confirmar: bool = True) -> Asiento:
    _exigir_abierto(db, emisor_id, fecha)
    limpias = _validar_lineas(db, emisor_id, lineas)
    a = Asiento(emisor_id=emisor_id, numero=_siguiente_numero(db, emisor_id), fecha=fecha,
                descripcion=descripcion[:300], origen=origen, documento_ref=documento_ref, creado_por=quien)
    a.lineas = [AsientoLinea(**x) for x in limpias]
    db.add(a)
    if confirmar:
        db.commit()
    else:
        db.flush()
    return a


def actualizar_asiento(db: Session, a: Asiento, fecha: date, descripcion: str, lineas: list[dict]) -> Asiento:
    if a.anulado:
        raise ContabilidadError("El asiento está anulado", 409)
    _exigir_abierto(db, a.emisor_id, a.fecha)
    _exigir_abierto(db, a.emisor_id, fecha)
    limpias = _validar_lineas(db, a.emisor_id, lineas)
    a.fecha, a.descripcion = fecha, descripcion[:300]
    a.lineas = [AsientoLinea(**x) for x in limpias]
    if a.origen != "manual":
        a.editado = True
    db.commit()
    return a


def anular_asiento(db: Session, a: Asiento) -> None:
    if a.anulado:
        raise ContabilidadError("El asiento ya estaba anulado", 409)
    _exigir_abierto(db, a.emisor_id, a.fecha)
    a.anulado = True
    db.commit()


# --- Asientos automáticos desde los comprobantes --------------------------------------------

def _factor(tipo_cambio) -> Decimal:
    return Decimal(tipo_cambio) if tipo_cambio else Decimal("1")


def _cuadrar(lineas: list[tuple], ajuste_ingreso: CuentaContable, ajuste_gasto: CuentaContable) -> list[dict]:
    """Quita líneas en cero y lleva el redondeo (céntimos) a otros ingresos / otros gastos."""
    salida = [{"cuenta_id": c.id, "debe": q(d), "haber": q(h), "detalle": det} for c, d, h, det in lineas if q(d) or q(h)]
    diferencia = sum(x["debe"] for x in salida) - sum(x["haber"] for x in salida)
    if diferencia > 0:
        salida.append({"cuenta_id": ajuste_ingreso.id, "debe": CERO, "haber": diferencia, "detalle": "Redondeo"})
    elif diferencia < 0:
        salida.append({"cuenta_id": ajuste_gasto.id, "debe": -diferencia, "haber": CERO, "detalle": "Redondeo"})
    return salida


def _lineas_factura(cs, f: Factura) -> tuple[str, str, list]:
    """(origen, descripción, líneas) del asiento de un comprobante emitido."""
    fx = _factor(f.tipo_cambio)
    neto = (f.total_venta - f.total_descuentos) * fx
    iva = f.monto_impuesto * fx
    otros = f.total_otros_cargos * fx
    devuelto = (f.total_iva_devuelto or CERO) * fx
    total = f.monto_total * fx
    a_credito = f.condicion_venta in ("02", "08", "10")
    cobro = cs("clientes") if a_credito else cs("caja_bancos")
    cliente = f.receptor_nombre or "Consumidor final"
    t = f.tipo_documento
    if t in ("01", "04", "09", "02"):
        nombre = {"02": "Nota de débito", "04": "Tiquete", "09": "Exportación"}.get(t, "Venta")
        return "venta", f"{nombre} {f.numero_consecutivo} · {cliente}", [
            (cobro, total, 0, cliente), (cs("ventas"), 0, neto, None), (cs("iva_debito"), 0, iva, None),
            (cs("otros_ingresos"), 0, otros, "Otros cargos"), (cs("iva_debito"), devuelto, 0, "IVA devuelto"),
        ]
    if t == "03":
        return "venta", f"Nota de crédito {f.numero_consecutivo} · {cliente}", [
            (cs("devoluciones_ventas"), neto, 0, None), (cs("iva_debito"), iva, 0, None),
            (cs("otros_ingresos"), otros, 0, "Otros cargos"), (cobro, 0, total, cliente),
        ]
    if t == "10":
        return "cobro", f"Recibo de pago {f.numero_consecutivo} · {cliente}", [
            (cs("caja_bancos"), total, 0, None), (cs("clientes"), 0, total, cliente),
        ]
    if t == "08":
        proveedor = f.receptor_nombre or "Proveedor"
        return "compra", f"Factura de compra {f.numero_consecutivo} · {proveedor}", [
            (cs("compras_gastos"), total - iva, 0, proveedor), (cs("iva_credito"), iva, 0, None),
            (cs("caja_bancos"), 0, total, None),
        ]
    return "", "", []


def _lineas_recibido(cs, d: DocumentoRecibido) -> tuple[str, str, list]:
    fx = _factor(d.tipo_cambio)
    total = d.total_comprobante * fx
    iva = d.total_impuesto * fx
    if d.monto_impuesto_acreditar is not None:
        acreditable = d.monto_impuesto_acreditar * fx
    else:
        acreditable = iva if (d.condicion_impuesto or "01") == "01" else CERO
    proveedor = d.proveedor_nombre or d.proveedor_identificacion
    lineas = [(cs("compras_gastos"), total - acreditable, 0, proveedor), (cs("iva_credito"), acreditable, 0, None),
              (cs("proveedores"), 0, total, proveedor)]
    if d.tipo_documento == "03":   # nota de crédito del proveedor: al revés
        lineas = [(c, h, de, det) for c, de, h, det in lineas]
    nombre = {"02": "Nota de débito", "03": "Nota de crédito"}.get(d.tipo_documento, "Compra")
    return "compra", f"{nombre} de {proveedor} ({d.clave[21:41]})", lineas


def documentos_del_mes(db: Session, emisor_id: str, desde: date, hasta: date):
    inicio = datetime.combine(desde, time.min, tzinfo=zona_cr())
    fin = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona_cr())
    facturas = db.scalars(select(Factura).where(
        Factura.emisor_id == emisor_id, Factura.estado == EstadoFactura.ACEPTADO,
        Factura.fecha_emision >= inicio, Factura.fecha_emision < fin).order_by(Factura.fecha_emision)).all()
    recibidos = db.scalars(select(DocumentoRecibido).where(
        DocumentoRecibido.emisor_id == emisor_id, DocumentoRecibido.mensaje.in_(("1", "2")),
        DocumentoRecibido.estado == EstadoFactura.ACEPTADO,
        DocumentoRecibido.fecha_emision >= inicio, DocumentoRecibido.fecha_emision < fin)
        .order_by(DocumentoRecibido.fecha_emision)).all()
    abonos = db.scalars(select(Abono).where(Abono.emisor_id == emisor_id, Abono.anulado.is_(False),
                                            Abono.fecha >= desde, Abono.fecha <= hasta).order_by(Abono.fecha)).all()
    return facturas, recibidos, abonos


def contabilizar(db: Session, emisor_id: str, anio: int, mes: int, quien: str | None = None) -> dict:
    """
    Crea los asientos que faltan de los comprobantes aceptados del mes (ventas, notas,
    recibos, compras) y de los abonos de clientes. Los que ya tienen asiento no se tocan,
    así que se puede correr las veces que haga falta.
    """
    desde = date(anio, mes, 1)
    hasta = (desde + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    _exigir_abierto(db, emisor_id, desde)
    if not tiene_catalogo(db, emisor_id):
        raise ContabilidadError("Primero cree el catálogo de cuentas", 409)
    cache: dict[str, CuentaContable] = {}

    def cs(clave: str) -> CuentaContable:
        if clave not in cache:
            cache[clave] = cuenta_sistema(db, emisor_id, clave)
        return cache[clave]

    facturas, recibidos, abonos = documentos_del_mes(db, emisor_id, desde, hasta)
    hechos = set(db.scalars(select(Asiento.documento_ref).where(Asiento.emisor_id == emisor_id,
                                                                 Asiento.documento_ref.is_not(None))))
    creados = defaultdict(int)
    pendientes = []
    for f in facturas:
        pendientes.append((f"factura:{f.id}", fecha_cr(f.fecha_emision), *_lineas_factura(cs, f)))
    for d in recibidos:
        pendientes.append((f"recibido:{d.id}", fecha_cr(d.fecha_emision), *_lineas_recibido(cs, d)))
    for a in abonos:
        f = db.get(Factura, a.factura_id)
        cliente = f.receptor_nombre if f else ""
        monto = a.monto * _factor(f.tipo_cambio if f else None)
        pendientes.append((f"abono:{a.id}", a.fecha, "cobro", f"Abono de {cliente} a la factura {f.numero_consecutivo if f else ''}",
                           [(cs("caja_bancos"), monto, 0, a.referencia), (cs("clientes"), 0, monto, cliente)]))
    sin_costo = _pendientes_inventario(db, emisor_id, desde, hasta, facturas, cs, pendientes)
    for ref, fecha, origen, descripcion, lineas in pendientes:
        if not origen or ref in hechos:
            continue
        crear_asiento(db, emisor_id, fecha, descripcion, _cuadrar(lineas, cs("otros_ingresos"), cs("otros_gastos")),
                      origen=origen, documento_ref=ref, quien=quien or "contabilización automática", confirmar=False)
        creados[origen] += 1
    db.commit()
    return {"creados": sum(creados.values()), "por_origen": dict(creados),
            "ya_estaban": len([p for p in pendientes if p[0] in hechos]),
            "productos_sin_costo": sin_costo}


# --- Costo de ventas desde el inventario ----------------------------------------------------------

def _valor(m: MovimientoInventario) -> Decimal:
    """Valor del movimiento al costo promedio de ese momento (positivo entra, negativo sale)."""
    return Decimal(m.cantidad) * Decimal(m.costo_unitario)


def _pendientes_inventario(db: Session, emisor_id: str, desde: date, hasta: date, facturas: list[Factura], cs,
                           pendientes: list) -> list[str]:
    """
    Agrega a `pendientes` los asientos del inventario del mes (costo promedio de cada movimiento):

    - Venta (factura, tiquete, exportación): Debe costo de ventas · Haber inventario.
    - Devolución (nota de crédito que regresa mercadería): al revés.
    - Compra registrada en el inventario (entrada con costo o factura electrónica de compra): la
      compra ya se contabilizó como gasto, así que se pasa de compras y gastos al inventario.
    - Salida o ajuste manual: la diferencia va al costo de ventas (mermas, faltantes o sobrantes).

    Devuelve los productos que se movieron sin costo (no se pueden valorar).
    """
    ids = [f.id for f in facturas]
    por_factura: dict[str, list[MovimientoInventario]] = defaultdict(list)
    sin_costo = set()
    if ids:
        for m in db.scalars(select(MovimientoInventario).where(MovimientoInventario.factura_id.in_(ids),
                                                                MovimientoInventario.tipo.in_(("venta", "devolucion", "compra")))):
            por_factura[m.factura_id].append(m)
    for f in facturas:
        movs = por_factura.get(f.id, [])
        for m in movs:
            if m.costo_unitario is None:
                sin_costo.add(m.producto.descripcion if m.producto else m.producto_id)
        valorados = [m for m in movs if m.costo_unitario is not None]
        salida = -sum((_valor(m) for m in valorados if m.tipo in ("venta", "devolucion")), CERO)   # >0 = costo
        entrada = sum((_valor(m) for m in valorados if m.tipo == "compra"), CERO)
        fecha = fecha_cr(f.fecha_emision)
        if q(salida):
            lineas = [(cs("costo_ventas"), salida, 0, None), (cs("inventario"), 0, salida, None)] if salida > 0 else \
                [(cs("inventario"), -salida, 0, None), (cs("costo_ventas"), 0, -salida, "Devolución")]
            pendientes.append((f"costo:{f.id}", fecha, "costo", f"Costo de ventas {f.numero_consecutivo}", lineas))
        if q(entrada):
            pendientes.append((f"inventario-compra:{f.id}", fecha, "inventario", f"Mercadería al inventario {f.numero_consecutivo}",
                               [(cs("inventario"), entrada, 0, None), (cs("compras_gastos"), 0, entrada, None)]))

    inicio = datetime.combine(desde, time.min, tzinfo=zona_cr())
    fin = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona_cr())
    for m in db.scalars(select(MovimientoInventario).where(
            MovimientoInventario.emisor_id == emisor_id, MovimientoInventario.factura_id.is_(None),
            MovimientoInventario.tipo.in_(("entrada", "salida", "ajuste")),
            MovimientoInventario.fecha >= inicio, MovimientoInventario.fecha < fin).order_by(MovimientoInventario.fecha)):
        if m.costo_unitario is None:
            sin_costo.add(m.producto.descripcion if m.producto else m.producto_id)
            continue
        valor = _valor(m)
        if not q(valor):
            continue
        producto = m.producto.descripcion if m.producto else ""
        if m.tipo == "entrada" and (m.nota or "").startswith("Existencia inicial"):
            # Mercadería que ya tenía al empezar: no es una compra del período
            contra, texto = cs("utilidades_acumuladas"), f"Inventario inicial: {producto}"
        elif m.tipo == "entrada":
            contra, texto = cs("compras_gastos"), f"Entrada al inventario: {producto}"
        else:
            contra, texto = cs("costo_ventas"), f"{'Ajuste' if m.tipo == 'ajuste' else 'Salida'} de inventario: {producto}"
        lineas = [(cs("inventario"), valor, 0, m.nota), (contra, 0, valor, None)] if valor > 0 else \
            [(contra, -valor, 0, m.nota), (cs("inventario"), 0, -valor, None)]
        pendientes.append((f"inventario:{m.id}", fecha_cr(m.fecha), "inventario", texto[:300], lineas))
    return sorted(str(x) for x in sin_costo)


# --- Asiento de cierre anual ---------------------------------------------------------------------

def propuesta_cierre(db: Session, emisor_id: str, anio: int) -> dict:
    """
    Asiento que cierra las cuentas de resultados del año (ingresos, costos y gastos) contra
    utilidades acumuladas. Se calcula sin contar un cierre ya hecho, así que sirve para ver
    el asiento antes de registrarlo y como archivo para copiarlo a mano.
    """
    fecha = date(anio, 12, 31)
    lista = [c for c in cuentas(db, emisor_id) if c.tipo in ("ingreso", "costo", "gasto") and c.acepta_movimientos]
    movs = _movimientos(db, emisor_id, date(anio, 1, 1), fecha, excluir_origen="cierre")
    lineas = []
    utilidad = CERO
    for c in ordenar(lista):
        saldo = q(_saldo(c.tipo, *movs.get(c.id, (CERO, CERO))))
        if not saldo:
            continue
        # Se deja la cuenta en cero: ingresos (acreedores) al debe; costos y gastos (deudores) al haber
        if c.tipo == "ingreso":
            utilidad += saldo
            lineas.append({"cuenta_id": c.id, "codigo": c.codigo, "nombre": c.nombre,
                           "debe": max(saldo, CERO), "haber": max(-saldo, CERO)})
        else:
            utilidad -= saldo
            lineas.append({"cuenta_id": c.id, "codigo": c.codigo, "nombre": c.nombre,
                           "debe": max(-saldo, CERO), "haber": max(saldo, CERO)})
    acumuladas = None
    try:
        acumuladas = cuenta_sistema(db, emisor_id, "utilidades_acumuladas")
    except ContabilidadError:
        pass
    if lineas and acumuladas is not None and q(utilidad):
        lineas.append({"cuenta_id": acumuladas.id, "codigo": acumuladas.codigo, "nombre": acumuladas.nombre,
                       "debe": max(-utilidad, CERO), "haber": max(utilidad, CERO),
                       "detalle": "Utilidad del año" if utilidad > 0 else "Pérdida del año"})
    existente = db.scalar(select(Asiento).where(Asiento.emisor_id == emisor_id, Asiento.documento_ref == f"cierre:{anio}",
                                                Asiento.anulado.is_(False)))
    return {
        "anio": anio, "fecha": fecha.isoformat(), "descripcion": f"Cierre del año {anio}: traslado del resultado a utilidades acumuladas",
        "lineas": [{**ln, "debe": str(q(ln["debe"])), "haber": str(q(ln["haber"]))} for ln in lineas],
        "total": str(q(sum((ln["debe"] for ln in lineas), CERO))), "utilidad": str(q(utilidad)),
        "falta_cuenta": acumuladas is None,
        "registrado": {"id": existente.id, "numero": existente.numero} if existente else None,
    }


def registrar_cierre(db: Session, emisor_id: str, anio: int, quien: str | None = None) -> Asiento:
    p = propuesta_cierre(db, emisor_id, anio)
    if p["registrado"]:
        raise ContabilidadError(f"El año {anio} ya tiene su asiento de cierre (N.º {p['registrado']['numero']}). "
                                "Anúlelo si necesita rehacerlo.", 409)
    if p["falta_cuenta"]:
        raise ContabilidadError("Falta la cuenta de utilidades acumuladas en el catálogo")
    if len(p["lineas"]) < 2:
        raise ContabilidadError(f"El año {anio} no tiene movimientos de ingresos, costos ni gastos que cerrar")
    return crear_asiento(db, emisor_id, date(anio, 12, 31), p["descripcion"],
                         [{"cuenta_id": ln["cuenta_id"], "debe": ln["debe"], "haber": ln["haber"],
                           "detalle": ln.get("detalle")} for ln in p["lineas"]],
                         origen="cierre", documento_ref=f"cierre:{anio}", quien=quien)


# --- Reportes ------------------------------------------------------------------------------------

def _movimientos(db: Session, emisor_id: str, desde: date | None, hasta: date | None,
                 excluir_origen: str | None = None) -> dict[str, tuple[Decimal, Decimal]]:
    """{cuenta_id: (debe, haber)} de los asientos vigentes entre las fechas (incluidas)."""
    query = (select(AsientoLinea.cuenta_id, func.coalesce(func.sum(AsientoLinea.debe), 0),
                    func.coalesce(func.sum(AsientoLinea.haber), 0))
             .join(Asiento, Asiento.id == AsientoLinea.asiento_id)
             .where(Asiento.emisor_id == emisor_id, Asiento.anulado.is_(False)).group_by(AsientoLinea.cuenta_id))
    if desde:
        query = query.where(Asiento.fecha >= desde)
    if hasta:
        query = query.where(Asiento.fecha <= hasta)
    if excluir_origen:
        query = query.where(Asiento.origen != excluir_origen)
    return {cid: (Decimal(d), Decimal(h)) for cid, d, h in db.execute(query)}


def _saldo(tipo: str, debe: Decimal, haber: Decimal) -> Decimal:
    return debe - haber if tipo in DEUDORAS else haber - debe


def _arbol(lista: list[CuentaContable], valores: dict[str, Decimal]) -> list[dict]:
    """Suma los saldos de las cuentas de movimiento hacia sus grupos (por el código)."""
    por_codigo = {c.codigo: c for c in lista}
    totales: dict[str, Decimal] = defaultdict(Decimal)
    for c in lista:
        v = valores.get(c.id, CERO)
        if not v:
            continue
        codigo = c.codigo
        while codigo:
            totales[codigo] += v
            codigo = padre(codigo)
            if codigo and codigo not in por_codigo:
                break
    return [{"cuenta_id": c.id, "codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo, "nivel": c.codigo.count("."),
             "grupo": not c.acepta_movimientos, "saldo": str(q(totales[c.codigo]))}
            for c in ordenar(lista) if totales.get(c.codigo)]


def balance_comprobacion(db: Session, emisor_id: str, desde: date, hasta: date) -> dict:
    lista = cuentas(db, emisor_id)
    previo = _movimientos(db, emisor_id, None, desde - timedelta(days=1))
    periodo = _movimientos(db, emisor_id, desde, hasta)
    filas = []
    sumas = defaultdict(Decimal)
    for c in ordenar(lista):
        if not c.acepta_movimientos:
            continue
        d0, h0 = previo.get(c.id, (CERO, CERO))
        d, h = periodo.get(c.id, (CERO, CERO))
        inicial, final = _saldo(c.tipo, d0, h0), _saldo(c.tipo, d0 + d, h0 + h)
        if not (inicial or d or h):
            continue
        deudor = (d0 + d) - (h0 + h)
        filas.append({"cuenta_id": c.id, "codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo,
                      "saldo_inicial": str(q(inicial)), "debe": str(q(d)), "haber": str(q(h)), "saldo_final": str(q(final)),
                      "saldo_deudor": str(q(max(deudor, CERO))), "saldo_acreedor": str(q(max(-deudor, CERO)))})
        sumas["debe"] += d
        sumas["haber"] += h
        sumas["deudor"] += max(deudor, CERO)
        sumas["acreedor"] += max(-deudor, CERO)
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "cuentas": filas,
            "totales": {k: str(q(v)) for k, v in sumas.items()},
            "cuadra": q(sumas["debe"]) == q(sumas["haber"]) and q(sumas["deudor"]) == q(sumas["acreedor"])}


def estado_resultados(db: Session, emisor_id: str, desde: date, hasta: date) -> dict:
    lista = [c for c in cuentas(db, emisor_id) if c.tipo in ("ingreso", "costo", "gasto")]
    # El asiento de cierre deja estas cuentas en cero: no se cuenta para mostrar el resultado del período
    movs = _movimientos(db, emisor_id, desde, hasta, excluir_origen="cierre")
    valores = {c.id: _saldo(c.tipo, *movs.get(c.id, (CERO, CERO))) for c in lista}
    total = {t: sum((valores[c.id] for c in lista if c.tipo == t), CERO) for t in ("ingreso", "costo", "gasto")}
    utilidad_bruta = total["ingreso"] - total["costo"]
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "cuentas": _arbol(lista, valores),
            "ingresos": str(q(total["ingreso"])), "costos": str(q(total["costo"])), "gastos": str(q(total["gasto"])),
            "utilidad_bruta": str(q(utilidad_bruta)), "utilidad_neta": str(q(utilidad_bruta - total["gasto"]))}


def balance_general(db: Session, emisor_id: str, fecha: date) -> dict:
    lista = cuentas(db, emisor_id)
    movs = _movimientos(db, emisor_id, None, fecha)
    valores = {c.id: _saldo(c.tipo, *movs.get(c.id, (CERO, CERO))) for c in lista}
    suma = lambda tipos: sum((valores[c.id] for c in lista if c.tipo in tipos), CERO)   # noqa: E731
    resultado = suma(("ingreso",)) - suma(("costo", "gasto"))
    activo, pasivo, patrimonio = suma(("activo",)), suma(("pasivo",)), suma(("patrimonio",))
    return {"fecha": fecha.isoformat(),
            "activo": _arbol([c for c in lista if c.tipo == "activo"], valores),
            "pasivo": _arbol([c for c in lista if c.tipo == "pasivo"], valores),
            "patrimonio": _arbol([c for c in lista if c.tipo == "patrimonio"], valores),
            "total_activo": str(q(activo)), "total_pasivo": str(q(pasivo)), "total_patrimonio": str(q(patrimonio)),
            "resultado_acumulado": str(q(resultado)),
            "total_pasivo_patrimonio": str(q(pasivo + patrimonio + resultado)),
            "cuadra": q(activo) == q(pasivo + patrimonio + resultado)}


def mayor(db: Session, emisor_id: str, cuenta: CuentaContable, desde: date, hasta: date) -> dict:
    previo = _movimientos(db, emisor_id, None, desde - timedelta(days=1)).get(cuenta.id, (CERO, CERO))
    saldo = _saldo(cuenta.tipo, *previo)
    inicial = saldo
    filas = []
    query = (select(AsientoLinea, Asiento).join(Asiento, Asiento.id == AsientoLinea.asiento_id)
             .where(AsientoLinea.cuenta_id == cuenta.id, Asiento.anulado.is_(False), Asiento.fecha >= desde,
                    Asiento.fecha <= hasta).order_by(Asiento.fecha, Asiento.numero))
    for ln, a in db.execute(query):
        saldo += _saldo(cuenta.tipo, ln.debe, ln.haber)
        filas.append({"asiento_id": a.id, "numero": a.numero, "fecha": a.fecha.isoformat(), "descripcion": a.descripcion,
                      "detalle": ln.detalle, "debe": str(ln.debe), "haber": str(ln.haber), "saldo": str(q(saldo))})
    return {"cuenta": {"id": cuenta.id, "codigo": cuenta.codigo, "nombre": cuenta.nombre, "tipo": cuenta.tipo},
            "desde": desde.isoformat(), "hasta": hasta.isoformat(), "saldo_inicial": str(q(inicial)),
            "saldo_final": str(q(saldo)), "movimientos": filas}


def asiento_a_dict(a: Asiento) -> dict:
    return {
        "id": a.id, "numero": a.numero, "fecha": a.fecha.isoformat(), "descripcion": a.descripcion, "origen": a.origen,
        "documento_ref": a.documento_ref, "editado": a.editado, "anulado": a.anulado, "creado_por": a.creado_por,
        "total": str(sum((ln.debe for ln in a.lineas), CERO)),
        "lineas": [{"cuenta_id": ln.cuenta_id, "codigo": ln.cuenta.codigo, "nombre": ln.cuenta.nombre,
                    "debe": str(ln.debe), "haber": str(ln.haber), "detalle": ln.detalle} for ln in a.lineas],
    }


def diario(db: Session, emisor_id: str, desde: date, hasta: date, texto: str | None = None) -> list[dict]:
    query = (select(Asiento).options(selectinload(Asiento.lineas).selectinload(AsientoLinea.cuenta))
             .where(Asiento.emisor_id == emisor_id, Asiento.fecha >= desde, Asiento.fecha <= hasta)
             .order_by(Asiento.fecha, Asiento.numero))
    if texto:
        query = query.where(or_(Asiento.descripcion.ilike(f"%{texto}%"), Asiento.numero == (int(texto) if texto.isdigit() else -1)))
    return [asiento_a_dict(a) for a in db.scalars(query)]
