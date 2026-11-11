"""
Autoservicio: cada persona crea su cuenta y, si va a facturar, inscribe su empresa.

1. Cuenta: con Google o Microsoft (services/oauth.py) o con correo y contraseña (se
   confirma con un enlace al correo). Al crearla elige si va a facturar con su empresa o
   si es contador.
2. Empresa: quien va a facturar inscribe su empresa con todos sus datos. Se verifica en
   Hacienda que la cédula esté inscrita. Queda como dueño, con la prueba gratis
   (N documentos y M días del sistema en línea, en Ventas → Facturación y avisos).
3. Después, en Primeros pasos: llave criptográfica, usuarios que facturan con él y compra
   de documentos y del sistema en línea.
"""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import Emisor, Registro, Suscripcion, Usuario, utcnow
from api.services import administracion, correo, enlaces, hacienda_publico, saldo, usuarios
from config.settings import get_settings

HORAS_ENLACE = 48
TIPOS_CUENTA = ("empresa", "contador")


class RegistroError(Exception):
    def __init__(self, detalle: str, status_code: int = 422):
        super().__init__(detalle)
        self.detalle = detalle
        self.status_code = status_code


def abierto(db: Session) -> bool:
    """La inscripción en línea está abierta (el administrador puede cerrarla)."""
    return bool(administracion.ajustes(db).autoregistro)


def disponible(db: Session) -> bool:
    """Crear cuenta con correo y contraseña (necesita el correo de salida para confirmarla)."""
    return abierto(db) and get_settings().smtp_configurado


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def correo_libre(db: Session, email: str) -> bool:
    return not db.scalar(select(func.count()).select_from(Usuario).where(func.lower(Usuario.email) == email.strip().lower()))


# --- 1. Cuenta ------------------------------------------------------------------------------

def crear_cuenta(db: Session, *, nombre: str, email: str, password: str, tipo: str, ip: str | None) -> str:
    """Crea la cuenta sin activar y devuelve el token del enlace de confirmación."""
    if not disponible(db):
        raise RegistroError("Crear la cuenta con correo todavía no está activado (falta el correo de salida del servicio). "
                            "Intente con Google o Microsoft, o escriba a ventas.", 403)
    if tipo not in TIPOS_CUENTA:
        raise RegistroError("Tipo de cuenta inválido")
    email = email.strip().lower()
    if not correo_libre(db, email):
        raise RegistroError("Ya existe una cuenta con ese correo. Ingrese o use «¿Olvidó su contraseña?».", 409)
    u = Usuario(email=email, nombre=nombre.strip()[:100], password_hash=usuarios.hash_password(password), es_admin=False,
                emisor_id=None, es_contador=tipo == "contador", rol="contador_externo" if tipo == "contador" else "dueno",
                activo=False)
    db.add(u)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(Registro(token_hash=_hash(token), emisor_id=None, usuario_id=u.id,
                    expira=utcnow() + timedelta(hours=HORAS_ENLACE), ip=ip))
    db.commit()
    return token


def mensaje_confirmacion(destino: str, token: str):
    enlace = f"{enlaces.url_base()}/panel/#/confirmar/{token}"
    cuerpo = (
        "¡Hola!\n\nRecibimos su inscripción en el sistema de facturación electrónica.\n\n"
        f"Para activar su cuenta abra este enlace (vence en {HORAS_ENLACE} horas):\n{enlace}\n\n"
        "Si usted no hizo esta inscripción, ignore este correo y no se activará nada.\n"
    )
    return correo.mensaje_simple(destino, "Active su cuenta de facturación electrónica", cuerpo)


def confirmar(db: Session, token: str) -> Usuario:
    """Activa la cuenta. El enlace sirve una sola vez."""
    r = db.scalar(select(Registro).where(Registro.token_hash == _hash(token or "")))
    if r is None or r.confirmado is not None:
        raise RegistroError("El enlace no es válido o ya se usó. Si ya activó la cuenta, ingrese.", 404)
    if r.expira < utcnow():
        raise RegistroError("El enlace venció. Inscríbase de nuevo.", 410)
    usuario = db.get(Usuario, r.usuario_id)
    usuario.activo = True
    if r.emisor_id:   # inscripciones hechas antes de separar cuenta y empresa
        emisor = db.get(Emisor, r.emisor_id)
        emisor.activo = True
        db.commit()
        dar_prueba(db, emisor)
    r.confirmado = utcnow()
    db.commit()
    return usuario


