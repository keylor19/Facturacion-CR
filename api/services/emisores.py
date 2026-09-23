"""Acceso a los datos y secretos (cifrados) de cada emisor."""
import secrets

from api.models.database import Emisor
from api.models.schemas import EmisorResponse
from api.services import firma
from api.services.cifrado import cifrar, descifrar, descifrar_texto


class EmisorIncompletoError(ValueError):
    pass


def a_respuesta(e: Emisor) -> EmisorResponse:
    return EmisorResponse(
        id=str(e.id),
        tipo_identificacion=e.tipo_identificacion,
        numero_identificacion=e.numero_identificacion,
        nombre=e.nombre,
        nombre_comercial=e.nombre_comercial,
        codigo_actividad=e.codigo_actividad,
        correo=e.correo,
        telefono_codigo_pais=e.telefono_codigo_pais,
        telefono=e.telefono,
        provincia=e.provincia,
        canton=e.canton,
        distrito=e.distrito,
        barrio=e.barrio,
        otras_senas=e.otras_senas,
        proveedor_sistemas=e.proveedor_sistemas,
        registro_fiscal_8707=e.registro_fiscal_8707,
        ambiente=e.ambiente,
        activo=e.activo,
        tiene_credenciales_hacienda=bool(e.hacienda_usuario and e.hacienda_password_cifrado),
        hacienda_usuario=e.hacienda_usuario,
        tiene_certificado=e.cert_p12_cifrado is not None,
        cert_sujeto=e.cert_sujeto,
        cert_vence=e.cert_vence,
        webhook_url=e.webhook_url,
    )


def persona_emisor(e: Emisor) -> dict:
    """Datos del emisor en el formato de nodo persona del generador XML."""
    return {
        "nombre": e.nombre,
        "tipo_identificacion": e.tipo_identificacion,
        "numero_identificacion": e.numero_identificacion,
        "nombre_comercial": e.nombre_comercial,
        "ubicacion": {
            "provincia": e.provincia, "canton": e.canton, "distrito": e.distrito,
            "barrio": e.barrio, "otras_senas": e.otras_senas,
        },
        "telefono_codigo_pais": e.telefono_codigo_pais or "506",
        "telefono": e.telefono,
        "correo": e.correo,
        "codigo_actividad": e.codigo_actividad,
        "proveedor_sistemas": proveedor_sistemas(e),
        "registro_fiscal_8707": e.registro_fiscal_8707,
    }


def proveedor_sistemas(e: Emisor) -> str:
    return e.proveedor_sistemas or e.numero_identificacion


def verificar_listo_para_emitir(e: Emisor) -> None:
    faltantes = []
    if not e.activo:
        raise EmisorIncompletoError("El emisor está inactivo")
    if e.cert_p12_cifrado is None:
        faltantes.append("certificado digital")
    if not (e.hacienda_usuario and e.hacienda_password_cifrado):
        faltantes.append("credenciales de Hacienda")
    if faltantes:
        raise EmisorIncompletoError("Al emisor le falta: " + ", ".join(faltantes))


# --- Certificado ---------------------------------------------------------

def guardar_certificado(e: Emisor, p12: bytes, password: str) -> list[str]:
    """Valida el .p12, lo guarda cifrado y devuelve advertencias (si las hay)."""
    info = firma.inspeccionar_certificado(p12, password)
    advertencias = []
    if info["dias_para_vencer"] < 0:
        raise firma.FirmaError("El certificado está vencido")
    if info["dias_para_vencer"] < 30:
        advertencias.append(f"El certificado vence en {info['dias_para_vencer']} días")
    identificacion = "".join(ch for ch in info["sujeto"] if ch.isdigit())
    if e.numero_identificacion.lstrip("0") not in identificacion:
        advertencias.append(
            "La identificación del emisor no aparece en el sujeto del certificado; verifique que sea el certificado correcto"
        )

    e.cert_p12_cifrado = cifrar(p12)
    e.cert_password_cifrado = cifrar(password)
    e.cert_sujeto = info["sujeto"][:300]
    e.cert_vence = info["vence"]
    return advertencias


def certificado(e: Emisor) -> tuple[bytes, str]:
    if e.cert_p12_cifrado is None:
        raise EmisorIncompletoError("El emisor no tiene certificado digital cargado")
    return descifrar(e.cert_p12_cifrado), descifrar_texto(e.cert_password_cifrado) or ""


# --- Credenciales de Hacienda ----------------------------------------------

def guardar_credenciales(e: Emisor, usuario: str, password: str) -> None:
    e.hacienda_usuario = usuario.strip()
    e.hacienda_password_cifrado = cifrar(password)


def credenciales(e: Emisor) -> tuple[str, str]:
    if not (e.hacienda_usuario and e.hacienda_password_cifrado):
        raise EmisorIncompletoError("El emisor no tiene credenciales de Hacienda")
    return e.hacienda_usuario, descifrar_texto(e.hacienda_password_cifrado)


# --- Webhook ---------------------------------------------------------------

def configurar_webhook(e: Emisor, url: str | None) -> str | None:
    """Guarda la URL; genera un secreto nuevo y lo devuelve (se muestra una sola vez)."""
    if not url:
        e.webhook_url = None
        e.webhook_secret_cifrado = None
        return None
    secreto = "whsec_" + secrets.token_urlsafe(32)
    e.webhook_url = url
    e.webhook_secret_cifrado = cifrar(secreto)
    return secreto


def webhook_secret(e: Emisor) -> str | None:
    return descifrar_texto(e.webhook_secret_cifrado)
