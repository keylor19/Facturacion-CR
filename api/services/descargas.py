"""
Descarga masiva de comprobantes en un ZIP (para el contador o respaldo propio):
XML firmados, respuestas de Hacienda, PDF opcional y los documentos recibidos.
"""
import csv
import io
import tempfile
import zipfile
from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import DocumentoRecibido, Emisor, Factura
from api.models.schemas import TIPOS_COMPROBANTE
from api.services.fechas import zona_cr
from api.services.pdf import generar_pdf

MAX_DOCUMENTOS = 3000
MAX_CON_PDF = 500   # generar PDF es lo costoso: con PDF se pide un rango menor


class DescargaError(Exception):
    pass


def _rango(columna, desde: date, hasta: date):
    return (columna >= datetime.combine(desde, time.min, zona_cr()),
            columna <= datetime.combine(hasta, time.max, zona_cr()))


def _carpeta(texto: str) -> str:
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in texto).strip()


def generar_zip(db: Session, emisor: Emisor, desde: date, hasta: date, *, emitidos: bool = True,
                recibidos: bool = True, con_pdf: bool = False, tipo_documento: str | None = None):
    """Devuelve un archivo temporal (posicionado al inicio) con el ZIP."""
    q_emitidos = select(Factura).where(Factura.emisor_id == emisor.id, *_rango(Factura.fecha_emision, desde, hasta))
    if tipo_documento:
        q_emitidos = q_emitidos.where(Factura.tipo_documento == tipo_documento)
    q_recibidos = select(DocumentoRecibido).where(DocumentoRecibido.emisor_id == emisor.id,
                                                  *_rango(DocumentoRecibido.fecha_emision, desde, hasta))
    n_emitidos = db.scalar(select(func.count()).select_from(q_emitidos.subquery())) if emitidos else 0
    n_recibidos = db.scalar(select(func.count()).select_from(q_recibidos.subquery())) if recibidos else 0
    if n_emitidos + n_recibidos == 0:
        raise DescargaError("No hay documentos en ese período")
    limite = MAX_CON_PDF if con_pdf else MAX_DOCUMENTOS
    if (n_emitidos if con_pdf else n_emitidos + n_recibidos) > limite:
        raise DescargaError(f"Son demasiados documentos ({n_emitidos + n_recibidos}); el máximo por descarga es "
                            f"{limite}{' con PDF' if con_pdf else ''}. Elija un rango de fechas menor.")

    indice = io.StringIO()
    indice.write("﻿")
    filas = csv.writer(indice, delimiter=";")
    filas.writerow(["Origen", "Tipo", "Fecha", "Consecutivo", "Clave", "Contraparte", "Identificación",
                    "Moneda", "Impuesto", "Total", "Estado"])

    salida = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024)
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        if emitidos:
            for f in db.execute(q_emitidos.order_by(Factura.fecha_emision).execution_options(yield_per=200)).scalars():
                tipo = TIPOS_COMPROBANTE.get(f.tipo_documento, f.tipo_documento)
                base = f"emitidos/{_carpeta(tipo)}/{f.numero_consecutivo}"
                if f.xml_firmado:
                    z.writestr(f"{base}.xml", f.xml_firmado)
                if f.xml_respuesta:
                    z.writestr(f"{base}-respuesta-hacienda.xml", f.xml_respuesta)
                if con_pdf:
                    z.writestr(f"{base}.pdf", generar_pdf(f))
                filas.writerow(["Emitido", tipo, f"{f.fecha_emision.astimezone(zona_cr()):%d/%m/%Y %H:%M}",
                                f.numero_consecutivo, f.clave, f.receptor_nombre or "", f.receptor_identificacion or "",
                                f.moneda, f.monto_impuesto, f.monto_total, f.estado.value])
        if recibidos:
            for d in db.execute(q_recibidos.order_by(DocumentoRecibido.fecha_emision).execution_options(yield_per=200)).scalars():
                base = f"recibidos/{_carpeta(d.proveedor_nombre or d.proveedor_identificacion)}/{d.clave}"
                z.writestr(f"{base}.xml", d.xml_original)
                if d.xml_respuesta_proveedor:
                    z.writestr(f"{base}-respuesta-hacienda-proveedor.xml", d.xml_respuesta_proveedor)
                if d.xml_firmado:
                    z.writestr(f"{base}-mensaje-receptor.xml", d.xml_firmado)
                if d.xml_respuesta:
                    z.writestr(f"{base}-respuesta-mensaje.xml", d.xml_respuesta)
                fecha = d.fecha_emision.astimezone(zona_cr()).strftime("%d/%m/%Y %H:%M") if d.fecha_emision else ""
                filas.writerow(["Recibido", TIPOS_COMPROBANTE.get(d.tipo_documento, d.tipo_documento or ""), fecha,
                                d.clave[21:41], d.clave, d.proveedor_nombre or "", d.proveedor_identificacion,
                                d.moneda, d.total_impuesto, d.total_comprobante,
                                d.estado.value if d.estado else "SIN RESPONDER"])
        z.writestr("indice.csv", indice.getvalue())
    salida.seek(0)
    return salida
