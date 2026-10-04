"""Inicio de sesión del panel web, verificación en dos pasos y administración de usuarios."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models.database import Emisor, Usuario, get_db
from api.models.schemas import (
    CambioPasswordRequest, CodigoRequest, Desactivar2FARequest, LoginRequest, LoginResponse, UsuarioActualizar,
    UsuarioCrear, UsuarioResponse,
)
from api.security import Principal, autenticar, require_admin
from api.services import auditoria, dos_pasos, limites, saldo, usuarios
from config.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["usuarios y sesiones"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else None
    limites.aplicar(f"login:{ip}", get_settings().LIMITE_LOGIN_MINUTO)
    try:
        token, sesion = usuarios.iniciar_sesion(db, payload.email, payload.password, ip, payload.codigo)
    except usuarios.Requiere2FA as exc:
        if payload.codigo:
            auditoria.registrar(db, "login.2fa_fallido", actor=f"usuario:{payload.email}", request=request)
        raise HTTPException(status_code=401, detail=str(exc), headers={"X-Requiere-2FA": "codigo"})
    except usuarios.LoginError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    auditoria.registrar(db, "login", actor=f"usuario:{sesion.usuario.email}", request=request)
    return LoginResponse(token=token, expira=sesion.expira, usuario=usuarios.a_respuesta(sesion.usuario))


@router.post("/auth/logout", status_code=204)
def logout(credenciales: HTTPAuthorizationCredentials | None = Security(_bearer), db: Session = Depends(get_db)):
    if credenciales:
        usuarios.cerrar_sesion(db, credenciales.credentials)


@router.get("/auth/yo")
def yo(principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    """Usuario actual y empresas a las que tiene acceso (para el panel)."""
    usuario = db.get(Usuario, principal.usuario_id) if principal.usuario_id else None
    empresas = []
    if not principal.falta_2fa:
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
        "debe_activar_2fa": principal.falta_2fa,
    }


def _usuario_panel(principal: Principal, db: Session) -> Usuario:
    if not principal.usuario_id:
        raise HTTPException(status_code=400, detail="Solo aplica a usuarios del panel")
    return db.get(Usuario, principal.usuario_id)


@router.post("/auth/cambiar-password", status_code=204)
def cambiar_password(payload: CambioPasswordRequest, request: Request,
                     principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    usuario = _usuario_panel(principal, db)
    if not usuarios.verificar_password(payload.actual, usuario.password_hash):
        raise HTTPException(status_code=422, detail="La contraseña actual no es correcta")
    usuario.password_hash = usuarios.hash_password(payload.nueva)
    db.commit()
    usuarios.cerrar_todas(db, usuario.id)
    auditoria.registrar(db, "usuario.cambio_password", principal=principal, request=request)


# --- Verificación en dos pasos (app autenticadora) ---------------------------

@router.post("/auth/2fa/iniciar")
def iniciar_2fa(principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    """Genera el secreto y el código QR para escanear con la app autenticadora."""
    usuario = _usuario_panel(principal, db)
    try:
        secreto = usuarios.iniciar_2fa(db, usuario)
    except usuarios.LoginError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    enlace = dos_pasos.uri(secreto, usuario.email)
    return {"secreto": secreto, "uri": enlace, "qr_svg": dos_pasos.qr_svg(enlace)}


@router.post("/auth/2fa/activar", status_code=204)
def activar_2fa(payload: CodigoRequest, request: Request,
                credenciales: HTTPAuthorizationCredentials | None = Security(_bearer),
                principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    """Confirma con el primer código de la app; a partir de aquí se pide en cada inicio de sesión."""
    usuario = _usuario_panel(principal, db)
    limites.aplicar(f"2fa:{usuario.id}", 10)
    try:
        usuarios.activar_2fa(db, usuario, payload.codigo)
    except usuarios.LoginError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Las demás sesiones abiertas (iniciadas sin 2FA) se cierran
    usuarios.cerrar_todas(db, usuario.id, excepto_token=credenciales.credentials if credenciales else None)
    auditoria.registrar(db, "usuario.2fa_activada", principal=principal, request=request)


@router.post("/auth/2fa/desactivar", status_code=204)
def desactivar_2fa(payload: Desactivar2FARequest, request: Request,
                   principal: Principal = Depends(autenticar), db: Session = Depends(get_db)):
    usuario = _usuario_panel(principal, db)
    if usuario.es_admin and get_settings().exige_2fa_admin:
        raise HTTPException(status_code=409, detail="Los administradores deben mantener la verificación en dos pasos")
    limites.aplicar(f"2fa:{usuario.id}", 10)
    try:
        usuarios.desactivar_2fa(db, usuario, payload.password, payload.codigo)
    except usuarios.LoginError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    auditoria.registrar(db, "usuario.2fa_desactivada", principal=principal, request=request)


# --- Administración de usuarios ---------------------------------------------

@router.get("/usuarios", response_model=list[UsuarioResponse], dependencies=[Depends(require_admin)])
def listar_usuarios(db: Session = Depends(get_db)):
    return [usuarios.a_respuesta(u) for u in db.scalars(select(Usuario).order_by(Usuario.email))]


@router.post("/usuarios", response_model=UsuarioResponse, status_code=201)
def crear_usuario(payload: UsuarioCrear, request: Request,
                  principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
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
    auditoria.registrar(db, "usuario.crear", principal=principal, request=request, emisor_id=u.emisor_id,
                        detalle=f"{u.email} ({'administrador' if u.es_admin else 'empresa'})")
    return usuarios.a_respuesta(u)


def _usuario(db: Session, usuario_id: UUID) -> Usuario:
    u = db.get(Usuario, str(usuario_id))
    if u is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return u


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse)
def actualizar_usuario(usuario_id: UUID, payload: UsuarioActualizar, request: Request,
                       principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    u = _usuario(db, usuario_id)
    if payload.activo is False and principal.usuario_id == str(u.id):
        raise HTTPException(status_code=409, detail="No puede desactivar su propio usuario")
    cambios = [c for c in ("nombre", "activo", "password") if getattr(payload, c) is not None]
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
    detalle = f"{u.email}: {', '.join(cambios) or 'sin cambios'}"
    if payload.activo is not None:
        detalle += f" (activo={u.activo})"
    auditoria.registrar(db, "usuario.actualizar", principal=principal, request=request,
                        emisor_id=u.emisor_id, detalle=detalle)
    return usuarios.a_respuesta(u)


@router.delete("/usuarios/{usuario_id}/2fa", status_code=204)
def reiniciar_2fa(usuario_id: UUID, request: Request,
                  principal: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Quita la verificación en dos pasos de un usuario (perdió el teléfono). Cierra sus sesiones."""
    u = _usuario(db, usuario_id)
    usuarios.reiniciar_2fa(db, u)
    usuarios.cerrar_todas(db, u.id)
    auditoria.registrar(db, "usuario.2fa_reiniciada", principal=principal, request=request,
                        emisor_id=u.emisor_id, detalle=u.email)
