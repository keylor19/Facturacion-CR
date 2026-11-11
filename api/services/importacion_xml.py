"""
Carga de comprobantes XML de Hacienda para las empresas que el contador lleva y que
no facturan en este sistema. Se detecta solo si el XML es de una venta (la empresa es
el emisor) o de una compra (la empresa es el receptor):

- Ventas: se guardan como comprobantes emitidos «importados» (nunca se envían a
  Hacienda ni gastan documentos) con sus líneas, para el IVA, los libros y los asientos.
- Compras: se registran como facturas de proveedor aceptadas con crédito de IVA total
  (el contador puede cambiar la condición en el asiento si no es así).
"""
from datetime import date, datetime
from decimal import Decimal

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import DocumentoRecibido, Emisor, EstadoFactura, Factura, FacturaDetalle
from api.services import recepcion
from api.services.emision import EmisionError
from api.services.recepcion import _decimal, _texto
from api.services.xml_seguro import parsear

RAICES_EMITIDOS = {
    "FacturaElectronica": "01", "NotaDebitoElectronica": "02", "NotaCreditoElectronica": "03",
    "TiqueteElectronico": "04", "FacturaElectronicaCompra": "08", "FacturaElectronicaExportacion": "09",
    "ReciboElectronicoPago": "10",
}


class ImportacionError(Exception):
    pass


def _linea(nodo, numero: int) -> FacturaDetalle:
    t = lambda ruta: _texto(nodo, ruta)   # noqa: E731
    descuento = sum((_decimal(d.text) for d in nodo.findall("{*}Descuento/{*}MontoDescuento")), Decimal("0"))
    impuesto = nodo.find("{*}Impuesto")
    tarifa = _texto(impuesto, "CodigoTarifaIVA") if impuesto is not None else None
    porcentaje = _decimal(_texto(impuesto, "Tarifa")) if impuesto is not None else Decimal("0")
    monto_impuesto = sum((_decimal(i.findtext("{*}Monto")) for i in nodo.findall("{*}Impuesto")), Decimal("0"))
    exonerado = sum((_decimal(e.text) for e in nodo.findall("{*}Impuesto/{*}Exoneracion/{*}MontoExoneracion")), Decimal("0"))
    subtotal = _decimal(t("SubTotal"))
    return FacturaDetalle(
        linea_numero=int(t("NumeroLinea") or numero), codigo_cabys=t("CodigoCABYS") or t("Codigo"),
        descripcion=(t("Detalle") or "Sin detalle")[:500], unidad_medida=(t("UnidadMedida") or "")[:15] or None,
        cantidad=_decimal(t("Cantidad")) or Decimal("1"), precio_unitario=_decimal(t("PrecioUnitario")),
        descuento=descuento, subtotal=subtotal, base_imponible=_decimal(t("BaseImponible")) or subtotal,
        codigo_tarifa_iva=tarifa, impuesto_porcentaje=porcentaje if impuesto is not None else None,
        impuesto_monto=monto_impuesto, monto_exonerado=exonerado,
        impuesto_neto=_decimal(t("ImpuestoNeto")) if t("ImpuestoNeto") else monto_impuesto - exonerado,
        monto_total=_decimal(t("MontoTotalLinea")),
    )


