"""
Recepción de comprobantes de proveedores y emisión del Mensaje Receptor
(aceptación total, parcial o rechazo) ante Hacienda.
"""
import base64
import binascii
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import DocumentoRecibido, Emisor, EstadoFactura, siguiente_consecutivo
from api.models.schemas import MensajeReceptorRequest
from api.services import emisores
from api.services.clave_generator import generar_consecutivo
from api.services import saldo
from api.services.emision import EmisionError, cobrar_documento, firmar_para_emisor, verificar_saldo
from api.services.fechas import ahora_cr, a_iso_cr
from api.services.firma import verificar_firma_local
from api.services.xml_generator import (
    generar_mensaje_receptor, validar_xsd, XMLValidacionError, TIPO_DOC_MENSAJE_RECEPTOR, q,
)
from api.services.xml_seguro import parsear

# Comprobantes que admiten Mensaje Receptor
RAICES_ACEPTABLES = {
    "FacturaElectronica": "01",
    "NotaDebitoElectronica": "02",
    "NotaCreditoElectronica": "03",
}
MAX_BYTES_XML = 5_000_000


def decodificar_base64(dato: str, campo: str) -> bytes:
    try:
        contenido = base64.b64decode(dato, validate=True)
    except (binascii.Error, ValueError):
        raise EmisionError(422, f"{campo} no es base64 válido")
    if len(contenido) > MAX_BYTES_XML:
        raise EmisionError(413, f"{campo} excede el tamaño máximo")
    return contenido


def _texto(root, ruta: str) -> str | None:
    el = root.find("/".join("{*}" + p for p in ruta.split("/")))
    return el.text.strip() if el is not None and el.text else None


def _decimal(valor: str | None) -> Decimal:
    try:
        return Decimal(valor) if valor else Decimal("0")
    except InvalidOperation:
        raise EmisionError(422, f"Monto inválido en el XML: {valor!r}")


def registrar_documento(db: Session, emisor: Emisor, xml: bytes, respuesta: bytes | None = None) -> DocumentoRecibido:
    """Valida y guarda un comprobante recibido de un proveedor."""
    if len(xml) > MAX_BYTES_XML:
        raise EmisionError(413, "El XML excede el tamaño máximo")
    try:
        root = parsear(xml)
    except etree.XMLSyntaxError as exc:
        raise EmisionError(422, f"XML inválido: {exc}")

    raiz = etree.QName(root).localname
    if raiz not in RAICES_ACEPTABLES:
        raise EmisionError(422, f"Tipo de documento no admite mensaje receptor: {raiz}")

    clave = _texto(root, "Clave") or ""
    if not re.fullmatch(r"\d{50}", clave):
        raise EmisionError(422, "El XML no tiene una clave válida")

    receptor_numero = _texto(root, "Receptor/Identificacion/Numero")
    if receptor_numero != emisor.numero_identificacion:
        raise EmisionError(422, "El comprobante no está dirigido a este emisor (la identificación del receptor no coincide)")

    proveedor_numero = _texto(root, "Emisor/Identificacion/Numero")
    if not proveedor_numero:
        raise EmisionError(422, "El XML no indica la identificación del emisor")

    existente = db.scalar(select(DocumentoRecibido).where(
        DocumentoRecibido.emisor_id == emisor.id, DocumentoRecibido.clave == clave
    ))
    if existente:
        raise EmisionError(409, f"El comprobante ya fue registrado (id {existente.id})")

    fecha = None
    if fecha_txt := _texto(root, "FechaEmision"):
        try:
            fecha = datetime.fromisoformat(fecha_txt)
        except ValueError:
            raise EmisionError(422, f"FechaEmision inválida: {fecha_txt}")

    try:
        xml_txt = xml.decode("utf-8")
    except UnicodeDecodeError:
        # Otro encoding declarado (p. ej. ISO-8859-1): se normaliza a UTF-8
        xml_txt = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
    respuesta_txt = None
    if respuesta:
        try:
            resp_root = parsear(respuesta)
        except etree.XMLSyntaxError as exc:
            raise EmisionError(422, f"Respuesta de Hacienda inválida: {exc}")
        if _texto(resp_root, "Clave") != clave:
            raise EmisionError(422, "La respuesta de Hacienda no corresponde a este comprobante")
        respuesta_txt = etree.tostring(resp_root, xml_declaration=True, encoding="UTF-8").decode("utf-8")

    doc = DocumentoRecibido(
        emisor_id=emisor.id,
        clave=clave,
        tipo_documento=RAICES_ACEPTABLES[raiz],
        fecha_emision=fecha,
        proveedor_tipo_identificacion=_texto(root, "Emisor/Identificacion/Tipo"),
        proveedor_identificacion=proveedor_numero,
        proveedor_nombre=(_texto(root, "Emisor/Nombre") or "")[:200],
        moneda=_texto(root, "ResumenFactura/CodigoTipoMoneda/CodigoMoneda") or "CRC",
        tipo_cambio=_decimal(_texto(root, "ResumenFactura/CodigoTipoMoneda/TipoCambio")) or None,
        total_impuesto=_decimal(_texto(root, "ResumenFactura/TotalImpuesto")),
        total_comprobante=_decimal(_texto(root, "ResumenFactura/TotalComprobante")),
        firma_valida=verificar_firma_local(xml_txt, externo=True),
        xml_original=xml_txt,
        xml_respuesta_proveedor=respuesta_txt,
    )
    db.add(doc)
    db.commit()
    return doc


