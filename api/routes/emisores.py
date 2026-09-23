"""Administración de emisores (empresas) y llaves de acceso. Requiere llave de administrador."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models.database import ApiKey, Emisor, get_db
from api.models.schemas import (
    ApiKeyCrear, ApiKeyResponse, CredencialesHaciendaRequest, EmisorActualizar, EmisorCrear,
    EmisorResponse, WebhookRequest,
)
from api.security import crear_api_key, require_admin
from api.services import emisores, saldo
from api.services.cifrado import CifradoError
from api.services.firma import FirmaError, inspeccionar_certificado
from api.services.hacienda_auth import HaciendaAuthError, obtener_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["administración"], dependencies=[Depends(require_admin)])

MAX_BYTES_P12 = 100_000


def _emisor(db: Session, emisor_id: UUID) -> Emisor:
    emisor = db.get(Emisor, str(emisor_id))
    if not emisor:
        raise HTTPException(status_code=404, detail="Emisor no encontrado")
    return emisor


def _key_respuesta(k: ApiKey, llave: str | None = None) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(k.id), nombre=k.nombre, prefijo=k.prefijo, es_admin=k.es_admin,
        emisor_id=str(k.emisor_id) if k.emisor_id else None, activa=k.activa,
        ultimo_uso=k.ultimo_uso, created_at=k.created_at, api_key=llave,
    )


# --- Emisores --------------------------------------------------------------

@router.post("/emisores", response_model=EmisorResponse, status_code=201)
def crear_emisor(payload: EmisorCrear, db: Session = Depends(get_db)):
    emisor = Emisor(**payload.model_dump())
    db.add(emisor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un emisor con esa identificación")
    return emisores.a_respuesta(emisor)


@router.get("/emisores", response_model=list[EmisorResponse])
def listar_emisores(activo: bool | None = None, db: Session = Depends(get_db)):
    query = select(Emisor).order_by(Emisor.nombre)
    if activo is not None:
        query = query.where(Emisor.activo.is_(activo))
    lista = list(db.scalars(query))
    saldos = saldo.disponibles_por_emisor(db, [e.id for e in lista]) if saldo.control_activo() else {}
    return [emisores.a_respuesta(e).model_copy(update={"saldo_documentos": saldos.get(e.id)}) for e in lista]


@router.get("/emisores/{emisor_id}", response_model=EmisorResponse)
def obtener_emisor(emisor_id: UUID, db: Session = Depends(get_db)):
    return emisores.a_respuesta(_emisor(db, emisor_id))


@router.patch("/emisores/{emisor_id}", response_model=EmisorResponse)
def actualizar_emisor(emisor_id: UUID, payload: EmisorActualizar, db: Session = Depends(get_db)):
    emisor = _emisor(db, emisor_id)
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(emisor, campo, valor)
    db.commit()
    return emisores.a_respuesta(emisor)


@router.put("/emisores/{emisor_id}/certificado")
def cargar_certificado(
    emisor_id: UUID,
    archivo: UploadFile = File(..., description="Certificado .p12 del emisor"),
    password: str = Form(..., description="PIN del certificado"),
    db: Session = Depends(get_db),
):
    """Carga (o reemplaza) el certificado digital. Se guarda cifrado."""
    emisor = _emisor(db, emisor_id)
    contenido = archivo.file.read(MAX_BYTES_P12 + 1)
    if len(contenido) > MAX_BYTES_P12:
        raise HTTPException(status_code=413, detail="El archivo es demasiado grande para ser un .p12")
    try:
        advertencias = emisores.guardar_certificado(emisor, contenido, password)
    except FirmaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except CifradoError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    db.commit()
    return {"ok": True, "sujeto": emisor.cert_sujeto, "vence": emisor.cert_vence, "advertencias": advertencias}


@router.put("/emisores/{emisor_id}/credenciales-hacienda")
def guardar_credenciales(emisor_id: UUID, payload: CredencialesHaciendaRequest, db: Session = Depends(get_db)):
    """Usuario y contraseña del API de comprobantes (ATV). Se guardan cifrados."""
    emisor = _emisor(db, emisor_id)
    try:
        emisores.guardar_credenciales(emisor, payload.usuario, payload.password)
    except CifradoError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    db.commit()
    return {"ok": True}


@router.post("/emisores/{emisor_id}/probar-conexion")
def probar_conexion(emisor_id: UUID, db: Session = Depends(get_db)):
    """Verifica credenciales de Hacienda (obtiene un token) y el certificado."""
    emisor = _emisor(db, emisor_id)
    resultado = {"ambiente": emisor.ambiente}
    try:
        obtener_token(emisor, forzar=True)
        resultado["hacienda"] = "ok"
    except HaciendaAuthError as exc:
        resultado["hacienda"] = f"error: {exc}"
    try:
        p12, password = emisores.certificado(emisor)
        info = inspeccionar_certificado(p12, password)
        resultado["certificado"] = "ok" if info["dias_para_vencer"] >= 0 else "vencido"
        resultado["certificado_dias_para_vencer"] = info["dias_para_vencer"]
    except (emisores.EmisorIncompletoError, FirmaError, CifradoError) as exc:
        resultado["certificado"] = f"error: {exc}"
    resultado["ok"] = resultado.get("hacienda") == "ok" and resultado.get("certificado") == "ok"
    return resultado


@router.put("/emisores/{emisor_id}/webhook")
def configurar_webhook(emisor_id: UUID, payload: WebhookRequest, db: Session = Depends(get_db)):
    """
    Configura la URL que recibe los cambios de estado. Devuelve el secreto
    para validar la firma HMAC (se muestra una sola vez).
    """
    emisor = _emisor(db, emisor_id)
    url = str(payload.url) if payload.url else None
    if url and not url.startswith("https://"):
        raise HTTPException(status_code=422, detail="El webhook debe usar HTTPS")
    secreto = emisores.configurar_webhook(emisor, url)
    db.commit()
    return {"ok": True, "webhook_url": url, "secreto": secreto}


# --- API keys --------------------------------------------------------------

@router.post("/api-keys", response_model=ApiKeyResponse, status_code=201)
def crear_llave(payload: ApiKeyCrear, db: Session = Depends(get_db)):
    """Crea una llave. La llave completa solo se muestra en esta respuesta."""
    if payload.emisor_id:
        try:
            _emisor(db, UUID(payload.emisor_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="emisor_id inválido")
    registro, llave = crear_api_key(db, payload.nombre, payload.es_admin, payload.emisor_id)
    return _key_respuesta(registro, llave)


@router.get("/api-keys", response_model=list[ApiKeyResponse])
def listar_llaves(emisor_id: UUID | None = None, db: Session = Depends(get_db)):
    query = select(ApiKey).order_by(ApiKey.created_at.desc())
    if emisor_id:
        query = query.where(ApiKey.emisor_id == str(emisor_id))
    return [_key_respuesta(k) for k in db.scalars(query)]


@router.delete("/api-keys/{key_id}", status_code=204)
def revocar_llave(key_id: UUID, db: Session = Depends(get_db)):
    registro = db.get(ApiKey, str(key_id))
    if not registro:
        raise HTTPException(status_code=404, detail="Llave no encontrada")
    registro.activa = False
    db.commit()
