"""
Mensualidades: cada servicio se cobra por aparte.

- Documentos: paquetes prepago (saldo.py / compras.py), se recargan cuando quiera.
- Sistema en línea (empresa), contabilidad de la empresa (cuando el dueño la lleva él mismo)
  y cuenta de contador: mensualidad.

Al pedir un servicio se le muestra el precio y queda activo de inmediato (la primera vez,
con los días de prueba gratis). El día 1 de cada mes se emite UNA factura por cliente con
los servicios del mes anterior, proporcional a los días que los tuvo. Tiene
`dias_para_pagar` días; si no paga, las mensualidades se suspenden hasta que pague.
Los documentos no se suspenden: se pagaron por adelantado.

Un servicio sin precio configurado no se cobra (queda libre).
"""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import CobroMensual, Contratacion, Emisor, Usuario, utcnow
from api.services import administracion
from api.services.fechas import ahora_cr
from config.settings import get_settings

SERVICIOS = {
    "facturacion_web": {"nombre": "Sistema en línea", "de": "empresa", "precio": "precio_web_mensual",
                        "detalle": "Facturar desde el navegador: punto de venta, clientes, productos, inventario y cobros."},
    "contabilidad": {"nombre": "Contabilidad de la empresa", "de": "empresa", "precio": "precio_contabilidad_mensual",
                     "detalle": "Asientos automáticos, estados financieros, IVA y D-104, llevados por el dueño."},
    "contador": {"nombre": "Cuenta de contador", "de": "usuario", "precio": "precio_contador_mensual",
                 "detalle": "La contabilidad de todas las empresas que usted lleva."},
}
CENTIMO = Decimal("0.01")


class MensualidadError(Exception):
    def __init__(self, detalle: str, status_code: int = 422):
        super().__init__(detalle)
        self.detalle = detalle
        self.status_code = status_code


def clave_cliente(emisor_id: str | None = None, usuario_id: str | None = None) -> str:
    return f"e:{emisor_id}" if emisor_id else f"u:{usuario_id}"


def hoy() -> date:
    return ahora_cr().date()


def precio(db: Session, servicio: str) -> Decimal | None:
    valor = getattr(administracion.ajustes(db), SERVICIOS[servicio]["precio"])
    return Decimal(valor) if valor else None


def se_cobra(db: Session, servicio: str) -> bool:
    return get_settings().CONTROL_SUSCRIPCIONES and precio(db, servicio) is not None


def contrato(db: Session, cliente: str, servicio: str) -> Contratacion | None:
    """Contratación vigente hoy (o None)."""
    d = hoy()
    return db.scalar(select(Contratacion).where(
        Contratacion.cliente == cliente, Contratacion.servicio == servicio, Contratacion.desde <= d,
        (Contratacion.hasta.is_(None)) | (Contratacion.hasta >= d)).order_by(Contratacion.desde.desc()))


def moroso(db: Session, cliente: str) -> CobroMensual | None:
    """Factura mensual vencida sin pagar (si reportó el pago, no se suspende mientras se confirma)."""
    return db.scalar(select(CobroMensual).where(CobroMensual.cliente == cliente, CobroMensual.estado == "PENDIENTE",
                                                CobroMensual.vence < hoy()).order_by(CobroMensual.vence))


def activo(db: Session, servicio: str, *, emisor_id: str | None = None, usuario_id: str | None = None) -> bool:
    """El cliente puede usar el servicio: no se cobra, o lo tiene contratado y está al día."""
    if not se_cobra(db, servicio):
        return True
    cliente = clave_cliente(emisor_id, usuario_id)
    return contrato(db, cliente, servicio) is not None and moroso(db, cliente) is None


def motivo(db: Session, servicio: str, *, emisor_id: str | None = None, usuario_id: str | None = None) -> str:
    cliente = clave_cliente(emisor_id, usuario_id)
    deuda = moroso(db, cliente)
    if deuda:
        return (f"Suspendido por falta de pago: la factura de {deuda.periodo:%m/%Y} venció el {deuda.vence:%d/%m/%Y}. "
                "Pague y repórtelo en Mis servicios.")
    p = precio(db, servicio)
    a = administracion.ajustes(db)
    return f"Active «{SERVICIOS[servicio]['nombre']}» en Mis servicios ({a.moneda_web} {p:,.2f} por mes)."