def _emitido(db: Session, emisor: Emisor, root, raiz: str, xml_txt: str) -> Factura:
    clave = _texto(root, "Clave") or ""
    if db.scalar(select(Factura).where(Factura.clave == clave)):
        raise ImportacionError("Ese comprobante ya está cargado")
    fecha = datetime.fromisoformat(_texto(root, "FechaEmision"))
    r = lambda ruta: _texto(root, f"ResumenFactura/{ruta}")   # noqa: E731
    medios = [{"tipo": m.findtext("{*}TipoMedioPago") or m.text} for m in root.findall("{*}ResumenFactura/{*}MedioPago")]
    plazo = _texto(root, "PlazoCredito")
    referencia = _texto(root, "InformacionReferencia/Numero")
    origen = db.scalar(select(Factura).where(Factura.emisor_id == emisor.id, Factura.clave == referencia)) if referencia else None
    receptor = "Receptor"
    f = Factura(
        emisor_id=emisor.id, clave=clave, numero_consecutivo=_texto(root, "NumeroConsecutivo") or clave[21:41],
        tipo_documento=RAICES_EMITIDOS[raiz], fecha_emision=fecha, situacion=clave[41:42] or "1",
        receptor_nombre=(_texto(root, f"{receptor}/Nombre") or "")[:200] or None,
        receptor_identificacion=_texto(root, f"{receptor}/Identificacion/Numero"),
        receptor_tipo_identificacion=_texto(root, f"{receptor}/Identificacion/Tipo"),
        receptor_correo=_texto(root, f"{receptor}/CorreoElectronico"),
        condicion_venta=_texto(root, "CondicionVenta"),
        moneda=r("CodigoTipoMoneda/CodigoMoneda") or "CRC",
        tipo_cambio=_decimal(r("CodigoTipoMoneda/TipoCambio")) or None,
        total_venta=_decimal(r("TotalVenta")), total_descuentos=_decimal(r("TotalDescuentos")),
        total_gravado=_decimal(r("TotalGravado")), total_exento=_decimal(r("TotalExento")),
        total_exonerado=_decimal(r("TotalExonerado")), total_no_sujeto=_decimal(r("TotalNoSujeto")),
        total_otros_cargos=_decimal(r("TotalOtrosCargos")), total_iva_devuelto=_decimal(r("TotalIVADevuelto")),
        monto_impuesto=_decimal(r("TotalImpuesto")), monto_total=_decimal(r("TotalComprobante")),
        estado=EstadoFactura.ACEPTADO, estado_hacienda="importado", importada=True, correo_enviado=True,
        codigo_referencia=_texto(root, "InformacionReferencia/Codigo"), referencia_clave=referencia,
        factura_origen_id=origen.id if origen else None, periodo_fiscal=date(fecha.year, fecha.month, 1),
        xml_firmado=xml_txt,
        json_original={"medios_pago": medios, "plazo_credito": int(plazo) if plazo and plazo.isdigit() else None,
                       "importado": True},
    )
    f.detalles = [_linea(n, i + 1) for i, n in enumerate(root.findall("{*}DetalleServicio/{*}LineaDetalle"))]
    db.add(f)
    db.commit()
    return f


def importar(db: Session, emisor: Emisor, xml: bytes) -> tuple[str, object]:
    """Devuelve ("venta", Factura) o ("compra", DocumentoRecibido)."""
    if len(xml) > recepcion.MAX_BYTES_XML:
        raise ImportacionError("El XML es demasiado grande")
    try:
        root = parsear(xml)
    except etree.XMLSyntaxError as exc:
        raise ImportacionError(f"XML inválido: {exc}")
    raiz = etree.QName(root).localname
    if raiz not in RAICES_EMITIDOS:
        raise ImportacionError(f"No es un comprobante electrónico ({raiz}). Las respuestas de Hacienda y los mensajes "
                               "receptor no se cargan.")
    emisor_xml = _texto(root, "Emisor/Identificacion/Numero")
    receptor_xml = _texto(root, "Receptor/Identificacion/Numero")
    try:
        xml_txt = xml.decode("utf-8")
    except UnicodeDecodeError:
        xml_txt = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
    try:
        if emisor_xml == emisor.numero_identificacion:
            return "venta", _emitido(db, emisor, root, raiz, xml_txt)
        if receptor_xml == emisor.numero_identificacion:
            doc = recepcion.registrar_documento(db, emisor, xml, origen="contable")
            doc.mensaje, doc.estado, doc.estado_hacienda = "1", EstadoFactura.ACEPTADO, "importado"
            doc.condicion_impuesto, doc.monto_impuesto_acreditar = "01", doc.total_impuesto
            db.commit()
            return "compra", doc
    except EmisionError as exc:
        db.rollback()
        raise ImportacionError("Ese comprobante ya está cargado" if exc.status_code == 409 else exc.detail)
    except (ValueError, TypeError) as exc:
        db.rollback()
        raise ImportacionError(f"No se pudo leer el comprobante: {exc}")
    raise ImportacionError(f"El comprobante no es de esta empresa: lo emite {emisor_xml or '¿?'} para {receptor_xml or '¿?'}")
