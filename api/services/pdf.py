"""Representación gráfica (PDF) de un comprobante electrónico."""
from decimal import Decimal
from io import BytesIO

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from api.models.database import Factura
from api.models.schemas import TIPOS_COMPROBANTE
from api.services.fechas import zona_cr

CONDICIONES_VENTA = {
    "01": "Contado", "02": "Crédito", "03": "Consignación", "04": "Apartado",
    "05": "Arrendamiento con opción de compra", "06": "Arrendamiento en función financiera",
    "07": "Cobro a favor de un tercero", "08": "Servicios prestados al Estado a crédito",
    "10": "Venta a crédito en IVA hasta 90 días", "12": "Venta de mercancía no nacionalizada",
    "13": "Venta de bienes usados no contribuyente", "14": "Arrendamiento operativo",
    "15": "Arrendamiento financiero", "99": "Otros",
}
MEDIOS_PAGO = {
    "01": "Efectivo", "02": "Tarjeta", "03": "Cheque", "04": "Transferencia",
    "05": "Recaudado por terceros", "06": "SINPE Móvil", "07": "Plataforma digital", "99": "Otros",
}


def _m(valor, moneda: str) -> str:
    valor = Decimal(valor or 0)
    return f"{moneda} {valor:,.2f}"


def _p(texto, estilo):
    return Paragraph(escape(str(texto or "")), estilo)


def _qr(texto: str, tamano: float = 30 * mm) -> Drawing:
    widget = QrCodeWidget(texto)
    x1, y1, x2, y2 = widget.getBounds()
    d = Drawing(tamano, tamano, transform=[tamano / (x2 - x1), 0, 0, tamano / (y2 - y1), 0, 0])
    d.add(widget)
    return d