def crear_mensaje_receptor(db: Session, doc: DocumentoRecibido, req: MensajeReceptorRequest) -> DocumentoRecibido:
    """Genera, firma y deja listo para enviar el Mensaje Receptor."""
    if doc.estado in (EstadoFactura.PENDIENTE, EstadoFactura.ENVIADO, EstadoFactura.ACEPTADO):
        raise EmisionError(409, f"El documento ya tiene un mensaje receptor en estado {doc.estado.value}")
    if doc.estado in (EstadoFactura.ERROR_COMUNICACION, EstadoFactura.CONTINGENCIA):
        raise EmisionError(409, "El mensaje receptor ya existe y está pendiente de reenvío; use /reenviar")

    emisor: Emisor = doc.emisor
    try:
        emisores.verificar_listo_para_emitir(emisor)
    except emisores.EmisorIncompletoError as exc:
        raise EmisionError(409, str(exc))
    verificar_saldo(db, emisor)

    tiene_impuesto = doc.total_impuesto > 0
    condicion = req.condicion_impuesto
    acreditar = req.monto_impuesto_acreditar
    gasto = req.monto_gasto_aplicable
    if req.mensaje in ("1", "2") and tiene_impuesto:
        if not condicion:
            raise EmisionError(422, "condicion_impuesto es obligatoria cuando el comprobante tiene impuesto")
        if condicion == "01" and acreditar is None:
            acreditar = doc.total_impuesto
        if acreditar is not None and acreditar > doc.total_impuesto:
            raise EmisionError(422, "monto_impuesto_acreditar no puede ser mayor al impuesto del comprobante")

    tipo = TIPO_DOC_MENSAJE_RECEPTOR[req.mensaje]
    fecha = ahora_cr()
    try:
        numero = siguiente_consecutivo(db, emisor.id, req.sucursal, req.terminal, tipo)
        consecutivo = generar_consecutivo(req.sucursal, req.terminal, tipo, numero)
        xml = generar_mensaje_receptor(
            clave_documento=doc.clave,
            cedula_proveedor=doc.proveedor_identificacion,
            fecha=fecha,
            mensaje=req.mensaje,
            detalle_mensaje=req.detalle_mensaje,
            monto_total_impuesto=q(doc.total_impuesto) if tiene_impuesto else None,
            codigo_actividad=req.codigo_actividad or emisor.codigo_actividad,
            condicion_impuesto=condicion if req.mensaje in ("1", "2") else None,
            monto_impuesto_acreditar=q(acreditar) if acreditar is not None else None,
            monto_gasto_aplicable=q(gasto) if gasto is not None else None,
            total_factura=q(doc.total_comprobante),
            cedula_receptor=emisor.numero_identificacion,
            consecutivo_receptor=consecutivo,
        )
        xml_firmado = firmar_para_emisor(emisor, xml)
        validar_xsd(xml_firmado, tipo)
    except XMLValidacionError as exc:
        db.rollback()
        raise EmisionError(422, str(exc))
    except EmisionError:
        db.rollback()
        raise

    envio = {
        "clave": doc.clave,
        "fecha": a_iso_cr(fecha),
        "emisor": {
            "tipoIdentificacion": doc.proveedor_tipo_identificacion or "02",
            "numeroIdentificacion": doc.proveedor_identificacion,
        },
        "receptor": {
            "tipoIdentificacion": emisor.tipo_identificacion,
            "numeroIdentificacion": emisor.numero_identificacion,
        },
        "consecutivoReceptor": consecutivo,
    }

    doc.mensaje = req.mensaje
    doc.detalle_mensaje = req.detalle_mensaje
    doc.codigo_actividad = req.codigo_actividad or emisor.codigo_actividad
    doc.condicion_impuesto = condicion if req.mensaje in ("1", "2") else None
    doc.monto_impuesto_acreditar = acreditar
    doc.monto_gasto_aplicable = gasto
    doc.consecutivo_receptor = consecutivo
    doc.fecha_mensaje = fecha
    doc.xml_firmado = xml_firmado
    doc.envio_json = envio
    doc.clave_consulta = f"{doc.clave}-{consecutivo}"
    doc.estado = EstadoFactura.PENDIENTE
    doc.estado_hacienda = None
    doc.mensaje_hacienda = None
    doc.xml_respuesta = None
    doc.intentos_envio = 0
    doc.ultimo_envio = None
    restante = cobrar_documento(db, emisor, doc.clave_consulta, tipo, recibido=doc)
    db.commit()
    saldo.despues_de_consumir(emisor, restante)
    return doc
