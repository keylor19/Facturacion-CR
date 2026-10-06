"""
Emisión de comprobantes: consecutivo, clave, XML, firma, validación y
persistencia. Lo usan la API (crear, anular) y cualquier otro punto de entrada.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models.database import (
    Emisor, Factura, FacturaDetalle, EstadoFactura, siguiente_consecutivo,
)
from api.models.schemas import FacturaRequest, ReciboPagoRequest, ReferenciaRequest, TIPOS_COMPROBANTE
from api.services import emisores, hacienda_publico, inventario, saldo
from api.services.cifrado import CifradoError
from api.services.clave_generator import generar_clave, consecutivo_desde_clave
from api.services.fechas import ahora_cr, a_iso_cr, zona_cr
from config.settings import get_settings
from api.services.firma import firmar_xml, verificar_firma_local, FirmaError
from api.services.xml_generator import (
    LineaRecibo, generar_recibo_pago, generar_xml, validar_xsd, XMLValidacionError, q,
)

logger = logging.getLogger(__name__)

# Comprobantes que se pueden anular con una nota de crédito
TIPOS_ANULABLES = ("01", "02", "04", "09")


class EmisionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _parte(tipo: str | None, numero: str | None) -> dict | None:
    if numero and tipo in ("01", "02", "03", "04"):
        return {"tipoIdentificacion": tipo, "numeroIdentificacion": numero}
    return None


def _buscar_por_referencia(db: Session, emisor: Emisor, referencia_externa: str) -> Factura | None:
    return db.scalar(select(Factura).where(
        Factura.emisor_id == emisor.id, Factura.referencia_externa == referencia_externa
    ))


def firmar_para_emisor(emisor: Emisor, xml: str) -> str:
    """Firma con el certificado del emisor y verifica el resultado."""
    try:
        p12, password = emisores.certificado(emisor)
        xml_firmado = firmar_xml(xml, p12, password)
    except (FirmaError, emisores.EmisorIncompletoError) as exc:
        raise EmisionError(409, f"No se pudo firmar: {exc}")
    except CifradoError as exc:
        logger.exception("Error descifrando el certificado del emisor %s", emisor.id)
        raise EmisionError(500, f"No se pudo firmar: {exc}")
    if not verificar_firma_local(xml_firmado):
        raise EmisionError(500, "La firma generada no es válida. Revise el certificado digital del emisor.")
    return xml_firmado


def verificar_saldo(db: Session, emisor: Emisor) -> None:
    """Falla rápido (402) si la empresa no tiene documentos disponibles."""
    try:
        saldo.verificar(db, emisor)
    except saldo.SaldoAgotadoError as exc:
        raise EmisionError(402, str(exc))


def cobrar_documento(db: Session, emisor: Emisor, referencia: str, tipo_documento: str, **documento) -> int | None:
    """Descuenta 1 documento dentro de la transacción de emisión (402 si no hay saldo)."""
    try:
        return saldo.consumir(db, emisor, referencia, tipo_documento, **documento)
    except saldo.SaldoAgotadoError as exc:
        db.rollback()
        raise EmisionError(402, str(exc))


def _fecha_emision(datos: FacturaRequest) -> datetime:
    """
    Situación 1: ahora. Situación 2 (contingencia) y 3 (sin internet): la fecha
    real en que se hizo la venta, que no puede ser futura ni demasiado antigua.
    """
    ahora = ahora_cr()
    if datos.situacion == "1":
        return ahora
    fecha = datos.fecha_emision
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=zona_cr())
    fecha = fecha.astimezone(zona_cr()).replace(microsecond=0)
    if fecha > ahora + timedelta(minutes=5):
        raise EmisionError(422, "fecha_emision no puede ser futura")
    limite = get_settings().DIAS_MAX_CONTINGENCIA
    if fecha < ahora - timedelta(days=limite):
        raise EmisionError(422, f"fecha_emision tiene más de {limite} días; revise el plazo permitido por Hacienda")
    return fecha


def emitir(
    db: Session, emisor: Emisor, datos: FacturaRequest, factura_origen_id: str | None = None
) -> tuple[Factura, bool]:
    """
    Crea, firma y guarda el comprobante (estado PENDIENTE). Devuelve
    (factura, creada). Si referencia_externa ya existe devuelve la existente.
    El encolado del envío lo hace quien llama.
    """
    if datos.referencia_externa:
        existente = _buscar_por_referencia(db, emisor, datos.referencia_externa)
        if existente:
            return existente, False

    try:
        emisores.verificar_listo_para_emitir(emisor)
    except emisores.EmisorIncompletoError as exc:
        raise EmisionError(409, str(exc))
    verificar_saldo(db, emisor)

    if get_settings().VALIDAR_CABYS:
        inexistentes = hacienda_publico.cabys_inexistentes([p.codigo_cabys for p in datos.productos])
        if inexistentes:
            raise EmisionError(422, "Código(s) CABYS que no existen en el catálogo de Hacienda: "
                                    + ", ".join(inexistentes) + ". Búsquelos en /api/v1/hacienda/cabys?q=")
        no_aplicables = hacienda_publico.exoneraciones_no_aplicables(datos.productos)
        if no_aplicables:
            raise EmisionError(422, "Exoneración no aplicable: " + "; ".join(no_aplicables)
                                    + ". Quite la exoneración de esas líneas o use una que las contemple.")

    fecha_emision = _fecha_emision(datos)

    if datos.moneda != "CRC" and datos.tipo_cambio is None:
        try:
            # Venta de un día anterior (contingencia): el tipo de cambio de ese día
            if fecha_emision.date() < ahora_cr().date():
                datos.tipo_cambio = hacienda_publico.tipo_cambio_en_fecha(datos.moneda, fecha_emision.date())
            else:
                datos.tipo_cambio = hacienda_publico.tipo_cambio(datos.moneda)
        except hacienda_publico.HaciendaPublicoError as exc:
            raise EmisionError(422, f"No se pudo obtener el tipo de cambio ({exc}); indique tipo_cambio")
    persona = emisores.persona_emisor(emisor)

    try:
        numero = siguiente_consecutivo(db, emisor.id, datos.sucursal, datos.terminal, datos.tipo_documento)
        clave = generar_clave(
            numero_identificacion_emisor=emisor.numero_identificacion,
            sucursal=datos.sucursal,
            terminal=datos.terminal,
            tipo_documento=datos.tipo_documento,
            numero_consecutivo=numero,
            fecha_emision=fecha_emision.date(),
            situacion=datos.situacion,
        )
        consecutivo = consecutivo_desde_clave(clave)
        xml_sin_firmar, lineas, tot = generar_xml(clave, consecutivo, fecha_emision, persona, datos)
        xml_firmado = firmar_para_emisor(emisor, xml_sin_firmar)
        validar_xsd(xml_firmado, datos.tipo_documento)
    except XMLValidacionError as exc:
        db.rollback()
        raise EmisionError(422, str(exc))
    except EmisionError:
        db.rollback()
        raise

    # Partes del JSON de envío (deben coincidir con los nodos Emisor/Receptor del XML)
    empresa = _parte(emisor.tipo_identificacion, emisor.numero_identificacion)
    if datos.tipo_documento == "08":
        # En la FEC el nodo Emisor del XML es el proveedor, pero en el envío el
        # "emisor" es quien firma y cuya cédula va en la clave (la empresa).
        contraparte = datos.proveedor
        parte_emisor = empresa
        parte_receptor = _parte(contraparte.tipo_identificacion, contraparte.numero_identificacion)
    else:
        contraparte = datos.receptor
        parte_emisor = empresa
        parte_receptor = _parte(contraparte.tipo_identificacion, contraparte.numero_identificacion) if contraparte else None

    envio_json = {"clave": clave, "fecha": a_iso_cr(fecha_emision), "emisor": parte_emisor}
    if parte_receptor:
        envio_json["receptor"] = parte_receptor

    factura = Factura(
        emisor_id=emisor.id,
        clave=clave,
        numero_consecutivo=consecutivo,
        tipo_documento=datos.tipo_documento,
        situacion=datos.situacion,
        fecha_emision=fecha_emision,
        referencia_externa=datos.referencia_externa,
        factura_origen_id=factura_origen_id,
        receptor_nombre=contraparte.nombre if contraparte else None,
        receptor_identificacion=(contraparte.numero_identificacion or contraparte.identificacion_extranjero) if contraparte else None,
        receptor_tipo_identificacion=contraparte.tipo_identificacion if contraparte else None,
        receptor_correo=contraparte.correo if contraparte else None,
        condicion_venta=datos.condicion_venta,
        moneda=datos.moneda,
        tipo_cambio=datos.tipo_cambio,
        total_venta=tot.venta,
        total_descuentos=tot.descuentos,
        total_gravado=tot.gravado,
        total_exento=tot.exento,
        total_exonerado=tot.exonerado,
        total_no_sujeto=tot.no_sujeto,
        total_iva_devuelto=tot.iva_devuelto,
        total_otros_cargos=tot.otros_cargos,
        monto_impuesto=tot.impuesto,
        monto_total=tot.comprobante,
        estado=EstadoFactura.PENDIENTE,
        envio_json=envio_json,
        clave_consulta=clave,
        xml_firmado=xml_firmado,
        json_original=datos.model_dump(mode="json"),
    )
    factura.detalles = [
        FacturaDetalle(
            linea_numero=ln.numero,
            codigo_cabys=ln.producto.codigo_cabys,
            codigo_producto=ln.producto.codigo_comercial,
            descripcion=ln.producto.descripcion,
            unidad_medida=ln.producto.unidad_medida,
            es_servicio=ln.producto.servicio,
            cantidad=ln.producto.cantidad,
            precio_unitario=ln.producto.precio_unitario,
            descuento=ln.descuento,
            subtotal=ln.subtotal,
            base_imponible=ln.base_imponible,
            codigo_tarifa_iva=ln.producto.tarifa_iva_principal,
            impuesto_porcentaje=ln.tarifa_iva,
            impuesto_monto=ln.impuesto_bruto,
            monto_exonerado=ln.monto_exonerado,
            impuesto_asumido=ln.impuesto_asumido,
            impuesto_neto=ln.impuesto_neto,
            monto_total=ln.monto_total_linea,
        )
        for ln in lineas
    ]
    db.add(factura)
    try:
        inventario.aplicar_documento(db, emisor.id, factura, datos)
    except inventario.InventarioError as exc:
        db.rollback()
        raise EmisionError(422, str(exc))
    restante = cobrar_documento(db, emisor, clave, datos.tipo_documento, factura=factura)

    try:
        db.commit()
    except IntegrityError:
        # Dos solicitudes simultáneas con la misma referencia_externa (no se cobra)
        db.rollback()
        if datos.referencia_externa:
            existente = _buscar_por_referencia(db, emisor, datos.referencia_externa)
            if existente:
                return existente, False
        raise
    saldo.despues_de_consumir(emisor, restante)
    return factura, True


def datos_anulacion(original: Factura, razon: str, referencia_externa: str | None) -> FacturaRequest:
    """Arma la nota de crédito que anula totalmente un comprobante aceptado."""
    if original.tipo_documento not in TIPOS_ANULABLES:
        raise EmisionError(409, f"No se puede anular un comprobante tipo {original.tipo_documento}")
    if original.estado != EstadoFactura.ACEPTADO:
        raise EmisionError(409, "Solo se pueden anular comprobantes aceptados por Hacienda")

    base = dict(original.json_original)
    base.update(
        tipo_documento="03",
        referencia_externa=referencia_externa,
        referencia=None,
        referencias=[ReferenciaRequest(
            tipo_documento=original.tipo_documento,
            numero=original.clave,
            fecha_emision=original.fecha_emision,
            codigo="01",
            razon=razon,
        ).model_dump(mode="json")],
        tipo_cambio=str(original.tipo_cambio) if original.tipo_cambio else None,
        notas=None,
    )
    return FacturaRequest(**base)


def notas_activas(db: Session, original: Factura) -> list[Factura]:
    """Notas de crédito de anulación ya emitidas y no rechazadas para un comprobante."""
    return list(db.scalars(select(Factura).where(
        Factura.factura_origen_id == original.id,
        Factura.tipo_documento == "03",
        Factura.estado != EstadoFactura.RECHAZADO,
    )))


# ---------------------------------------------------------------------------
# Recibo Electrónico de Pago (10)
# ---------------------------------------------------------------------------

# Condición de la venta original -> condición del recibo de pago (XSD oficial)
CONDICION_PAGO = {"08": "09", "10": "11"}


def recibos_activos(db: Session, original: Factura) -> list[Factura]:
    return list(db.scalars(select(Factura).where(
        Factura.factura_origen_id == original.id,
        Factura.tipo_documento == "10",
        Factura.estado != EstadoFactura.RECHAZADO,
    )))


def saldo_pendiente(db: Session, original: Factura) -> Decimal:
    pagado = sum((r.monto_total for r in recibos_activos(db, original)), Decimal("0"))
    return q(original.monto_total - pagado)


def _lineas_recibo(original: Factura, monto: Decimal) -> list[LineaRecibo]:
    """Reparte el pago entre las tarifas de IVA de la factura original, en proporción."""
    proporcion = monto / original.monto_total
    grupos: dict = {}
    for d in original.detalles:
        g = grupos.setdefault(d.codigo_tarifa_iva, {"subtotal": Decimal("0"), "iva": Decimal("0"), "tarifa": d.impuesto_porcentaje})
        g["subtotal"] += d.subtotal
        g["iva"] += d.impuesto_neto
    # Los otros cargos de la factura se pagan como parte del subtotal sin IVA
    if original.total_otros_cargos:
        g = grupos.setdefault(None, {"subtotal": Decimal("0"), "iva": Decimal("0"), "tarifa": None})
        g["subtotal"] += original.total_otros_cargos

    lineas = []
    for codigo, g in sorted(grupos.items(), key=lambda x: x[0] or ""):
        detalle = f"Pago {TIPOS_COMPROBANTE[original.tipo_documento].lower()} {original.numero_consecutivo}"
        if codigo:
            detalle += f" (IVA {Decimal(g['tarifa'] or 0):g}%)"
        lineas.append(LineaRecibo(
            detalle=detalle,
            subtotal=q(g["subtotal"] * proporcion),
            codigo_tarifa_iva=codigo,
            tarifa=g["tarifa"],
            impuesto=q(g["iva"] * proporcion),
        ))
    # Ajuste de redondeo para que el recibo sume exactamente el monto pagado
    diferencia = q(monto) - sum((ln.total for ln in lineas), Decimal("0"))
    if diferencia and lineas:
        lineas[0].subtotal += diferencia
    return lineas


def emitir_recibo_pago(db: Session, emisor: Emisor, original: Factura, req: ReciboPagoRequest) -> tuple[Factura, bool]:
    if req.referencia_externa:
        existente = _buscar_por_referencia(db, emisor, req.referencia_externa)
        if existente:
            return existente, False

    if original.tipo_documento != "01":
        raise EmisionError(409, "El recibo de pago aplica a facturas electrónicas (01)")
    if original.condicion_venta not in CONDICION_PAGO:
        raise EmisionError(409, "El recibo de pago aplica a ventas a crédito al Estado (08) o con IVA hasta 90 días (10)")
    if original.estado != EstadoFactura.ACEPTADO:
        raise EmisionError(409, "La factura debe estar aceptada por Hacienda")
    if not original.receptor_identificacion:
        raise EmisionError(409, "La factura no tiene receptor identificado")

    pendiente = saldo_pendiente(db, original)
    monto = q(req.monto)
    if monto > pendiente:
        raise EmisionError(422, f"El pago ({monto}) supera el saldo pendiente ({pendiente})")

    try:
        emisores.verificar_listo_para_emitir(emisor)
    except emisores.EmisorIncompletoError as exc:
        raise EmisionError(409, str(exc))
    verificar_saldo(db, emisor)

    sucursal = req.sucursal or int(original.numero_consecutivo[:3])
    terminal = req.terminal or int(original.numero_consecutivo[3:8])
    fecha = ahora_cr()
    persona = emisores.persona_emisor(emisor)
    lineas = _lineas_recibo(original, monto)
    receptor = {
        "nombre": original.receptor_nombre,
        "tipo_identificacion": original.receptor_tipo_identificacion,
        "numero_identificacion": original.receptor_identificacion,
        "correo": original.receptor_correo,
    }
    try:
        numero = siguiente_consecutivo(db, emisor.id, sucursal, terminal, "10")
        clave = generar_clave(emisor.numero_identificacion, sucursal, terminal, "10", numero, fecha.date())
        consecutivo = consecutivo_desde_clave(clave)
        xml = generar_recibo_pago(
            clave, consecutivo, fecha, persona, receptor, CONDICION_PAGO[original.condicion_venta],
            original.moneda, original.tipo_cambio, lineas, req.medios_pago,
            {"tipo_documento": original.tipo_documento, "numero": original.clave,
             "fecha_emision": original.fecha_emision, "codigo": "04", "razon": "Pago de factura a crédito"},
        )
        xml_firmado = firmar_para_emisor(emisor, xml)
        validar_xsd(xml_firmado, "10")
    except XMLValidacionError as exc:
        db.rollback()
        raise EmisionError(422, str(exc))
    except EmisionError:
        db.rollback()
        raise

    subtotal = sum((ln.subtotal for ln in lineas), Decimal("0"))
    impuesto = sum((ln.impuesto for ln in lineas), Decimal("0"))
    recibo = Factura(
        emisor_id=emisor.id,
        clave=clave,
        numero_consecutivo=consecutivo,
        tipo_documento="10",
        fecha_emision=fecha,
        referencia_externa=req.referencia_externa,
        factura_origen_id=original.id,
        receptor_nombre=original.receptor_nombre,
        receptor_identificacion=original.receptor_identificacion,
        receptor_tipo_identificacion=original.receptor_tipo_identificacion,
        receptor_correo=original.receptor_correo,
        condicion_venta=CONDICION_PAGO[original.condicion_venta],
        moneda=original.moneda,
        tipo_cambio=original.tipo_cambio,
        total_venta=subtotal,
        total_gravado=subtotal,
        monto_impuesto=impuesto,
        monto_total=subtotal + impuesto,
        estado=EstadoFactura.PENDIENTE,
        envio_json={
            "clave": clave, "fecha": a_iso_cr(fecha),
            "emisor": _parte(emisor.tipo_identificacion, emisor.numero_identificacion),
            **({"receptor": parte} if (parte := _parte(original.receptor_tipo_identificacion,
                                                        original.receptor_identificacion)) else {}),
        },
        clave_consulta=clave,
        xml_firmado=xml_firmado,
        json_original={**req.model_dump(mode="json"), "factura_origen": original.clave},
    )
    recibo.detalles = [
        FacturaDetalle(
            linea_numero=i, descripcion=ln.detalle, cantidad=1, precio_unitario=ln.subtotal,
            subtotal=ln.subtotal, base_imponible=ln.subtotal, codigo_tarifa_iva=ln.codigo_tarifa_iva,
            impuesto_porcentaje=ln.tarifa, impuesto_monto=ln.impuesto, impuesto_neto=ln.impuesto,
            monto_total=ln.total,
        )
        for i, ln in enumerate(lineas, start=1)
    ]
    db.add(recibo)
    restante = cobrar_documento(db, emisor, clave, "10", factura=recibo)
    db.commit()
    saldo.despues_de_consumir(emisor, restante)
    return recibo, True
