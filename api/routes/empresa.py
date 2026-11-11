"""La empresa configura lo suyo: certificado, usuario de Hacienda y primeros pasos."""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Emisor, Usuario, UsuarioEmpresa, get_db
from api.models.schemas import CredencialesHaciendaRequest
from api.security import Principal, emisor_actual, permiso
from api.services import arranque, auditoria, emisores
from api.services.cifrado import CifradoError
from api.services.firma import FirmaError

router = APIRouter(prefix="/api/v1/empresa", tags=["mi empresa"])

MAX_BYTES_P12 = 100_000


@router.get("/arranque")
def primeros_pasos(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Lista de lo que falta para facturar."""
    return arranque.pasos(db, emisor)


@router.put("/certificado")
def cargar_certificado(
    archivo: UploadFile = File(..., description="Llave criptográfica .p12 de la empresa"),
    password: str = Form(..., description="PIN de la llave"),
    *, request: Request, principal: Principal = Depends(permiso("configuracion")),
    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db),
):
    """Carga (o reemplaza) la llave criptográfica. Se guarda cifrada."""
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
    auditoria.registrar(db, "emisor.certificado", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=f"vence {emisor.cert_vence:%Y-%m-%d}" if emisor.cert_vence else None)
    return {"ok": True, "sujeto": emisor.cert_sujeto, "vence": emisor.cert_vence, "advertencias": advertencias}


@router.put("/credenciales-hacienda")
def guardar_credenciales(payload: CredencialesHaciendaRequest, request: Request,
                         principal: Principal = Depends(permiso("configuracion")),
                         emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Usuario y contraseña del API de comprobantes de Hacienda. Se guardan cifrados."""
    try:
        emisores.guardar_credenciales(emisor, payload.usuario, payload.password)
    except CifradoError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    db.commit()
    auditoria.registrar(db, "emisor.credenciales_hacienda", principal=principal, request=request, emisor_id=emisor.id)
    return {"ok": True}


@router.post("/probar-conexion", dependencies=[Depends(permiso("configuracion"))])
def probar_conexion(emisor: Emisor = Depends(emisor_actual)):
    """Prueba el usuario de Hacienda y la llave criptográfica."""
    return arranque.probar_conexion(emisor)



# --- Contadores que llevan la contabilidad de la empresa --------------------------------------

@router.get("/contadores", dependencies=[Depends(permiso("usuarios"))])
def contadores(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Contadores que llevan la contabilidad de la empresa (solo ven contabilidad, no facturan)."""
    filas = db.execute(select(Usuario, UsuarioEmpresa.created_at).join(UsuarioEmpresa, UsuarioEmpresa.usuario_id == Usuario.id)
                       .where(UsuarioEmpresa.emisor_id == emisor.id).order_by(Usuario.nombre)).all()
    return [{"id": u.id, "nombre": u.nombre, "email": u.email, "desde": desde, "activo": u.activo} for u, desde in filas]


@router.delete("/contadores/{usuario_id}", status_code=204)
def quitar_contador(usuario_id: UUID, request: Request, principal: Principal = Depends(permiso("usuarios")),
                    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    acceso = db.get(UsuarioEmpresa, (str(usuario_id), emisor.id))
    if acceso is None:
        raise HTTPException(status_code=404, detail="Ese contador no lleva la contabilidad de la empresa")
    db.delete(acceso)
    db.commit()
    auditoria.registrar(db, "contabilidad.acceso_quitado", principal=principal, request=request, emisor_id=emisor.id,
                        detalle=str(usuario_id))
