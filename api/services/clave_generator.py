"""
Generador de la "Clave" (clave numérica de 50 dígitos) que exige Hacienda
para identificar de forma única cada comprobante electrónico.

Estructura oficial (50 dígitos, sin separadores):
  país(3) + fecha(6, ddmmyy) + cédula emisor(12) + consecutivo(20) +
  situación(1) + código de seguridad(8)

El "consecutivo" de 20 dígitos se compone a su vez de:
  sucursal(3) + terminal(5) + tipo de documento(2) + numeración consecutiva(10)

Referencia: Anexo 1 "Especificaciones técnicas..." de Hacienda CR, Art. 3.
"""
import random
from datetime import date


TIPOS_DOCUMENTO = {
    "FACTURA_ELECTRONICA": "01",
    "NOTA_DEBITO": "02",
    "NOTA_CREDITO": "03",
    "TIQUETE_ELECTRONICO": "04",
    "CONFIRMACION_ACEPTACION": "05",
    "CONFIRMACION_ACEPTACION_PARCIAL": "06",
    "CONFIRMACION_RECHAZO": "07",
    "FACTURA_EXPORTACION": "08",
    "FACTURA_COMPRA": "09",
}

SITUACION_NORMAL = "1"
SITUACION_CONTINGENCIA = "2"
SITUACION_SIN_INTERNET = "3"


def _normalizar_cedula(numero_identificacion: str) -> str:
    """La cédula siempre va en 12 dígitos, rellenada con ceros a la izquierda."""
    return numero_identificacion.strip().zfill(12)


def generar_consecutivo(sucursal: int, terminal: int, tipo_documento: str, numero: int) -> str:
    """
    Arma el consecutivo de 20 dígitos.
    sucursal: 001-999 (código de tu sucursal/local)
    terminal: 00001-99999 (caja o punto de emisión)
    tipo_documento: código de 2 dígitos, ver TIPOS_DOCUMENTO
    numero: consecutivo secuencial que tú controlas (nunca debe repetirse
            para el mismo sucursal+terminal+tipo_documento)
    """
    return (
        str(sucursal).zfill(3)
        + str(terminal).zfill(5)
        + tipo_documento
        + str(numero).zfill(10)
    )


def generar_codigo_seguridad() -> str:
    """Código pseudoaleatorio de 8 dígitos exigido en la clave."""
    return str(random.randint(0, 99_999_999)).zfill(8)


def generar_clave(
    numero_identificacion_emisor: str,
    sucursal: int,
    terminal: int,
    tipo_documento: str,
    numero_consecutivo: int,
    situacion: str = SITUACION_NORMAL,
    fecha_emision: date | None = None,
) -> str:
    """
    Devuelve la clave de 50 dígitos lista para usar en el XML y en el envío
    a Hacienda. IMPORTANTE: nunca reuses una clave — es la llave primaria
    del comprobante ante Hacienda y ante tu propia base de datos.
    """
    fecha_emision = fecha_emision or date.today()

    pais = "506"
    fecha = fecha_emision.strftime("%d%m%y")
    cedula = _normalizar_cedula(numero_identificacion_emisor)
    consecutivo = generar_consecutivo(sucursal, terminal, tipo_documento, numero_consecutivo)
    codigo_seguridad = generar_codigo_seguridad()

    clave = pais + fecha + cedula + consecutivo + situacion + codigo_seguridad

    if len(clave) != 50:
        raise ValueError(f"Clave generada con longitud incorrecta: {len(clave)} (debe ser 50)")

    return clave
