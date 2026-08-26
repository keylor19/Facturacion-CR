"""
Genera el XML de la Factura Electrónica v4.4 a partir de los datos ya
validados (Pydantic) y la clave ya generada.

⚠️ IMPORTANTE: esta es una plantilla base con los campos obligatorios más
comunes. El XSD real de v4.4 tiene bastantes más campos opcionales/condicionales
(exoneraciones, referencias a otros documentos, información de otros
cargos, etc.). Antes de ir a producción, valida el XML generado contra el
XSD oficial descargado de ATV con una librería como `xmlschema` o `lxml`.
"""
from datetime import datetime
from decimal import Decimal
from lxml import etree

NS = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica"


def _sub(parent, tag, text=None):
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def generar_xml_factura(
    clave: str,
    numero_consecutivo: str,
    emisor: dict,
    receptor: dict,
    productos: list,
    moneda: str = "CRC",
    condicion_venta: str = "01",
    medio_pago: str = "01",
    fecha_emision: datetime | None = None,
) -> str:
    """
    Devuelve el XML SIN firmar (string). La firma se aplica después con
    services/firma.py, porque la firma XAdES necesita el documento ya
    canonicalizado y completo.
    """
    fecha_emision = fecha_emision or datetime.now()

    root = etree.Element("FacturaElectronica", nsmap={None: NS})

    _sub(root, "Clave", clave)
    _sub(root, "ProveedorSistemas", emisor.get("numero_identificacion", ""))
    _sub(root, "CodigoActividadEmisor", emisor.get("codigo_actividad", "000000"))
    _sub(root, "NumeroConsecutivo", numero_consecutivo)
    _sub(root, "FechaEmision", fecha_emision.strftime("%Y-%m-%dT%H:%M:%S-06:00"))

    # --- Emisor ---
    em = _sub(root, "Emisor")
    _sub(em, "Nombre", emisor["nombre"])
    ident = _sub(em, "Identificacion")
    _sub(ident, "Tipo", emisor["tipo_identificacion"])
    _sub(ident, "Numero", emisor["numero_identificacion"])
    ubic = _sub(em, "Ubicacion")
    _sub(ubic, "Provincia", emisor.get("provincia", "1"))
    _sub(ubic, "Canton", emisor.get("canton", "01"))
    _sub(ubic, "Distrito", emisor.get("distrito", "01"))
    _sub(em, "CorreoElectronico", emisor.get("correo", ""))

    # --- Receptor ---
    if receptor:
        rec = _sub(root, "Receptor")
        _sub(rec, "Nombre", receptor["nombre"])
        ridnet = _sub(rec, "Identificacion")
        _sub(ridnet, "Tipo", receptor["tipo_identificacion"])
        _sub(ridnet, "Numero", receptor["numero_identificacion"])
        if receptor.get("correo"):
            _sub(rec, "CorreoElectronico", receptor["correo"])

    _sub(root, "CondicionVenta", condicion_venta)

    medio = _sub(root, "MedioPago")
    _sub(medio, "TipoMedioPago", medio_pago)

    # --- Detalle de líneas ---
    detalle = _sub(root, "DetalleServicio")
    total_gravado = Decimal("0")
    total_impuesto = Decimal("0")
    total_venta = Decimal("0")

    for i, prod in enumerate(productos, start=1):
        cantidad = Decimal(str(prod["cantidad"]))
        precio_unitario = Decimal(str(prod["precio_unitario"]))
        monto_total_linea = (cantidad * precio_unitario).quantize(Decimal("0.00001"))
        pct_imp = Decimal(str(prod.get("impuesto_porcentaje", "13.00")))
        monto_impuesto_linea = (monto_total_linea * pct_imp / 100).quantize(Decimal("0.00001"))

        linea = _sub(detalle, "LineaDetalle")
        _sub(linea, "NumeroLinea", i)
        if prod.get("codigo_producto"):
            codigo = _sub(linea, "Codigo")
            _sub(codigo, "Tipo", "04")
            _sub(codigo, "Codigo", prod["codigo_producto"])
        _sub(linea, "Cantidad", cantidad)
        _sub(linea, "UnidadMedida", "Unid")
        _sub(linea, "Detalle", prod["descripcion"])
        _sub(linea, "PrecioUnitario", precio_unitario)
        _sub(linea, "MontoTotal", monto_total_linea)
        _sub(linea, "SubTotal", monto_total_linea)

        impuesto = _sub(linea, "Impuesto")
        _sub(impuesto, "Codigo", "01")  # 01 = IVA
        _sub(impuesto, "Tarifa", pct_imp)
        _sub(impuesto, "Monto", monto_impuesto_linea)

        _sub(linea, "ImpuestoNeto", monto_impuesto_linea)
        _sub(linea, "MontoTotalLinea", monto_total_linea + monto_impuesto_linea)

        total_gravado += monto_total_linea
        total_impuesto += monto_impuesto_linea
        total_venta += monto_total_linea

    # --- Resumen de factura ---
    resumen = _sub(root, "ResumenFactura")
    codmoneda = _sub(resumen, "CodigoTipoMoneda")
    _sub(codmoneda, "CodigoMoneda", moneda)
    if moneda != "CRC":
        _sub(codmoneda, "TipoCambio", "1.00")  # ⚠️ reemplazar por tipo de cambio real BCCR

    _sub(resumen, "TotalServGravados", "0.00")
    _sub(resumen, "TotalMercanciasGravadas", total_gravado)
    _sub(resumen, "TotalGravado", total_gravado)
    _sub(resumen, "TotalVenta", total_venta)
    _sub(resumen, "TotalDescuentos", "0.00")
    _sub(resumen, "TotalVentaNeta", total_venta)
    _sub(resumen, "TotalImpuesto", total_impuesto)
    _sub(resumen, "TotalComprobante", total_venta + total_impuesto)

    xml_str = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=False
    )
    return xml_str.decode("utf-8")