# --- 2. Empresa -------------------------------------------------------------------------------

def datos_hacienda(cedula: str) -> dict:
    """Nombre, tipo de identificación y actividades activas de un contribuyente inscrito."""
    try:
        c = hacienda_publico.contribuyente(cedula)
    except hacienda_publico.HaciendaPublicoError as exc:
        if exc.status_code == 404:
            raise RegistroError("Esa cédula no aparece en Hacienda. Revise que esté bien escrita.")
        raise RegistroError("No pudimos consultar Hacienda en este momento. Intente de nuevo en unos minutos.", 503)
    estado = ((c.get("situacion") or {}).get("estado") or "").lower()
    activas = [a for a in c.get("actividades") or [] if a.get("estado") in ("A", None)]
    if estado != "inscrito" or not activas:
        raise RegistroError("Para facturar electrónicamente la empresa debe estar inscrita en Hacienda con una "
                            "actividad económica activa.")
    return {"nombre": c.get("nombre") or "", "tipo_identificacion": c.get("tipoIdentificacion") or "",
            "actividades": [str(a["codigo"]).zfill(6) for a in activas],
            "principal": str(next((a for a in activas if a.get("tipo") == "P"), activas[0])["codigo"]).zfill(6)}


def inscribir_empresa(db: Session, usuario: Usuario, datos: dict) -> Emisor:
    """La persona (sin empresa todavía) inscribe la suya y queda como dueño, con la prueba gratis."""
    if not abierto(db):
        raise RegistroError("La inscripción en línea está cerrada. Contacte a ventas.", 403)
    if usuario.es_admin or usuario.es_contador:
        raise RegistroError("Esta cuenta no inscribe empresas para facturar", 403)
    if usuario.emisor_id:
        raise RegistroError("Su cuenta ya tiene una empresa", 409)
    cedula = datos["numero_identificacion"]
    if db.scalar(select(func.count()).select_from(Emisor).where(Emisor.numero_identificacion == cedula)):
        raise RegistroError("Esa empresa ya está inscrita. Pídale al dueño que le cree un usuario, o escriba a ventas.", 409)
    hacienda = datos_hacienda(cedula)
    if datos["codigo_actividad"] not in hacienda["actividades"]:
        raise RegistroError(f"La actividad {datos['codigo_actividad']} no está activa para esa cédula en Hacienda")
    e = Emisor(**{**datos, "nombre": hacienda["nombre"][:100] or datos["nombre"],
                  "tipo_identificacion": hacienda["tipo_identificacion"] or datos["tipo_identificacion"]},
               ambiente="stag", facturacion_web=True, activo=True)
    db.add(e)
    db.flush()
    usuario.emisor_id = e.id
    usuario.rol = "dueno"
    db.commit()
    dar_prueba(db, e, usuario)
    return e


def dar_prueba(db: Session, emisor: Emisor, usuario: Usuario | None = None) -> None:
    """Documentos de prueba y el sistema en línea: con mensualidad, queda contratado con sus días gratis."""
    from api.services import mensualidades
    a = administracion.ajustes(db)
    if a.prueba_documentos:
        saldo.acreditar(db, emisor, documentos=a.prueba_documentos, precio=0, nombre="Prueba gratis",
                        dias_vigencia=max(a.prueba_dias, 30), notas="Inscripción en línea", creado_por="registro")
    if mensualidades.se_cobra(db, "facturacion_web"):
        mensualidades.contratar(db, "facturacion_web", emisor=emisor, quien=usuario.email if usuario else "registro")
    elif a.prueba_dias:
        ahora = utcnow()
        db.add(Suscripcion(emisor_id=emisor.id, servicio="facturacion_web", desde=ahora,
                           hasta=ahora + timedelta(days=a.prueba_dias), meses=0, precio=0, moneda="CRC",
                           notas=f"Prueba gratis de {a.prueba_dias} días", creado_por="registro"))
        db.commit()
