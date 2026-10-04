"""
Verificación en dos pasos con códigos TOTP (RFC 6238): compatible con Google
Authenticator, Microsoft Authenticator, Authy, 1Password, etc.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from io import StringIO
from urllib.parse import quote

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing

EMISOR_TOTP = "Facturacion CR"
PASO_SEGUNDOS = 30
DIGITOS = 6


def generar_secreto() -> str:
    """Secreto aleatorio de 160 bits en base32 (el formato que usan las apps)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo(secreto: str, paso: int) -> str:
    llave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    digest = hmac.new(llave, struct.pack(">Q", paso), hashlib.sha1).digest()
    desplazamiento = digest[-1] & 0x0F
    numero = struct.unpack(">I", digest[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** DIGITOS).zfill(DIGITOS)


def paso_actual(ahora: float | None = None) -> int:
    return int((ahora if ahora is not None else time.time()) // PASO_SEGUNDOS)


def verificar(secreto: str, codigo: str, ultimo_paso: int | None, ahora: float | None = None) -> int | None:
    """
    Devuelve el paso de tiempo usado si el código es válido (tolerancia de ±30 s)
    y no fue usado antes; si no, None.
    """
    codigo = (codigo or "").strip().replace(" ", "")
    if not codigo.isdigit() or len(codigo) != DIGITOS:
        return None
    actual = paso_actual(ahora)
    for paso in (actual - 1, actual, actual + 1):
        if ultimo_paso is not None and paso <= ultimo_paso:
            continue   # un código ya usado no se puede reutilizar
        if hmac.compare_digest(_codigo(secreto, paso), codigo):
            return paso
    return None


def uri(secreto: str, cuenta: str) -> str:
    etiqueta = quote(f"{EMISOR_TOTP}:{cuenta}")
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(EMISOR_TOTP)}&digits={DIGITOS}&period={PASO_SEGUNDOS}"


def qr_svg(texto: str, tamano: int = 220) -> str:
    """QR en SVG para escanear con la app (sin servicios externos)."""
    widget = QrCodeWidget(texto)
    x1, y1, x2, y2 = widget.getBounds()
    dibujo = Drawing(tamano, tamano, transform=[tamano / (x2 - x1), 0, 0, tamano / (y2 - y1), 0, 0])
    dibujo.add(widget)
    salida = StringIO()
    renderSVG.drawToFile(dibujo, salida)
    return salida.getvalue()
