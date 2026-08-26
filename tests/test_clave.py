from datetime import date
from api.services.clave_generator import generar_clave, TIPOS_DOCUMENTO


def test_clave_tiene_50_digitos():
    clave = generar_clave(
        numero_identificacion_emisor="3101123456",
        sucursal=1,
        terminal=1,
        tipo_documento=TIPOS_DOCUMENTO["FACTURA_ELECTRONICA"],
        numero_consecutivo=1,
        fecha_emision=date(2026, 8, 25),
    )
    assert len(clave) == 50
    assert clave.startswith("506")  # código de país
    assert clave[3:9] == "250826"  # ddmmyy


def test_clave_solo_digitos():
    clave = generar_clave(
        numero_identificacion_emisor="3101123456",
        sucursal=1,
        terminal=1,
        tipo_documento=TIPOS_DOCUMENTO["FACTURA_ELECTRONICA"],
        numero_consecutivo=42,
    )
    assert clave.isdigit()


def test_claves_diferentes_para_consecutivos_diferentes():
    c1 = generar_clave("3101123456", 1, 1, TIPOS_DOCUMENTO["FACTURA_ELECTRONICA"], 1)
    c2 = generar_clave("3101123456", 1, 1, TIPOS_DOCUMENTO["FACTURA_ELECTRONICA"], 2)
    assert c1 != c2