def contratar(db: Session, servicio: str, *, emisor: Emisor | None = None, usuario: Usuario | None = None,
              quien: str | None = None) -> Contratacion:
    if servicio not in SERVICIOS:
        raise MensualidadError("Servicio desconocido")
    if (SERVICIOS[servicio]["de"] == "empresa") != (emisor is not None):
        raise MensualidadError("Ese servicio no aplica a esta cuenta", 403)
    p = precio(db, servicio)
    if p is None:
        raise MensualidadError("Ese servicio no tiene precio todavía: ya puede usarlo sin costo")
    cliente = clave_cliente(emisor.id if emisor else None, usuario.id if usuario else None)
    if contrato(db, cliente, servicio):
        raise MensualidadError("Ya tiene ese servicio activo", 409)
    a = administracion.ajustes(db)
    d = hoy()
    primera_vez = db.scalar(select(Contratacion.id).where(Contratacion.cliente == cliente,
                                                          Contratacion.servicio == servicio)) is None
    gratis = d + timedelta(days=a.prueba_dias - 1) if primera_vez and a.prueba_dias > 0 else None
    c = Contratacion(cliente=cliente, emisor_id=emisor.id if emisor else None, usuario_id=usuario.id if usuario else None,
                     servicio=servicio, precio=p, moneda=a.moneda_web, desde=d, gratis_hasta=gratis, creado_por=quien)
    db.add(c)
    db.commit()
    return c


def cancelar(db: Session, c: Contratacion) -> None:
    """Se usa hasta hoy; el último mes se cobra proporcional a los días."""
    c.hasta = hoy()
    db.commit()


def a_dict(c: Contratacion | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "servicio": c.servicio, "precio": str(c.precio), "moneda": c.moneda, "desde": c.desde.isoformat(),
            "hasta": c.hasta.isoformat() if c.hasta else None,
            "gratis_hasta": c.gratis_hasta.isoformat() if c.gratis_hasta else None}


def servicios_de(db: Session, *, emisor_id: str | None = None, usuario_id: str | None = None) -> list[dict]:
    """Los servicios que le aplican a la cuenta, con su precio y si los tiene activos."""
    cliente = clave_cliente(emisor_id, usuario_id)
    de = "empresa" if emisor_id else "usuario"
    deuda = moroso(db, cliente)
    a = administracion.ajustes(db)
    salida = []
    for clave, s in SERVICIOS.items():
        if s["de"] != de:
            continue
        p = precio(db, clave)
        c = contrato(db, cliente, clave)
        esta_activo = activo(db, clave, emisor_id=emisor_id, usuario_id=usuario_id)
        pagado_hasta = None
        if clave == "facturacion_web" and c is None:
            # Meses que vendió el administrador antes (o regalía): sigue activo sin mensualidad
            from api.services import suscripciones
            est = suscripciones.estado(db, db.get(Emisor, emisor_id), clave)
            esta_activo = est["activo"]
            pagado_hasta = "regalia" if est["regalia"] else (est["vence"].date().isoformat() if est["vence"] else None)
        salida.append({"servicio": clave, "nombre": s["nombre"], "detalle": s["detalle"],
                       "precio": str(p) if p is not None else None, "moneda": a.moneda_web,
                       "se_cobra": se_cobra(db, clave), "contrato": a_dict(c), "activo": esta_activo,
                       "pagado_hasta": pagado_hasta if esta_activo else None, "suspendido": bool(c and deuda)})
    return salida


# --- Factura mensual ------------------------------------------------------------------------

def _rango_mes(periodo: date) -> tuple[date, date]:
    return periodo, periodo.replace(day=calendar.monthrange(periodo.year, periodo.month)[1])


