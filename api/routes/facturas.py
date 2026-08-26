from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.models.database import get_db, Factura, FacturaDetalle, EstadoFactura
from api.models.schemas import FacturaRequest, FacturaResponse, FacturaDetalleResponse
from api.services.clave_generator import generar_clave, TIPOS_DOCUMENTO
from api.services.xml_generator import generar_xml_factura
from api.services.firma import firmar_xml
from config.settings import get_settings
from workers.tasks import enviar_a_hacienda

router = APIRouter(prefix="/api/v1/facturas", tags=["facturas"])
settings = get_settings()


def _siguiente_consecutivo(db: Session) -> int:
    """
    Consecutivo simple basado en el conteo de facturas existentes.
    En producción con múltiples sucursales/terminales, esto debe llevarse
    por sucursal+terminal en una tabla de contadores con lock (SELECT FOR
    UPDATE) para evitar condiciones de carrera si hay concurrencia alta.
    """
    total = db.query(Factura).count()
    return total + 1


@router.post("", response_model=FacturaResponse, status_code=202)
def crear_factura(payload: FacturaRequest, db: Session = Depends(get_db)):
    fecha_emision = datetime.now()
    numero = _siguiente_consecutivo(db)

    clave = generar_clave(
        numero_identificacion_emisor=settings.EMISOR_NUMERO_IDENTIFICACION,
        sucursal=1,
        terminal=1,
        tipo_documento=TIPOS_DOCUMENTO["FACTURA_ELECTRONICA"],
        numero_consecutivo=numero,
        fecha_emision=fecha_emision.date(),
    )

    emisor = {
        "nombre": settings.EMISOR_NOMBRE,
        "tipo_identificacion": settings.EMISOR_TIPO_IDENTIFICACION,
        "numero_identificacion": settings.EMISOR_NUMERO_IDENTIFICACION,
        "provincia": settings.EMISOR_PROVINCIA,
        "canton": settings.EMISOR_CANTON,
        "distrito": settings.EMISOR_DISTRITO,
    }
    receptor = payload.receptor.model_dump()
    productos = [p.model_dump() for p in payload.productos]

    xml_sin_firmar = generar_xml_factura(
        clave=clave,
        numero_consecutivo=clave[21:41],  # el consecutivo va embebido en la clave
        emisor=emisor,
        receptor=receptor,
        productos=productos,
        moneda=payload.moneda,
        condicion_venta=payload.condicion_venta,
        medio_pago=payload.medio_pago,
        fecha_emision=fecha_emision,
    )

    try:
        xml_firmado = firmar_xml(xml_sin_firmar)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error firmando el comprobante: {exc}. Revisa el certificado digital.",
        )

    monto_total = sum(
        float(p["cantidad"]) * float(p["precio_unitario"]) for p in productos
    )
    monto_impuesto = sum(
        float(p["cantidad"]) * float(p["precio_unitario"]) * float(p.get("impuesto_porcentaje", 13)) / 100
        for p in productos
    )

    factura = Factura(
        clave=clave,
        numero_consecutivo=clave[21:41],
        fecha_emision=fecha_emision,
        emisor_nombre=emisor["nombre"],
        emisor_identificacion=emisor["numero_identificacion"],
        emisor_tipo_identificacion=emisor["tipo_identificacion"],
        receptor_nombre=receptor["nombre"],
        receptor_identificacion=receptor["numero_identificacion"],
        receptor_tipo_identificacion=receptor["tipo_identificacion"],
        receptor_correo=receptor.get("correo"),
        monto_total=monto_total,
        monto_impuesto=monto_impuesto,
        moneda=payload.moneda,
        estado=EstadoFactura.PENDIENTE,
        xml_firmado=xml_firmado,
        json_original=payload.model_dump(mode="json"),
    )
    db.add(factura)
    db.flush()  # para obtener factura.id antes del commit

    for i, prod in enumerate(productos, start=1):
        db.add(FacturaDetalle(
            factura_id=factura.id,
            linea_numero=i,
            codigo_producto=prod.get("codigo_producto"),
            descripcion=prod["descripcion"],
            cantidad=prod["cantidad"],
            precio_unitario=prod["precio_unitario"],
            monto_total=float(prod["cantidad"]) * float(prod["precio_unitario"]),
            impuesto_porcentaje=prod.get("impuesto_porcentaje"),
        ))

    db.commit()
    db.refresh(factura)

    # Encolar el envío real a Hacienda — el usuario NO espera esto.
    enviar_a_hacienda.delay(str(factura.id))

    return FacturaResponse(
        factura_id=str(factura.id),
        clave=factura.clave,
        estado=factura.estado.value,
        message="Factura generada, firmada y encolada para envío a Hacienda.",
    )


@router.get("/{factura_id}", response_model=FacturaDetalleResponse)
def obtener_factura(factura_id: str, db: Session = Depends(get_db)):
    factura = db.query(Factura).filter(Factura.id == factura_id).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    return factura


@router.get("", response_model=list[FacturaDetalleResponse])
def listar_facturas(
    estado: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(Factura)
    if estado:
        query = query.filter(Factura.estado == estado)
    return query.order_by(Factura.created_at.desc()).limit(100).all()


@router.post("/{factura_id}/reenviar", response_model=FacturaResponse)
def reenviar_factura(factura_id: str, db: Session = Depends(get_db)):
    factura = db.query(Factura).filter(Factura.id == factura_id).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if factura.estado == EstadoFactura.ACEPTADO:
        raise HTTPException(status_code=409, detail="La factura ya fue aceptada por Hacienda")

    enviar_a_hacienda.delay(str(factura.id))
    return FacturaResponse(
        factura_id=str(factura.id),
        clave=factura.clave,
        estado=factura.estado.value,
        message="Reenvío encolado.",
    )
