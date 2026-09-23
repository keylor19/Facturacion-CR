"""
Cifrado simétrico (Fernet: AES-128-CBC + HMAC-SHA256) de los secretos de
cada emisor: certificado .p12, su contraseña, contraseña de Hacienda y
secreto del webhook. La llave es MASTER_KEY (variable de entorno).
"""
from cryptography.fernet import Fernet, InvalidToken

from config.settings import get_settings


class CifradoError(Exception):
    pass


def _fernet() -> Fernet:
    llave = get_settings().MASTER_KEY
    if not llave:
        raise CifradoError("MASTER_KEY no está configurado (genere uno con: python -m api.cli generar-master-key)")
    try:
        return Fernet(llave.encode())
    except (ValueError, TypeError) as exc:
        raise CifradoError("MASTER_KEY inválido: debe ser una clave Fernet (base64 de 32 bytes)") from exc


def cifrar(dato: bytes | str) -> bytes:
    if isinstance(dato, str):
        dato = dato.encode("utf-8")
    return _fernet().encrypt(dato)


def descifrar(dato: bytes | None) -> bytes | None:
    if dato is None:
        return None
    try:
        return _fernet().decrypt(bytes(dato))
    except InvalidToken as exc:
        raise CifradoError("No se pudo descifrar el secreto (¿cambió MASTER_KEY?)") from exc


def descifrar_texto(dato: bytes | None) -> str | None:
    valor = descifrar(dato)
    return valor.decode("utf-8") if valor is not None else None


def generar_master_key() -> str:
    return Fernet.generate_key().decode()