def lineas_del_mes(db: Session, cliente: str, periodo: date) -> list[dict]:
    """Cada servicio del mes, proporcional a los días cobrables (sin la prueba gratis)."""
    inicio, fin = _rango_mes(periodo)
    dias_mes = (fin - inicio).days + 1
    lineas = []
    for c in db.scalars(select(Contratacion).where(Contratacion.cliente == cliente, Contratacion.desde <= fin,
                                                   (Contratacion.hasta.is_(None)) | (Contratacion.hasta >= inicio))
                        .order_by(Contratacion.desde)):
        desde = max(inicio, c.desde, (c.gratis_hasta + timedelta(days=1)) if c.gratis_hasta else inicio)
        hasta = min(fin, c.hasta or fin)
        dias = (hasta - desde).days + 1
        if dias <= 0:
            continue
        monto = (Decimal(c.precio) * dias / dias_mes).quantize(CENTIMO, ROUND_HALF_UP)
        nombre = SERVICIOS[c.servicio]["nombre"]
        concepto = f"{nombre} {periodo:%m/%Y}" + ("" if dias == dias_mes else f" ({dias} de {dias_mes} días)")
        lineas.append({"servicio": c.servicio, "concepto": concepto, "dias": dias, "monto": str(monto), "moneda": c.moneda})
    return lineas


def clientes_con_contratos(db: Session, periodo: date) -> list[Contratacion]:
    inicio, fin = _rango_mes(periodo)
    return list(db.scalars(select(Contratacion).where(Contratacion.desde <= fin,
                                                      (Contratacion.hasta.is_(None)) | (Contratacion.hasta >= inicio))))


def generar(db: Session, periodo: date) -> list[CobroMensual]:
    """Crea la factura mensual de cada cliente para el mes indicado (no duplica)."""
    a = administracion.ajustes(db)
    creados = []
    vistos = set()
    for c in clientes_con_contratos(db, periodo):
        if c.cliente in vistos:
            continue
        vistos.add(c.cliente)
        if db.scalar(select(CobroMensual.id).where(CobroMensual.cliente == c.cliente, CobroMensual.periodo == periodo)):
            continue
        lineas = lineas_del_mes(db, c.cliente, periodo)
        total = sum((Decimal(x["monto"]) for x in lineas), Decimal("0"))
        if total <= 0:
            continue
        cobro = CobroMensual(cliente=c.cliente, emisor_id=c.emisor_id, usuario_id=c.usuario_id, periodo=periodo,
                             lineas=lineas, total=total, moneda=lineas[0]["moneda"], emitido=hoy(),
                             vence=hoy() + timedelta(days=a.dias_para_pagar))
        db.add(cobro)
        db.commit()
        creados.append(cobro)
    return creados


def a_dict_cobro(c: CobroMensual, nombre: str | None = None) -> dict:
    return {"id": c.id, "cliente": nombre, "periodo": c.periodo.isoformat(), "lineas": c.lineas, "total": str(c.total),
            "moneda": c.moneda, "emitido": c.emitido.isoformat(), "vence": c.vence.isoformat(), "estado": c.estado,
            "vencido": c.estado == "PENDIENTE" and c.vence < hoy(), "referencia_pago": c.referencia_pago,
            "factura_id": c.factura_id, "comprobante_error": c.comprobante_error}


def reportar_pago(db: Session, c: CobroMensual, referencia: str) -> None:
    if c.estado not in ("PENDIENTE", "REPORTADO"):
        raise MensualidadError("Esa factura ya no tiene pago pendiente", 409)
    c.estado, c.referencia_pago, c.reportado_en = "REPORTADO", referencia.strip()[:100], utcnow()
    db.commit()


def confirmar_pago(db: Session, c: CobroMensual, quien: str, referencia: str | None = None) -> None:
    if c.estado in ("PAGADO", "ANULADO"):
        raise MensualidadError("Esa factura ya está pagada o anulada", 409)
    c.estado, c.pagado_en, c.confirmado_por = "PAGADO", utcnow(), quien
    if referencia:
        c.referencia_pago = referencia.strip()[:100]
    # La factura mensual es a crédito: el pago queda como abono en la cuenta por cobrar de la plataforma
    if c.factura_id:
        from api.models.database import Abono, EstadoFactura, Factura
        from api.services import cobros
        f = db.get(Factura, c.factura_id)
        if f is not None and f.estado != EstadoFactura.RECHAZADO:
            pendiente = cobros.saldo_factura(db, f)
            if pendiente > 0:
                db.add(Abono(emisor_id=f.emisor_id, factura_id=f.id, fecha=hoy(), monto=pendiente, medio_pago="04",
                             referencia=c.referencia_pago, nota="Mensualidad pagada", registrado_por=quien))
    db.commit()


