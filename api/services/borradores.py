"""
Proformas y documentos preliminares: comprobantes guardados sin emitir.

Los datos son el mismo cuerpo de POST /facturas. Los totales se calculan con
la misma función que usa la emisión (xml_generator.calcular), así que la
proforma muestra exactamente lo que dirá la factura.
"""
from datetime import timedelta
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy.orm import Session

from api.models.database import Borrador, Emisor, siguiente_consecutivo
from api.models.schemas import BorradorResponse, FacturaRequest
from api.services.fechas import ahora_cr
from api.services.pdf import generar_pdf
from api.services.xml_generator import calcular

DIAS_VIGENCIA_PROFORMA = 15
# Contador propio en la tabla de consecutivos (no choca con los códigos de Hacienda)
CONTADOR_PROFORMA = "PF"


def _mensaje_validacion(exc: ValidationError) -> str:
    partes = []
    for e in exc.errors():
        campo = " → ".join(str(p) for p in e.get("loc", ()))
        msg = str(e.get("msg", "")).removeprefix("Value error, ")
        partes.append(f"{campo}: {msg}" if campo else msg)
    return "\n".join(partes)


def evaluar(datos: dict) -> tuple[FacturaRequest | None, str | None]:
    """(solicitud válida, None) o (None, qué falta para poder emitir)."""
    try:
        req = FacturaRequest.model_validate(datos)
        calcular(req)
    except ValidationError as exc:
        return None, _mensaje_validacion(exc)
    except Exception as exc:  # combinación de montos que el cálculo rechaza
        return None, str(exc)
    return req, None


def aplicar_datos(b: Borrador, datos: dict) -> str | None:
    """Guarda los datos y los campos de búsqueda/totales. Devuelve los errores (None = listo para emitir)."""
    req, errores = evaluar(datos)
    b.datos = datos
    b.tipo_documento = str(datos.get("tipo_documento") or "01")[:2]
    contraparte = datos.get("proveedor") if b.tipo_documento == "08" else datos.get("receptor")
    if not isinstance(contraparte, dict):  # un preliminar puede venir a medias
        contraparte = {}
    b.receptor_nombre = (contraparte.get("nombre") or None) and str(contraparte["nombre"])[:200]
    b.receptor_identificacion = (contraparte.get("numero_identificacion") or None) and str(contraparte["numero_identificacion"])[:20]
    b.receptor_correo = (contraparte.get("correo") or None) and str(contraparte["correo"])[:160]
    b.moneda = str(datos.get("moneda") or "CRC")[:3]
    if req:
        _, tot = calcular(req)
        b.monto_impuesto, b.monto_total = tot.impuesto, tot.comprobante
    else:
        b.monto_impuesto = b.monto_total = None
    return errores


def crear(db: Session, emisor: Emisor, clase: str, datos: dict, vence, creado_por: str | None) -> tuple[Borrador, str | None]:
    b = Borrador(emisor_id=emisor.id, clase=clase, creado_por=creado_por, estado="ABIERTO")
    errores = aplicar_datos(b, datos)
    if clase == "proforma":
        b.numero = siguiente_consecutivo(db, emisor.id, 0, 0, CONTADOR_PROFORMA)
        b.vence = vence or (ahora_cr().date() + timedelta(days=DIAS_VIGENCIA_PROFORMA))
    db.add(b)
    return b, errores


def estado(b: Borrador) -> str:
    if b.estado == "ABIERTO" and b.clase == "proforma" and b.vence and b.vence < ahora_cr().date():
        return "VENCIDO"
    return b.estado


def numero_visible(b: Borrador) -> str:
    return f"PF-{b.numero:06d}" if b.numero else ""


def a_respuesta(b: Borrador, con_datos: bool = False) -> BorradorResponse:
    return BorradorResponse(
        id=str(b.id), clase=b.clase, numero=b.numero, tipo_documento=b.tipo_documento,
        receptor_nombre=b.receptor_nombre, receptor_identificacion=b.receptor_identificacion,
        receptor_correo=b.receptor_correo, moneda=b.moneda, monto_impuesto=b.monto_impuesto,
        monto_total=b.monto_total, vence=b.vence, estado=estado(b),
        factura_id=str(b.factura_id) if b.factura_id else None, creado_por=b.creado_por,
        created_at=b.created_at, updated_at=b.updated_at,
        errores=evaluar(b.datos)[1] if b.estado == "ABIERTO" else None,
        datos=b.datos if con_datos else None,
    )


def pdf_proforma(b: Borrador, emisor: Emisor) -> bytes:
    req, errores = evaluar(b.datos)
    if not req:
        raise ValueError(errores)
    lineas, tot = calcular(req)
    contraparte = req.proveedor if req.tipo_documento == "08" else req.receptor
    detalles = [
        SimpleNamespace(
            linea_numero=ln.numero, codigo_cabys=ln.producto.codigo_cabys, descripcion=ln.producto.descripcion,
            cantidad=ln.producto.cantidad, precio_unitario=ln.producto.precio_unitario, descuento=ln.descuento,
            impuesto_porcentaje=ln.tarifa_iva, monto_total=ln.monto_total_linea,
        )
        for ln in lineas
    ]
    documento = SimpleNamespace(
        emisor=emisor, json_original=req.model_dump(mode="json"), moneda=req.moneda, tipo_documento=req.tipo_documento,
        numero_consecutivo=numero_visible(b), fecha_emision=b.created_at, clave=None,
        receptor_nombre=contraparte.nombre if contraparte else None,
        receptor_identificacion=contraparte.numero_identificacion if contraparte else None,
        receptor_correo=contraparte.correo if contraparte else None,
        condicion_venta=req.condicion_venta, tipo_cambio=req.tipo_cambio, detalles=detalles,
        total_venta=tot.venta, total_descuentos=tot.descuentos, total_gravado=tot.gravado, total_exento=tot.exento,
        total_exonerado=tot.exonerado, monto_impuesto=tot.impuesto, total_otros_cargos=tot.otros_cargos,
        monto_total=tot.comprobante,
    )
    vigencia = [f"Válida hasta el {b.vence:%d/%m/%Y}."] if b.vence else []
    return generar_pdf(documento, titulo_documento="Proforma", notas_extra=vigencia)
