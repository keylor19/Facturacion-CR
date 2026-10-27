"""Reportes para contadores: resumen de IVA y libros de ventas/compras."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.models.database import Emisor, get_db
from api.security import emisor_actual
from api.services import descargas, reportes

router = APIRouter(prefix="/api/v1/reportes", tags=["reportes"])

Anio = Query(ge=2018, le=2100)
Mes = Query(ge=1, le=12)


def _csv(contenido: str, nombre: str) -> Response:
    return Response(
        content=contenido.encode("utf-8"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/resumen-iva")
def resumen_iva(anio: int = Anio, mes: int = Mes, emisor: Emisor = Depends(emisor_actual),
                db: Session = Depends(get_db)):
    """Ventas por tarifa, compras por condición de impuesto e IVA neto estimado del mes (insumo D-104)."""
    return reportes.resumen_iva(db, emisor, anio, mes)


@router.get("/ventas.csv")
def libro_ventas(anio: int = Anio, mes: int = Mes, emisor: Emisor = Depends(emisor_actual),
                 db: Session = Depends(get_db)):
    return _csv(reportes.libro_ventas_csv(db, emisor, anio, mes),
                f"ventas-{emisor.numero_identificacion}-{anio:04d}{mes:02d}.csv")


@router.get("/compras.csv")
def libro_compras(anio: int = Anio, mes: int = Mes, emisor: Emisor = Depends(emisor_actual),
                  db: Session = Depends(get_db)):
    return _csv(reportes.libro_compras_csv(db, emisor, anio, mes),
                f"compras-{emisor.numero_identificacion}-{anio:04d}{mes:02d}.csv")


@router.get("/estadisticas")
def estadisticas(anio: int = Anio, mes: int = Mes, emisor: Emisor = Depends(emisor_actual),
                 db: Session = Depends(get_db)):
    """Resumen del mes para el tablero: comprobantes por estado y tipo, ventas e IVA."""
    return reportes.estadisticas(db, emisor, anio, mes)


@router.get("/documentos.zip")
def documentos_zip(
    desde: date, hasta: date,
    emitidos: bool = True, recibidos: bool = True,
    pdf: bool = Query(default=False, description="Incluir el PDF de cada comprobante emitido (más lento)"),
    tipo_documento: str | None = Query(default=None, pattern=r"^\d{2}$", description="Solo un tipo de comprobante emitido"),
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """XML firmados, respuestas de Hacienda, PDF opcional e índice en Excel de un rango de fechas."""
    if hasta < desde:
        raise HTTPException(status_code=422, detail="La fecha final es anterior a la inicial")
    if (hasta - desde).days > 366:
        raise HTTPException(status_code=422, detail="El rango máximo es de un año")
    if not emitidos and not recibidos:
        raise HTTPException(status_code=422, detail="Elija emitidos, recibidos o ambos")
    try:
        archivo = descargas.generar_zip(db, emisor, desde, hasta, emitidos=emitidos, recibidos=recibidos,
                                        con_pdf=pdf, tipo_documento=tipo_documento)
    except descargas.DescargaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    nombre = f"comprobantes-{emisor.numero_identificacion}-{desde:%Y%m%d}-{hasta:%Y%m%d}.zip"
    return StreamingResponse(_trozos(archivo), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _trozos(archivo, tamano: int = 64 * 1024):
    with archivo:
        while trozo := archivo.read(tamano):
            yield trozo