def emitir_comprobante(db: Session, cobro: CobroMensual):
    """
    Factura electrónica de la mensualidad desde la empresa de la plataforma, a crédito con el
    plazo para pagar. Al contador (persona sin cédula registrada) se le emite tiquete a su nombre.
    Devuelve la factura (o None y deja el motivo en comprobante_error).
    """
    from api.models.database import Factura
    from api.models.schemas import TARIFAS_IVA, FacturaRequest
    from api.services import emision

    a = administracion.ajustes(db)
    if cobro.factura_id:
        return db.get(Factura, cobro.factura_id)
    if not a.emisor_ventas_id or not a.codigo_cabys:
        cobro.comprobante_error = "Configure en Ventas → Facturación y avisos qué empresa emite los comprobantes."
        db.commit()
        return None
    vendedor = db.get(Emisor, a.emisor_ventas_id)
    tarifa = TARIFAS_IVA[a.codigo_tarifa_iva]
    productos = []
    for ln in cobro.lineas:
        monto = Decimal(ln["monto"])
        if a.precio_incluye_iva:
            monto = monto / (1 + tarifa / 100)
        productos.append({"codigo_cabys": a.codigo_cabys, "descripcion": ln["concepto"][:200], "cantidad": "1",
                          "unidad_medida": "Os", "precio_unitario": str(monto.quantize(Decimal("0.00001"))),
                          "codigo_tarifa_iva": a.codigo_tarifa_iva})
    datos = {"referencia_externa": f"mensual-{cobro.id}", "condicion_venta": "02", "plazo_credito": a.dias_para_pagar,
             "moneda": cobro.moneda, "medios_pago": [{"tipo": a.medio_pago}], "productos": productos,
             "notas": f"Servicios de {cobro.periodo:%m/%Y}. Vence el {cobro.vence:%d/%m/%Y}."}
    if cobro.emisor_id:
        e = db.get(Emisor, cobro.emisor_id)
        datos.update(tipo_documento=a.tipo_comprobante, receptor={
            "nombre": e.nombre[:100], "tipo_identificacion": e.tipo_identificacion,
            "numero_identificacion": e.numero_identificacion, "correo": e.correo})
        if a.tipo_comprobante == "01" and e.codigo_actividad:
            datos["codigo_actividad_receptor"] = e.codigo_actividad
    else:
        u = db.get(Usuario, cobro.usuario_id)
        datos.update(tipo_documento="04", receptor={"nombre": u.nombre[:100], "correo": u.email})
    try:
        factura, _ = emision.emitir(db, vendedor, FacturaRequest.model_validate(datos))
    except (emision.EmisionError, ValueError) as exc:
        db.rollback()
        cobro = db.get(CobroMensual, cobro.id)
        cobro.comprobante_error = str(getattr(exc, "detail", exc))[:1000]
        db.commit()
        return None
    cobro.factura_id, cobro.comprobante_error = factura.id, None
    db.commit()
    return factura


def nombre_cliente(db: Session, c) -> str:
    if c.emisor_id:
        e = db.get(Emisor, c.emisor_id)
        return f"{e.nombre} · {e.numero_identificacion}" if e else "Empresa"
    u = db.get(Usuario, c.usuario_id)
    return f"{u.nombre} · {u.email} (contador)" if u else "Contador"


def correo_cliente(db: Session, c) -> str | None:
    if c.emisor_id:
        e = db.get(Emisor, c.emisor_id)
        return e.correo if e else None
    u = db.get(Usuario, c.usuario_id)
    return u.email if u else None
