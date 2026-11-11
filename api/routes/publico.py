"""Descarga pública de un comprobante con enlace firmado (para enviarlo por WhatsApp)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from api.models.database import EstadoFactura, Factura, get_db
from api.services import enlaces, limites
from api.services.pdf import generar_pdf

router = APIRouter(prefix="/api/v1/publico", tags=["enlaces públicos"])


def _comprobante(request: Request, factura_id: str, firma: str, db: Session) -> Factura:
    ip = request.client.host if request.client else "desconocida"
    limites.aplicar(f"publico:{ip}", 30)
    f = db.get(Factura, factura_id) if len(factura_id) == 36 and enlaces.valida(factura_id, firma) else None
    # Misma respuesta si no existe o si la firma no coincide: no se revela nada
    if f is None or f.estado == EstadoFactura.RECHAZADO:
        raise HTTPException(status_code=404, detail="Enlace no válido o vencido")
    return f


@router.get("/comprobantes/{factura_id}/{firma}/pdf")
def pdf(factura_id: str, firma: str, request: Request, db: Session = Depends(get_db)):
    f = _comprobante(request, factura_id, firma, db)
    return Response(generar_pdf(f), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{f.clave}.pdf"', "Cache-Control": "private, max-age=300"})


@router.get("/comprobantes/{factura_id}/{firma}/xml")
def xml(factura_id: str, firma: str, request: Request, db: Session = Depends(get_db)):
    f = _comprobante(request, factura_id, firma, db)
    return Response(f.xml_firmado or "", media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{f.clave}.xml"'})
