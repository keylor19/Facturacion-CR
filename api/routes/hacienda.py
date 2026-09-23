"""
Consultas a Hacienda:
  - Servicios públicos: contribuyentes y actividades, exoneraciones, CABYS, tipo de cambio.
  - API de comprobantes con las credenciales del emisor: estado y listado.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.models.database import Emisor
from api.security import autenticar, emisor_actual
from api.services import hacienda_client, hacienda_publico
from api.services.hacienda_auth import HaciendaAuthError

router = APIRouter(prefix="/api/v1/hacienda", tags=["consultas a Hacienda"])


def _publico(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except hacienda_publico.HaciendaPublicoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _privado(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HaciendaAuthError as exc:
        raise HTTPException(status_code=502, detail=f"Autenticación con Hacienda: {exc}")
    except hacienda_client.HaciendaClientError as exc:
        raise HTTPException(status_code=404 if exc.status_code == 404 else 502, detail=str(exc))


# --- Servicios públicos ------------------------------------------------------

@router.get("/contribuyentes/{identificacion}", dependencies=[Depends(autenticar)])
def consultar_contribuyente(identificacion: str):
    """Nombre, régimen, situación tributaria y actividades económicas registradas."""
    return _publico(hacienda_publico.contribuyente, identificacion)


@router.get("/exoneraciones/{autorizacion}", dependencies=[Depends(autenticar)])
def consultar_exoneracion(autorizacion: str):
    """Datos de una exoneración (porcentaje, vigencia, institución, CABYS autorizados)."""
    return _publico(hacienda_publico.exoneracion, autorizacion)


@router.get("/cabys", dependencies=[Depends(autenticar)])
def buscar_cabys(
    q: str | None = Query(default=None, description="Texto a buscar"),
    codigo: str | None = Query(default=None, description="Código CABYS"),
    top: int = Query(default=20, ge=1, le=100),
):
    """Catálogo de bienes y servicios (CABYS) con su tarifa de IVA."""
    return _publico(hacienda_publico.cabys, texto=q, codigo=codigo, top=top)


@router.get("/tipo-cambio/{moneda}", dependencies=[Depends(autenticar)])
def consultar_tipo_cambio(moneda: str):
    """Tipo de cambio de referencia (venta) para USD o EUR."""
    return {"moneda": moneda.upper(), "tipo_cambio": _publico(hacienda_publico.tipo_cambio, moneda)}


# --- API de comprobantes (credenciales del emisor) -----------------------------

@router.get("/estado/{clave}")
def estado_en_hacienda(clave: str, emisor: Emisor = Depends(emisor_actual)):
    """Estado de un comprobante (clave) o mensaje receptor (clave-consecutivo) directamente en Hacienda."""
    data = _privado(hacienda_client.consultar_estado, emisor, clave)
    r = hacienda_client.interpretar_respuesta(data)
    return {"clave": clave, "estado": r["estado"], "mensaje": r["mensaje"], "respuesta_xml": r["xml"]}


@router.get("/comprobantes")
def listar_comprobantes_hacienda(
    response: Response,
    emisor_filtro: str | None = Query(default=None, alias="emisor", description="tipo+identificación, p. ej. 02003101123456"),
    receptor: str | None = Query(default=None, description="tipo+identificación del receptor"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=50),
    emisor: Emisor = Depends(emisor_actual),
):
    """Listado de comprobantes registrados en Hacienda (emitidos o recibidos)."""
    datos, rango = _privado(hacienda_client.listar_comprobantes, emisor, {
        "emisor": emisor_filtro, "receptor": receptor, "offset": offset, "limit": limit,
    })
    if rango:
        response.headers["Content-Range"] = rango
    return datos


@router.get("/comprobantes/{clave}")
def obtener_comprobante_hacienda(clave: str, emisor: Emisor = Depends(emisor_actual)):
    return _privado(hacienda_client.obtener_comprobante, emisor, clave)
