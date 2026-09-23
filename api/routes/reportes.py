"""Reportes para contadores: resumen de IVA y libros de ventas/compras."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from api.models.database import Emisor, get_db
from api.security import emisor_actual
from api.services import reportes

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
