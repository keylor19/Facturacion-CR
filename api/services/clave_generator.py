"""
Generador de la "Clave" (clave numérica de 50 dígitos) que exige Hacienda
para identificar de forma única cada comprobante electrónico.

Estructura oficial (50 dígitos, sin separadores):
  país(3) + fecha(6, ddmmyy) + cédula emisor(12) + consecutivo(20) +
  situación(1) + código de seguridad(8)

El "consecutivo" de 20 dígitos se compone a su vez de:
  sucursal(3) + terminal(5) + tipo de documento(2) + numeración consecutiva(10)

Referencia: Anexos y estructuras v4.4 de Hacienda CR.
"""
import secrets
from datetime import date


TIPOS_DOCUMENTO = {
    "FACTURA_ELECTRONICA": "01",
    "NOTA_DEBITO": "02",
    "NOTA_CREDITO": "03",
    "TIQUETE_ELECTRONICO": "04",
    "CONFIRMACION_ACEPTACION": "05",
    "CONFIRMACION_ACEPTACION_PARCIAL": "06",
    "CONFIRMACION_RECHAZO": "07",
    "FACTURA_COMPRA": "08",
    "FACTURA_EXPORTACION": "09",
    "RECIBO_PAGO": "10",
}

SITUACION_NORMAL = "1"
SITUACION_CONTINGENCIA = "2"
SITUACION_SIN_INTERNET = "3"


def _normalizar_cedula(numero_identificacion: str) -> str:
    """La cédula siempre va en 12 dígitos, rellenada con ceros a la izquierda."""
    cedula = numero_identificacion.strip()
    if not cedula.isdigit() or len(cedula) > 12:
        raise ValueError(f"Identificación del emisor inválida: {numero_identificacion!r}")
    return cedula.zfill(12)


def generar_consecutivo(sucursal: int, terminal: int, tipo_documento: str, numero: int) -> str:
    """
    Arma el consecutivo de 20 dígitos.
    sucursal: 1-999 (código de tu sucursal/local)
    terminal: 1-99999 (caja o punto de emisión)
    tipo_documento: código de 2 dígitos, ver TIPOS_DOCUMENTO
    numero: consecutivo secuencial (nunca debe repetirse para el mismo
            sucursal+terminal+tipo_documento)
    """
    if not 1 <= sucursal <= 999:
        raise ValueError("La sucursal debe estar entre 1 y 999")
    if not 1 <= terminal <= 99_999:
        raise ValueError("La terminal debe estar entre 1 y 99999")
    if tipo_documento not in TIPOS_DOCUMENTO.values():
        raise ValueError(f"Tipo de documento inválido: {tipo_documento!r}")
    if not 1 <= numero <= 9_999_999_999:
        raise ValueError("El número consecutivo debe estar entre 1 y 9999999999")

    return (
        str(sucursal).zfill(3)
        + str(terminal).zfill(5)
        + tipo_documento
        + str(numero).zfill(10)
    )


def generar_codigo_seguridad() -> str:
    """Código aleatorio de 8 dígitos (criptográficamente seguro) exigido en la clave."""
    return str(secrets.randbelow(100_000_000)).zfill(8)


def generar_clave(
    numero_identificacion_emisor: str,
    sucursal: int,
    terminal: int,
    tipo_documento: str,
    numero_consecutivo: int,
    fecha_emision: date,
    situacion: str = SITUACION_NORMAL,
) -> str:
    """
    Devuelve la clave de 50 dígitos lista para usar en el XML y en el envío
    a Hacienda. `fecha_emision` debe ser la fecha en hora de Costa Rica.
    IMPORTANTE: nunca reuses una clave — es la llave primaria del
    comprobante ante Hacienda y ante tu propia base de datos.
    """
    if situacion not in (SITUACION_NORMAL, SITUACION_CONTINGENCIA, SITUACION_SIN_INTERNET):
        raise ValueError(f"Situación inválida: {situacion!r}")

    pais = "506"
    fecha = fecha_emision.strftime("%d%m%y")
    cedula = _normalizar_cedula(numero_identificacion_emisor)
    consecutivo = generar_consecutivo(sucursal, terminal, tipo_documento, numero_consecutivo)
    codigo_seguridad = generar_codigo_seguridad()

    clave = pais + fecha + cedula + consecutivo + situacion + codigo_seguridad

    if len(clave) != 50:
        raise ValueError(f"Clave generada con longitud incorrecta: {len(clave)} (debe ser 50)")

    return clave


def consecutivo_desde_clave(clave: str) -> str:
    """Extrae el consecutivo de 20 dígitos embebido en la clave."""
    return clave[21:41]
