"""
Enlaces públicos para que el cliente descargue su comprobante sin iniciar sesión
(se mandan por WhatsApp o mensaje). El enlace lleva una firma HMAC del id del
comprobante: no se puede adivinar ni cambiar por otro comprobante.
"""
import base64
import hashlib
import hmac
from urllib.parse import quote

from config.settings import get_settings


def _llave() -> bytes:
    s = get_settings()
    base = s.MASTER_KEY or s.JWT_SECRET
    return hmac.new(base.encode(), b"enlace-publico-comprobante", hashlib.sha256).digest()


def firma(factura_id: str) -> str:
    digest = hmac.new(_llave(), str(factura_id).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def valida(factura_id: str, recibida: str) -> bool:
    return hmac.compare_digest(firma(factura_id), recibida or "")


def url_base() -> str:
    s = get_settings()
    return (s.URL_PUBLICA or s.CALLBACK_BASE_URL).rstrip("/")


def url_pdf(factura_id: str) -> str:
    return f"{url_base()}/api/v1/publico/comprobantes/{factura_id}/{firma(factura_id)}/pdf"


def url_xml(factura_id: str) -> str:
    return f"{url_base()}/api/v1/publico/comprobantes/{factura_id}/{firma(factura_id)}/xml"


def whatsapp(telefono: str | None, texto: str) -> str:
    """Enlace wa.me que abre WhatsApp con el mensaje escrito. Sin teléfono, deja elegir el contacto."""
    numero = "".join(c for c in (telefono or "") if c.isdigit())
    if len(numero) == 8:          # número de Costa Rica sin código de país
        numero = "506" + numero
    return f"https://wa.me/{numero}?text={quote(texto)}" if numero else f"https://wa.me/?text={quote(texto)}"
