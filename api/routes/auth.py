"""Inicio de sesión del panel web y administración de usuarios."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models.database import Emisor, Usuario, get_db
from api.models.schemas import (
    CambioPasswordRequest, LoginRequest, LoginResponse, UsuarioActualizar, UsuarioCrear, UsuarioResponse,
)
from api.security import Principal, autenticar, require_admin
from api.services import limites, saldo, usuarios
from config.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["usuarios y sesiones"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else None
    limites.aplicar(f"login:{ip}", get_settings().LIMITE_LOGIN_MINUTO)
    try:
        token, sesion = usuarios.iniciar_sesion(db, payload.email, payload.password, ip)
    except usuarios.LoginError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return LoginResponse(token=token, expira=sesion.expira, usuario=usuarios.a_respuesta(sesion.usuario))


@router.post("/auth/logout", status_code=204)
def logout(credenciales: HTTPAuthorizationCredentials | None = Security(_bearer), db: Session = Depends(get_db)):
    if credenciales:
        usuarios.cerrar_sesion(db, credenciales.credentials)


@router.get("/auth/yo")
def yo(principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    """Usuario actual y empresas a las que tiene acceso (para el panel)."""
    usuario = db.get(Usuario, principal.usuario_id) if principal.usuario_id else None
    query = select(Emisor).where(Emisor.activo.is_(True)).order_by(Emisor.nombre)
    if principal.emisor_id:
        query = query.where(Emisor.id == principal.emisor_id)
    lista = list(db.scalars(query))
    saldos = saldo.disponibles_por_emisor(db, [e.id for e in lista]) if saldo.control_activo() else {}
    empresas = [
        {"id": str(e.id), "nombre": e.nombre, "numero_identificacion": e.numero_identificacion,
         "ambiente": e.ambiente, "tiene_certificado": e.cert_p12_cifrado is not None,
         "cert_vence": e.cert_vence, "saldo_documentos": saldos.get(e.id)}
        for e in lista
    ]
    return {
        "usuario": usuarios.a_respuesta(usuario) if usuario else None,
        "es_admin": principal.es_admin,
        "empresas": empresas,
        "control_saldo": saldo.control_activo(),
        "saldo_alerta": get_settings().SALDO_ALERTA_DOCUMENTOS,
    }


@router.post("/auth/cambiar-password", status_code=204)
def cambiar_password(payload: CambioPasswordRequest, principal: Principal = Depends(autenticar),
                     db: Session = Depends(get_db)):
    if not principal.usuario_id:
        raise HTTPException(status_code=400, detail="Solo aplica a usuarios del panel")
    usuario = db.get(Usuario, principal.usuario_id)
    if not usuarios.verificar_password(payload.actual, usuario.password_hash):
        raise HTTPException(status_code=422, detail="La contraseña actual no es correcta")
    usuario.password_hash = usuarios.hash_password(payload.nueva)
    db.commit()
    usuarios.cerrar_todas(db, usuario.id)


# --- Administración de usuarios ---------------------------------------------

@router.get("/usuarios", response_model=list[UsuarioResponse], dependencies=[Depends(require_admin)])
def listar_usuarios(db: Session = Depends(get_db)):
    return [usuarios.a_respuesta(u) for u in db.scalars(select(Usuario).order_by(Usuario.email))]


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201, dependencies=[Depends(require_admin)])
def crear_usuario(payload: UsuarioCrear, db: Session = Depends(get_db)):
    if payload.emisor_id:
        try:
            UUID(payload.emisor_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="emisor_id inválido")
        if db.get(Emisor, payload.emisor_id) is None:
            raise HTTPException(status_code=404, detail="Emisor no encontrado")
    try:
        u = usuarios.crear_usuario(db, payload.email, payload.nombre, payload.password,
                                   payload.es_admin, payload.emisor_id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo")
    return usuarios.a_respuesta(u)


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse)
def actualizar_usuario(usuario_id: UUID, payload: UsuarioActualizar,
                       principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(Usuario, str(usuario_id))
    if u is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if payload.activo is False and principal.usuario_id == str(u.id):
        raise HTTPException(status_code=409, detail="No puede desactivar su propio usuario")
    if payload.nombre is not None:
        u.nombre = payload.nombre
    if payload.activo is not None:
        u.activo = payload.activo
    if payload.password is not None:
        u.password_hash = usuarios.hash_password(payload.password)
        u.intentos_fallidos = 0
        u.bloqueado_hasta = None
    db.commit()
    if payload.password is not None or payload.activo is False:
        usuarios.cerrar_todas(db, u.id)
    return usuarios.a_respuesta(u)
