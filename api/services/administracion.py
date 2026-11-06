"""
Administración de la plataforma: comprobante de cada venta a las empresas
cliente, diagnóstico de problemas por empresa y tablero de ventas y vencimientos.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.models.database import (
    AjustesVentas, BuzonCorreo, Consumo, DocumentoRecibido, Emisor, EstadoFactura, Factura, FacturaEvento,
    Paquete, Plan, Suscripcion, utcnow,
)
from api.models.schemas import TARIFAS_IVA, FacturaRequest
from api.services import emision, saldo, suscripciones
from api.services.fechas import zona_cr
from api.services.reportes import rango_mes
from config.settings import get_settings

logger = logging.getLogger(__name__)

# Caché del tablero y los diagnósticos del administrador (ver routes/administracion.py)
CACHE_TABLERO_SEGUNDOS = 60
CLAVES_CACHE_ADMIN = ("admin:tablero", "admin:diagnosticos")

EN_PROCESO = (EstadoFactura.PENDIENTE, EstadoFactura.ENVIADO, EstadoFactura.ERROR_COMUNICACION, EstadoFactura.CONTINGENCIA)
DIAS_RECHAZOS = 7
MINUTOS_SIN_CONFIRMAR = 30
DIAS_POR_VENCER = 15


def ajustes(db: Session) -> AjustesVentas:
    a = db.get(AjustesVentas, 1)
    if a is None:
        a = AjustesVentas(id=1, codigo_tarifa_iva="08", precio_incluye_iva=True, tipo_comprobante="01", medio_pago="04")
        db.add(a)
        db.flush()
    return a


def ajustes_a_dict(a: AjustesVentas, db: Session) -> dict:
    emisor = db.get(Emisor, a.emisor_ventas_id) if a.emisor_ventas_id else None
    return {
        "emisor_ventas_id": a.emisor_ventas_id, "emisor_ventas": emisor.nombre if emisor else None,
        "codigo_cabys": a.codigo_cabys, "codigo_tarifa_iva": a.codigo_tarifa_iva,
        "precio_incluye_iva": a.precio_incluye_iva, "tipo_comprobante": a.tipo_comprobante, "medio_pago": a.medio_pago,
        "instrucciones_pago": a.instrucciones_pago, "contacto_ventas": a.contacto_ventas, "correo_avisos": a.correo_avisos,
    }


def _fecha(dt) -> str:
    return dt.astimezone(zona_cr()).strftime("%d/%m/%Y")


# --- Comprobante de la venta ------------------------------------------------------

def descripcion_venta(venta: Paquete | Suscripcion) -> str:
    if isinstance(venta, Paquete):
        return f"{venta.nombre}: {venta.documentos:,} documentos electrónicos".replace(",", ".")[:200]
    nombre = suscripciones.SERVICIOS.get(venta.servicio, venta.servicio)
    return (f"{nombre}: {venta.meses} mes(es), del {_fecha(venta.desde)} al {_fecha(venta.hasta)}")[:200]


def datos_comprobante(a: AjustesVentas, venta: Paquete | Suscripcion, comprador: Emisor, tipo: str,
                      medio_pago: str, rechazado: Factura | None = None) -> FacturaRequest:
    """
    Comprobante de una venta. Si sustituye a uno que Hacienda rechazó, lo cita con el
    código 16 (Anexos 4.4, nota 9) y usa otra referencia_externa para no devolver el rechazado.
    """
    tarifa = TARIFAS_IVA[a.codigo_tarifa_iva]
    precio = Decimal(venta.precio)
    if a.precio_incluye_iva:
        precio = precio / (1 + tarifa / 100)
    clase = "paquete" if isinstance(venta, Paquete) else "suscripcion"
    datos = {
        "tipo_documento": tipo,
        # Idempotente: reintentar no duplica. Al sustituir un rechazado se usa una referencia nueva.
        "referencia_externa": f"venta-{clase}-{venta.id}" + (f"-sust-{rechazado.numero_consecutivo}" if rechazado else ""),
        "condicion_venta": "01",
        "moneda": venta.moneda,
        "medios_pago": [{"tipo": medio_pago}],
        "receptor": {
            "nombre": comprador.nombre[:100], "tipo_identificacion": comprador.tipo_identificacion,
            "numero_identificacion": comprador.numero_identificacion, "correo": comprador.correo,
        },
        "productos": [{
            "codigo_cabys": a.codigo_cabys, "descripcion": descripcion_venta(venta), "cantidad": "1",
            "unidad_medida": "Os", "precio_unitario": str(precio.quantize(Decimal("0.00001"))),
            "codigo_tarifa_iva": a.codigo_tarifa_iva,
        }],
    }
    if tipo == "01" and comprador.codigo_actividad:
        datos["codigo_actividad_receptor"] = comprador.codigo_actividad
    if venta.referencia_pago:
        datos["notas"] = f"Pago: {venta.referencia_pago}"
    if rechazado:
        datos["referencia"] = {"tipo_documento": "10", "numero": rechazado.clave, "fecha_emision": rechazado.fecha_emision,
                               "codigo": "16", "razon": "Sustituye comprobante rechazado por Hacienda"}
    return FacturaRequest.model_validate(datos)


def emitir_comprobante(db: Session, venta: Paquete | Suscripcion, comprador: Emisor,
                       tipo: str | None = None, medio_pago: str | None = None) -> tuple[Factura | None, str | None]:
    """
    Emite el comprobante de la venta desde la empresa de la plataforma. Devuelve
    (factura, None) o (None, motivo). Una venta sin precio o con comprobante
    "ninguno" no se factura. El envío a Hacienda lo encola quien llama.
    """
    a = ajustes(db)
    # Una venta con comprobante vigente nunca se vuelve a facturar (aunque luego se cambie
    # la empresa que factura). Solo si Hacienda lo rechazó se emite uno que lo sustituye.
    anterior = db.get(Factura, venta.factura_id) if venta.factura_id else None
    if anterior is not None and anterior.estado != EstadoFactura.RECHAZADO:
        return anterior, None
    tipo = tipo or a.tipo_comprobante
    if tipo == "ninguno" or Decimal(venta.precio) <= 0:
        return None, None
    if not a.emisor_ventas_id or not a.codigo_cabys:
        motivo = "Configure en Ventas → Facturación de ventas qué empresa emite los comprobantes."
    elif a.emisor_ventas_id == comprador.id:
        return None, None
    else:
        vendedor = db.get(Emisor, a.emisor_ventas_id)
        try:
            datos = datos_comprobante(a, venta, comprador, tipo, medio_pago or a.medio_pago, rechazado=anterior)
            factura, _ = emision.emitir(db, vendedor, datos)
            venta.factura_id, venta.comprobante_error = factura.id, None
            db.commit()
            return factura, None
        except emision.EmisionError as exc:
            db.rollback()
            motivo = exc.detail
        except ValueError as exc:   # datos del comprador que Hacienda no acepta (p. ej. correo inválido)
            db.rollback()
            motivo = f"Datos del cliente incompletos para el comprobante: {exc}"
        except Exception:
            # La venta ya quedó registrada: un fallo inesperado no debe convertirse en un 500
            # (el administrador creería que la venta falló y la registraría dos veces)
            db.rollback()
            logger.exception("No se pudo emitir el comprobante de la venta %s", venta.id)
            motivo = "Error inesperado al emitir el comprobante. La venta quedó registrada; reintente desde Contabilidad."
    venta.comprobante_error = str(motivo)[:1000]
    db.commit()
    return None, venta.comprobante_error


def comprobante_por_anular(db: Session, venta: Paquete | Suscripcion) -> dict | None:
    """
    Venta anulada (p. ej. pago revertido) cuyo comprobante sigue aceptado por Hacienda
    y sin nota de crédito: seguiría sumando en la declaración de IVA de la plataforma.
    """
    f = db.get(Factura, venta.factura_id) if venta.factura_id else None
    if f is None or f.estado != EstadoFactura.ACEPTADO or emision.notas_activas(db, f):
        return None
    return {"factura_id": str(f.id), "emisor_id": str(f.emisor_id), "consecutivo": f.numero_consecutivo,
            "mensaje": f"El comprobante {f.numero_consecutivo} de esta venta sigue vigente ante Hacienda: "
                       "anúlelo con nota de crédito para que no quede en la declaración de IVA."}


def comprobante_a_dict(db: Session, venta: Paquete | Suscripcion) -> dict | None:
    if venta.factura_id:
        f = db.get(Factura, venta.factura_id)
        if f:
            return {"factura_id": str(f.id), "emisor_id": str(f.emisor_id), "tipo_documento": f.tipo_documento,
                    "consecutivo": f.numero_consecutivo, "estado": f.estado.value, "monto_total": f.monto_total}
    return {"error": venta.comprobante_error} if venta.comprobante_error else None


# --- Avisos comerciales al cliente -------------------------------------------------------

EVENTOS_COMPRA = ("saldo.bajo", "saldo.agotado", "paquete.por_vencer")


def texto_oferta(db: Session, evento: str) -> str:
    """Invitación a comprar que se agrega a los avisos de saldo y de servicios por vencer."""
    a = ajustes(db)
    partes = []
    if evento in EVENTOS_COMPRA:
        planes = db.scalars(select(Plan).where(Plan.activo.is_(True)).order_by(Plan.documentos)).all()
        if planes:
            lineas = [f"  • {p.nombre}: {p.documentos:,} documentos por {p.moneda} {p.precio:,.2f}".replace(",", " ")
                      + (f" (vigencia {p.dias_vigencia} días)" if p.dias_vigencia else "") for p in planes]
            partes.append("¿Desea adquirir más documentos? Estos son nuestros planes:\n" + "\n".join(lineas))
    else:
        partes.append("Renueve a tiempo para no interrumpir la facturación de su empresa.")
    if a.instrucciones_pago:
        partes.append("Formas de pago:\n" + a.instrucciones_pago.strip())
    if a.contacto_ventas:
        partes.append(f"Para comprar o resolver dudas: {a.contacto_ventas.strip()}")
    partes.append("Responda este correo con el comprobante de pago y le acreditamos el servicio en cuanto lo confirmemos.")
    return "\n\n".join(partes)


# --- Diagnóstico de cada empresa -----------------------------------------------------

def _alerta(nivel: str, titulo: str, detalle: str, seccion: str) -> dict:
    return {"nivel": nivel, "titulo": titulo, "detalle": detalle, "seccion": seccion}


def _resumir(texto: str | None, largo: int = 300) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= largo else texto[: largo - 1] + "…"


def diagnostico(db: Session, e: Emisor) -> list[dict]:
    """Problemas que impiden o pondrán en riesgo la facturación de la empresa, del más grave al más leve."""
    s = get_settings()
    ahora = utcnow()
    alertas = []
    if not e.activo:
        alertas.append(_alerta("info", "Empresa inactiva", "No puede emitir ni ingresar al panel.", "datos"))

    if e.cert_p12_cifrado is None:
        alertas.append(_alerta("error", "Sin certificado digital",
                               "No puede firmar comprobantes. Cargue el archivo .p12 y su PIN.", "hacienda"))
    elif e.cert_vence and e.cert_vence < ahora:
        alertas.append(_alerta("error", "Certificado vencido",
                               f"Venció el {_fecha(e.cert_vence)}. Hacienda rechaza lo que se firme con él: "
                               "el cliente debe generar uno nuevo en el ATV.", "hacienda"))
    elif e.cert_vence and e.cert_vence <= ahora + timedelta(days=s.DIAS_ALERTA_CERTIFICADO):
        alertas.append(_alerta("alerta", "Certificado por vencer",
                               f"Vence el {_fecha(e.cert_vence)} ({(e.cert_vence - ahora).days} días). "
                               "Pida al cliente renovarlo en el ATV y cárguelo aquí.", "hacienda"))
    if not (e.hacienda_usuario and e.hacienda_password_cifrado):
        alertas.append(_alerta("error", "Sin credenciales del API de Hacienda",
                               "Sin el usuario y la contraseña del API (ATV) no se pueden enviar comprobantes.", "hacienda"))

    if saldo.control_activo():
        disponible = saldo.disponible(db, e.id)
        if disponible <= 0:
            alertas.append(_alerta("error", "Sin documentos", "El saldo se agotó: no puede emitir. Véndale un paquete.", "compras"))
        elif disponible <= s.SALDO_ALERTA_DOCUMENTOS:
            alertas.append(_alerta("alerta", f"Quedan {disponible} documentos", "El saldo está por agotarse.", "compras"))
        limite = ahora + timedelta(days=s.DIAS_ALERTA_VENCIMIENTO_PAQUETE)
        por_vencer = [p for p in db.scalars(select(Paquete).where(
            Paquete.emisor_id == e.id, Paquete.anulado.is_(False), Paquete.vence.is_not(None),
            Paquete.vence > ahora, Paquete.vence <= limite)) if p.disponibles > 0]
        if por_vencer:
            primero = min(por_vencer, key=lambda p: p.vence)
            alertas.append(_alerta("alerta", f"{sum(p.disponibles for p in por_vencer)} documentos por vencer",
                                   f"Vencen sin usarse el {_fecha(primero.vence)}.", "compras"))

    for est in suscripciones.estados(db, e) if suscripciones.control_activo() else []:
        if est["estado"] == "VENCIDO":
            alertas.append(_alerta("error", f"{est['nombre']} vencido", "El servicio está suspendido hasta registrar el pago.", "compras"))
        elif est["estado"] == "EN_GRACIA":
            alertas.append(_alerta("alerta", f"{est['nombre']} en días de gracia",
                                   f"Venció el {_fecha(est['vence'])}; se suspende en {s.DIAS_GRACIA_SUSCRIPCION} días.", "compras"))
        elif est["estado"] == "POR_VENCER":
            alertas.append(_alerta("info", f"{est['nombre']} por vencer", f"Pagado hasta el {_fecha(est['vence'])}.", "compras"))

    rechazados = list(db.scalars(select(Factura).where(
        Factura.emisor_id == e.id, Factura.estado == EstadoFactura.RECHAZADO,
        Factura.updated_at >= ahora - timedelta(days=DIAS_RECHAZOS)).order_by(Factura.updated_at.desc())))
    if rechazados:
        ultimo = rechazados[0]
        alertas.append(_alerta("error", f"{len(rechazados)} comprobante(s) rechazado(s) por Hacienda",
                               f"Último ({ultimo.numero_consecutivo}): {_resumir(ultimo.mensaje_hacienda) or 'sin detalle'}",
                               "documentos"))

    atascados = list(db.scalars(select(Factura).where(
        Factura.emisor_id == e.id, Factura.estado.in_(EN_PROCESO),
        Factura.created_at <= ahora - timedelta(minutes=MINUTOS_SIN_CONFIRMAR)).order_by(Factura.created_at.desc())))
    if atascados:
        ultimo_evento = db.scalar(select(FacturaEvento).where(FacturaEvento.factura_id == atascados[0].id)
                                  .order_by(FacturaEvento.created_at.desc()).limit(1))
        causa = f"{ultimo_evento.evento}: {_resumir(ultimo_evento.detalle, 200)}" if ultimo_evento and ultimo_evento.detalle \
            else "Se reintenta solo cada 5 minutos."
        alertas.append(_alerta("alerta", f"{len(atascados)} comprobante(s) sin confirmar por Hacienda",
                               f"Último intento: {causa}", "documentos"))

    rechazos_receptor = db.scalar(select(func.count()).select_from(DocumentoRecibido).where(
        DocumentoRecibido.emisor_id == e.id, DocumentoRecibido.estado == EstadoFactura.RECHAZADO,
        DocumentoRecibido.updated_at >= ahora - timedelta(days=DIAS_RECHAZOS))) or 0
    if rechazos_receptor:
        alertas.append(_alerta("alerta", f"{rechazos_receptor} respuesta(s) a proveedores rechazada(s)",
                               "Hacienda rechazó mensajes de aceptación o rechazo de facturas recibidas.", "documentos"))

    buzon = db.scalar(select(BuzonCorreo).where(BuzonCorreo.emisor_id == e.id, BuzonCorreo.activo.is_(True)))
    if buzon and buzon.ultimo_error:
        alertas.append(_alerta("alerta", "No se puede leer el correo de facturas", _resumir(buzon.ultimo_error), "datos"))

    if e.ambiente == "stag" and e.activo:
        alertas.append(_alerta("info", "En ambiente de pruebas",
                               "Sus comprobantes no tienen validez fiscal. Páselo a Producción cuando esté listo.", "hacienda"))
    orden = {"error": 0, "alerta": 1, "info": 2}
    return sorted(alertas, key=lambda a: orden[a["nivel"]])


# --- Historial de compras --------------------------------------------------------------

def compras(db: Session, e: Emisor) -> list[dict]:
    """Paquetes y mensualidades comprados, del más reciente al más antiguo, con su comprobante."""
    filas = []
    for p in db.scalars(select(Paquete).where(Paquete.emisor_id == e.id)):
        filas.append({**saldo.paquete_a_dict(p), "clase": "paquete", "detalle": descripcion_venta(p),
                      "comprobante": comprobante_a_dict(db, p)})
    for sus in db.scalars(select(Suscripcion).where(Suscripcion.emisor_id == e.id)):
        filas.append({**suscripciones.a_dict(sus), "clase": "suscripcion", "detalle": descripcion_venta(sus),
                      "comprobante": comprobante_a_dict(db, sus)})
    return sorted(filas, key=lambda f: f["fecha"], reverse=True)


# --- Tablero ---------------------------------------------------------------------------

def _sumar(filas) -> dict[str, Decimal]:
    total: dict[str, Decimal] = {}
    for moneda, monto in filas:
        total[moneda] = total.get(moneda, Decimal("0")) + Decimal(monto)
    return total


def _ventas_entre(db: Session, desde, hasta) -> dict[str, Decimal]:
    paquetes = db.execute(select(Paquete.moneda, Paquete.precio).where(
        Paquete.anulado.is_(False), Paquete.created_at >= desde, Paquete.created_at < hasta)).all()
    servicios = db.execute(select(Suscripcion.moneda, Suscripcion.precio).where(
        Suscripcion.anulada.is_(False), Suscripcion.created_at >= desde, Suscripcion.created_at < hasta)).all()
    return _sumar([*paquetes, *servicios])


def tablero(db: Session) -> dict:
    s = get_settings()
    ahora = utcnow()
    hoy = ahora.astimezone(zona_cr())
    empresas = list(db.scalars(select(Emisor).order_by(Emisor.nombre)))
    nombres = {e.id: e.nombre for e in empresas}
    control = saldo.control_activo()
    saldos = saldo.disponibles_por_emisor(db, [e.id for e in empresas]) if control else {}

    # Ventas de los últimos 6 meses (incluido el actual)
    meses = []
    anio, mes = hoy.year, hoy.month
    for _ in range(6):
        desde, hasta = rango_mes(anio, mes)
        meses.append({"periodo": f"{anio:04d}-{mes:02d}", **{k: str(v) for k, v in _ventas_entre(db, desde, hasta).items()}})
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    inicio_mes, fin_mes = rango_mes(hoy.year, hoy.month)
    documentos_vendidos = db.scalar(select(func.coalesce(func.sum(Paquete.documentos), 0)).where(   # sin cortesías
        Paquete.anulado.is_(False), Paquete.precio > 0, Paquete.created_at >= inicio_mes, Paquete.created_at < fin_mes)) or 0
    documentos_consumidos = db.scalar(select(func.count()).select_from(Consumo).where(
        Consumo.created_at >= inicio_mes, Consumo.created_at < fin_mes)) or 0

    # Lo que vence pronto: paquetes con saldo, mensualidades, certificados y saldo bajo
    limite = ahora + timedelta(days=DIAS_POR_VENCER)
    vencimientos = []
    for p in db.scalars(select(Paquete).where(Paquete.anulado.is_(False), Paquete.vence.is_not(None),
                                              Paquete.vence > ahora, Paquete.vence <= limite)):
        if p.disponibles > 0:
            vencimientos.append({"emisor_id": p.emisor_id, "empresa": nombres.get(p.emisor_id), "tipo": "Paquete",
                                 "detalle": f"{p.disponibles} documentos de {p.nombre}", "vence": p.vence})
    for e in empresas:
        if not e.activo:
            continue
        if e.cert_vence and e.cert_vence <= limite:
            vencimientos.append({"emisor_id": e.id, "empresa": e.nombre, "tipo": "Certificado",
                                 "detalle": "Vencido" if e.cert_vence < ahora else "Certificado digital", "vence": e.cert_vence})
        if suscripciones.control_activo():
            for est in suscripciones.estados(db, e):
                if est["habilitado"] and est["vence"] and est["vence"] <= limite \
                        and est["estado"] in ("POR_VENCER", "EN_GRACIA", "VENCIDO"):
                    vencimientos.append({"emisor_id": e.id, "empresa": e.nombre, "tipo": "Mensualidad",
                                         "detalle": est["nombre"], "vence": est["vence"]})
        if control and saldos.get(e.id, 0) <= s.SALDO_ALERTA_DOCUMENTOS:
            vencimientos.append({"emisor_id": e.id, "empresa": e.nombre, "tipo": "Saldo",
                                 "detalle": f"Quedan {saldos.get(e.id, 0)} documentos", "vence": None})
    vencimientos.sort(key=lambda v: (v["vence"] is not None, v["vence"] or ahora))

    # Últimas ventas y mejores clientes (12 meses)
    ultimas = []
    for p in db.scalars(select(Paquete).where(Paquete.anulado.is_(False)).order_by(Paquete.created_at.desc()).limit(10)):
        ultimas.append({"fecha": p.created_at, "emisor_id": p.emisor_id, "empresa": nombres.get(p.emisor_id),
                        "detalle": descripcion_venta(p), "precio": p.precio, "moneda": p.moneda,
                        "comprobante": comprobante_a_dict(db, p)})
    for sus in db.scalars(select(Suscripcion).where(Suscripcion.anulada.is_(False)).order_by(Suscripcion.created_at.desc()).limit(10)):
        ultimas.append({"fecha": sus.created_at, "emisor_id": sus.emisor_id, "empresa": nombres.get(sus.emisor_id),
                        "detalle": descripcion_venta(sus), "precio": sus.precio, "moneda": sus.moneda,
                        "comprobante": comprobante_a_dict(db, sus)})
    ultimas = sorted(ultimas, key=lambda v: v["fecha"], reverse=True)[:10]

    hace_un_anio = ahora - timedelta(days=365)
    compras_por_empresa: dict[str, dict] = {}
    for emisor_id, moneda, precio, fecha in [
        *db.execute(select(Paquete.emisor_id, Paquete.moneda, Paquete.precio, Paquete.created_at)
                    .where(Paquete.anulado.is_(False), Paquete.created_at >= hace_un_anio)).all(),
        *db.execute(select(Suscripcion.emisor_id, Suscripcion.moneda, Suscripcion.precio, Suscripcion.created_at)
                    .where(Suscripcion.anulada.is_(False), Suscripcion.created_at >= hace_un_anio)).all(),
    ]:
        c = compras_por_empresa.setdefault(emisor_id, {"emisor_id": emisor_id, "empresa": nombres.get(emisor_id),
                                                       "compras": 0, "total": {}, "ultima": fecha})
        c["compras"] += 1
        c["total"][moneda] = str(Decimal(c["total"].get(moneda, "0")) + Decimal(precio))
        c["ultima"] = max(c["ultima"], fecha)
    mejores = sorted(compras_por_empresa.values(), key=lambda c: Decimal(c["total"].get("CRC", "0")), reverse=True)[:10]

    # Estado de cada empresa
    estado_empresas = []
    for e in empresas:
        alertas = diagnostico(db, e)
        estado_empresas.append({
            "emisor_id": e.id, "empresa": e.nombre, "numero_identificacion": e.numero_identificacion, "activo": e.activo,
            "ambiente": e.ambiente, "saldo": saldos.get(e.id) if control else None,
            "errores": sum(a["nivel"] == "error" for a in alertas), "alertas": sum(a["nivel"] == "alerta" for a in alertas),
            "principal": next((a for a in alertas if a["nivel"] != "info"), None),
        })
    activas = [x for x in estado_empresas if x["activo"]]
    return {
        "empresas_activas": len(activas),
        "empresas_con_errores": sum(1 for x in activas if x["errores"]),
        "empresas_con_alertas": sum(1 for x in activas if x["alertas"] and not x["errores"]),
        "ventas_mes": {k: str(v) for k, v in _ventas_entre(db, inicio_mes, fin_mes).items()},
        "ventas_por_mes": list(reversed(meses)),
        "documentos_vendidos_mes": int(documentos_vendidos),
        "documentos_consumidos_mes": documentos_consumidos,
        "vencimientos": vencimientos,
        "ultimas_ventas": ultimas,
        "mejores_clientes": mejores,
        "empresas": estado_empresas,
        "control_saldo": control,
    }


# --- Contabilidad de las ventas de la plataforma ---------------------------------------

def contabilidad(db: Session, anio: int, mes: int) -> dict:
    """
    Ventas cobradas del mes conciliadas con su comprobante: lo que el contador
    necesita para cerrar el mes sin revisar venta por venta.
    """
    desde, hasta = rango_mes(anio, mes)
    a = ajustes(db)
    nombres = dict(db.execute(select(Emisor.id, Emisor.nombre)).all())
    # Las ventas anuladas que tienen comprobante también se listan: si este sigue
    # vigente, el contador debe ver que falta la nota de crédito.
    ventas = [
        *db.scalars(select(Paquete).where(or_(Paquete.anulado.is_(False), Paquete.factura_id.is_not(None)),
                                          Paquete.precio > 0, Paquete.created_at >= desde, Paquete.created_at < hasta)),
        *db.scalars(select(Suscripcion).where(or_(Suscripcion.anulada.is_(False), Suscripcion.factura_id.is_not(None)),
                                              Suscripcion.precio > 0,
                                              Suscripcion.created_at >= desde, Suscripcion.created_at < hasta)),
    ]
    filas = []
    vendido: dict[str, Decimal] = {}
    facturado: dict[str, Decimal] = {}
    conteo = {"aceptados": 0, "en_proceso": 0, "rechazados": 0, "sin_comprobante": 0}
    for v in sorted(ventas, key=lambda x: x.created_at):
        comp = comprobante_a_dict(db, v)
        anulada = bool(v.anulado if isinstance(v, Paquete) else v.anulada)
        if anulada:
            filas.append({
                "clase": "paquete" if isinstance(v, Paquete) else "suscripcion", "id": str(v.id), "fecha": v.created_at,
                "emisor_id": v.emisor_id, "empresa": nombres.get(v.emisor_id), "detalle": descripcion_venta(v),
                "precio": v.precio, "moneda": v.moneda, "referencia_pago": v.referencia_pago, "comprobante": comp,
                "anulada": True, "nota_credito_pendiente": comprobante_por_anular(db, v),
            })
            continue
        vendido[v.moneda] = vendido.get(v.moneda, Decimal("0")) + Decimal(v.precio)
        if comp and comp.get("estado") == "ACEPTADO":
            conteo["aceptados"] += 1
            facturado[v.moneda] = facturado.get(v.moneda, Decimal("0")) + Decimal(comp["monto_total"])
        elif comp and comp.get("estado") == "RECHAZADO":
            conteo["rechazados"] += 1
        elif comp and comp.get("factura_id"):
            conteo["en_proceso"] += 1
        else:
            conteo["sin_comprobante"] += 1
        filas.append({
            "clase": "paquete" if isinstance(v, Paquete) else "suscripcion", "id": str(v.id), "fecha": v.created_at,
            "emisor_id": v.emisor_id, "empresa": nombres.get(v.emisor_id), "detalle": descripcion_venta(v),
            "precio": v.precio, "moneda": v.moneda, "referencia_pago": v.referencia_pago, "comprobante": comp,
        })
    return {
        "periodo": f"{anio:04d}-{mes:02d}",
        "emisor_ventas_id": a.emisor_ventas_id,
        "emisor_ventas": nombres.get(a.emisor_ventas_id),
        "ventas": filas,
        "vendido": {k: str(v) for k, v in vendido.items()},
        "facturado": {k: str(v) for k, v in facturado.items()},
        **conteo,
    }
