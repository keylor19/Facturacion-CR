"""
Autoservicio: crear la cuenta (correo y contraseña, Google o Microsoft) e inscribir la empresa.
Las rutas públicas tienen límite por IP.
"""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from api.models.database import Registro, Usuario, get_db
from api.models.schemas import PATRON_ACTIVIDAD, TipoIdentificacion
from api.security import Principal, autenticar
from api.services import administracion, auditoria, correo, limites, oauth, registro, usuarios
from config.settings import get_settings

router = APIRouter(prefix="/api/v1/registro", tags=["inscripción en línea"])
oauth_router = APIRouter(prefix="/api/v1/auth/oauth", tags=["inscripción en línea"])


class CuentaRequest(BaseModel):
    tipo: Literal["empresa", "contador"] = Field(description="empresa: va a facturar · contador: lleva contabilidades")
    nombre: str = Field(min_length=2, max_length=100, description="Nombre de la persona")
    correo: EmailStr
    password: str = Field(min_length=10, max_length=200)
    acepto_terminos: bool
    sitio_web: str = Field(default="", max_length=200, description="Debe ir vacío (protección contra robots)")


class EmpresaRequest(BaseModel):
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str = Field(min_length=9, max_length=12)
    nombre: str = Field(min_length=2, max_length=100)
    nombre_comercial: str | None = Field(default=None, max_length=80)
    codigo_actividad: str = Field(pattern=PATRON_ACTIVIDAD)
    correo: EmailStr = Field(description="Correo de la empresa (le llegan copias y avisos)")
    telefono: str | None = Field(default=None, pattern=r"^\d{8,20}$")
    provincia: str = Field(pattern=r"^[1-7]$")
    canton: str = Field(pattern=r"^\d{2}$")
    distrito: str = Field(pattern=r"^\d{2}$")
    otras_senas: str = Field(min_length=5, max_length=250)

    @field_validator("numero_identificacion")
    @classmethod
    def solo_digitos(cls, v: str) -> str:
        v = re.sub(r"\D", "", v)
        if not 9 <= len(v) <= 12:
            raise ValueError("La cédula debe tener entre 9 y 12 dígitos")
        return v


class ConfirmarRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


@router.get("")
def informacion(db: Session = Depends(get_db)):
    """Qué formas de inscripción están abiertas y qué incluye la prueba gratis."""
    a = administracion.ajustes(db)
    return {"disponible": registro.abierto(db), "con_correo": registro.disponible(db),
            "proveedores": oauth.disponibles() if registro.abierto(db) else [],
            "prueba_documentos": a.prueba_documentos, "prueba_dias": a.prueba_dias, "contacto_ventas": a.contacto_ventas}


@router.post("", status_code=201)
def crear_cuenta(payload: CuentaRequest, request: Request, db: Session = Depends(get_db)):
    """Crea la cuenta con correo y contraseña; se activa con el enlace que llega al correo."""
    limites.aplicar(f"registro:{_ip(request)}", 5, ventana=3600)
    if payload.sitio_web:   # campo trampa: una persona no lo ve ni lo llena
        return {"ok": True, "correo": payload.correo}
    if not payload.acepto_terminos:
        raise HTTPException(status_code=422, detail="Debe aceptar los términos del servicio")
    try:
        token = registro.crear_cuenta(db, nombre=payload.nombre, email=str(payload.correo), password=payload.password,
                                      tipo=payload.tipo, ip=_ip(request))
    except registro.RegistroError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    try:
        correo.enviar(registro.mensaje_confirmacion(str(payload.correo), token))
    except correo.CorreoError:
        # Sin el correo no se puede confirmar: se deshace para que pueda intentarlo de nuevo
        u = db.query(Usuario).filter(Usuario.email == str(payload.correo).lower()).one()
        db.query(Registro).filter(Registro.usuario_id == u.id).delete()
        db.delete(u)
        db.commit()
        raise HTTPException(status_code=503, detail="No pudimos enviar el correo de activación. Intente más tarde o use Google o Microsoft.")
    auditoria.registrar(db, "registro.cuenta", actor=str(payload.correo), request=request, detalle=payload.tipo)
    return {"ok": True, "correo": payload.correo}


@router.post("/confirmar")
def confirmar(payload: ConfirmarRequest, request: Request, db: Session = Depends(get_db)):
    limites.aplicar(f"registro-confirmar:{_ip(request)}", 20, ventana=3600)
    try:
        usuario = registro.confirmar(db, payload.token)
    except registro.RegistroError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    auditoria.registrar(db, "registro.confirmado", actor=usuario.email, request=request, emisor_id=usuario.emisor_id)
    return {"ok": True, "correo": usuario.email}


@router.post("/empresa", status_code=201)
def inscribir_empresa(payload: EmpresaRequest, request: Request, principal: Principal = Depends(autenticar),
                      db: Session = Depends(get_db)):
    """Quien va a facturar inscribe su empresa (queda como dueño, con la prueba gratis)."""
    if not principal.usuario_id:
        raise HTTPException(status_code=400, detail="Ingrese con su usuario para inscribir la empresa")
    limites.aplicar(f"registro-empresa:{principal.usuario_id}", 10, ventana=3600)
    usuario = db.get(Usuario, principal.usuario_id)
    try:
        e = registro.inscribir_empresa(db, usuario, payload.model_dump())
    except registro.RegistroError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detalle)
    auditoria.registrar(db, "registro.empresa", actor=usuario.email, request=request, emisor_id=e.id,
                        detalle=f"{e.numero_identificacion} {e.nombre}")
    return {"id": e.id, "nombre": e.nombre, "identificacion": e.numero_identificacion}


# --- Google y Microsoft ---------------------------------------------------------------------------

def _al_panel(fragmento: str) -> RedirectResponse:
    respuesta = RedirectResponse(f"/panel/#/{fragmento}", status_code=303)
    respuesta.delete_cookie(oauth.COOKIE, path="/api/v1/auth/oauth")
    return respuesta


@oauth_router.get("/{proveedor}/inicio")
def oauth_inicio(proveedor: Literal["google", "microsoft"], request: Request, tipo: Literal["empresa", "contador"] = "empresa"):
    limites.aplicar(f"oauth:{_ip(request)}", 20)
    try:
        url, nonce = oauth.inicio(proveedor, tipo)
    except oauth.OAuthError as exc:
        return _al_panel(f"oauth-error/{exc}")
    respuesta = RedirectResponse(url, status_code=303)
    respuesta.set_cookie(oauth.COOKIE, nonce, max_age=oauth.VIGENCIA_STATE, httponly=True, samesite="lax",
                         secure=get_settings().AMBIENTE == "prod", path="/api/v1/auth/oauth")
    return respuesta


@oauth_router.get("/{proveedor}/callback")
def oauth_callback(proveedor: Literal["google", "microsoft"], request: Request, code: str = "", state: str = "",
                   error: str = "", db: Session = Depends(get_db)):
    limites.aplicar(f"oauth:{_ip(request)}", 20)
    if error or not code or not state:
        return _al_panel("oauth-error/cancelado")
    try:
        usuario = oauth.completar(db, proveedor, code[:2000], state[:2000], request.cookies.get(oauth.COOKIE))
    except oauth.OAuthError as exc:
        return _al_panel(f"oauth-error/{exc}")
    token, _ = usuarios.crear_sesion(db, usuario, _ip(request))
    auditoria.registrar(db, "login", actor=f"usuario:{usuario.email}", request=request, detalle=f"con {proveedor}")
    # El token va en el fragmento (#): el navegador no lo manda a ningún servidor y el panel lo borra de la barra
    return _al_panel(f"oauth/{token}")