def generar_pdf(factura: Factura) -> bytes:
    emisor = factura.emisor
    datos = factura.json_original or {}
    moneda = factura.moneda

    estilos = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontSize=8, leading=10)
    negrita = ParagraphStyle("b", parent=normal, fontName="Helvetica-Bold")
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=13, leading=16, alignment=2)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"{TIPOS_COMPROBANTE.get(factura.tipo_documento, 'Comprobante')} {factura.numero_consecutivo}")
    partes = []

    # --- Encabezado: emisor + tipo de documento ---
    emisor_txt = [
        Paragraph(f"<b>{escape(emisor.nombre)}</b>", ParagraphStyle("e", parent=normal, fontSize=11, leading=14)),
        _p(emisor.nombre_comercial, normal) if emisor.nombre_comercial else Spacer(0, 0),
        _p(f"Identificación: {emisor.numero_identificacion}", normal),
        _p(emisor.otras_senas, normal),
        _p(f"Correo: {emisor.correo}" + (f"   Tel: {emisor.telefono}" if emisor.telefono else ""), normal),
        _p(f"Actividad económica: {datos.get('codigo_actividad_emisor') or emisor.codigo_actividad}", normal),
    ]
    fecha_local = factura.fecha_emision.astimezone(zona_cr())
    doc_txt = [
        Paragraph(escape(TIPOS_COMPROBANTE.get(factura.tipo_documento, "Comprobante electrónico")), titulo),
        Paragraph(f"<b>Consecutivo:</b> {factura.numero_consecutivo}", ParagraphStyle("r", parent=normal, alignment=2)),
        Paragraph(f"<b>Fecha:</b> {fecha_local:%d/%m/%Y %H:%M}", ParagraphStyle("r2", parent=normal, alignment=2)),
    ]
    encabezado = Table([[emisor_txt, doc_txt]], colWidths=[100 * mm, 86 * mm])
    encabezado.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    partes += [encabezado, Spacer(0, 4 * mm)]

    partes.append(Paragraph(f"<b>Clave numérica:</b> {factura.clave}", normal))
    partes.append(Spacer(0, 3 * mm))

    # --- Receptor / condiciones ---
    etiqueta = "Proveedor" if factura.tipo_documento == "08" else "Receptor"
    receptor = [
        Paragraph(f"<b>{etiqueta}:</b> {escape(factura.receptor_nombre or 'Consumidor final')}", normal),
        _p(f"Identificación: {factura.receptor_identificacion}", normal) if factura.receptor_identificacion else Spacer(0, 0),
        _p(f"Correo: {factura.receptor_correo}", normal) if factura.receptor_correo else Spacer(0, 0),
    ]
    medios = ", ".join(MEDIOS_PAGO.get(m.get("tipo"), m.get("tipo")) for m in datos.get("medios_pago", []))
    condiciones = [
        _p(f"Condición de venta: {CONDICIONES_VENTA.get(factura.condicion_venta, factura.condicion_venta)}"
           + (f" ({datos.get('plazo_credito')} días)" if datos.get("plazo_credito") else ""), normal),
        _p(f"Medio de pago: {medios}", normal),
        _p(f"Moneda: {moneda}" + (f"   Tipo de cambio: {Decimal(factura.tipo_cambio):,.2f}" if factura.tipo_cambio else ""), normal),
    ]
    info = Table([[receptor, condiciones]], colWidths=[100 * mm, 86 * mm])
    info.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    partes += [info, Spacer(0, 4 * mm)]

    # --- Detalle ---
    filas = [[_p(h, negrita) for h in ("#", "CABYS", "Descripción", "Cant.", "Precio unit.", "Desc.", "IVA %", "Total línea")]]
    for d in factura.detalles:
        filas.append([
            _p(d.linea_numero, normal), _p(d.codigo_cabys, normal), _p(d.descripcion, normal),
            _p(f"{Decimal(d.cantidad):,.3f}".rstrip("0").rstrip("."), normal),
            _p(f"{Decimal(d.precio_unitario):,.2f}", normal), _p(f"{Decimal(d.descuento):,.2f}", normal),
            _p(f"{Decimal(d.impuesto_porcentaje or 0):.2f}", normal), _p(f"{Decimal(d.monto_total):,.2f}", normal),
        ])
    detalle = Table(filas, colWidths=[8 * mm, 25 * mm, 58 * mm, 15 * mm, 24 * mm, 18 * mm, 13 * mm, 25 * mm], repeatRows=1)
    detalle.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    partes += [detalle, Spacer(0, 4 * mm)]

    # --- Totales + QR ---
    totales = [
        ("Total venta", factura.total_venta), ("Descuentos", factura.total_descuentos),
        ("Total gravado", factura.total_gravado), ("Total exento", factura.total_exento),
        ("Total exonerado", factura.total_exonerado), ("Impuesto", factura.monto_impuesto),
    ]
    if factura.total_otros_cargos:
        totales.append(("Otros cargos", factura.total_otros_cargos))
    filas_tot = [[_p(n, normal), _p(_m(v, moneda), normal)] for n, v in totales]
    filas_tot.append([_p("TOTAL", negrita), _p(_m(factura.monto_total, moneda), negrita)])
    tabla_tot = Table(filas_tot, colWidths=[35 * mm, 40 * mm])
    tabla_tot.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black), ("ALIGN", (1, 0), (1, -1), "RIGHT")]))

    notas = []
    if datos.get("notas"):
        notas.append(_p(f"Notas: {datos['notas']}", normal))
    for ref in datos.get("referencias") or []:
        notas.append(_p(f"Referencia: documento {ref.get('numero')} ({ref.get('razon') or ''})", normal))
    notas.append(_p(f"Estado ante Hacienda: {factura.estado.value}", normal))
    pie = Table([[_qr(factura.clave), notas, tabla_tot]], colWidths=[35 * mm, 76 * mm, 75 * mm])
    pie.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    partes += [pie, Spacer(0, 6 * mm)]

    partes.append(_p(
        "Comprobante electrónico emitido conforme a la normativa vigente de la Dirección General de Tributación "
        "de Costa Rica (versión 4.4). Consulte la validez del comprobante con su clave numérica.",
        ParagraphStyle("pie", parent=normal, fontSize=7, textColor=colors.grey),
    ))

    doc.build(partes)
    return buffer.getvalue()
