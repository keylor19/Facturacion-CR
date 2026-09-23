from datetime import date

import pytest

from api.services.clave_generator import generar_clave, consecutivo_desde_clave, TIPOS_DOCUMENTO

FE = TIPOS_DOCUMENTO["FACTURA_ELECTRONICA"]
HOY = date(2026, 8, 25)


def test_clave_tiene_50_digitos():
    clave = generar_clave("3101123456", 1, 1, FE, 1, HOY)
    assert len(clave) == 50
    assert clave.isdigit()
    assert clave.startswith("506")  # código de país
    assert clave[3:9] == "250826"  # ddmmyy
    assert clave[9:21] == "003101123456"
    assert clave[41] == "1"  # situación normal


def test_consecutivo_embebido_en_la_clave():
    clave = generar_clave("3101123456", 2, 15, FE, 42, HOY)
    assert consecutivo_desde_clave(clave) == "00200015010000000042"


def test_claves_diferentes_para_consecutivos_diferentes():
    c1 = generar_clave("3101123456", 1, 1, FE, 1, HOY)
    c2 = generar_clave("3101123456", 1, 1, FE, 2, HOY)
    assert c1 != c2


def test_tipos_compra_y_exportacion():
    assert TIPOS_DOCUMENTO["FACTURA_COMPRA"] == "08"
    assert TIPOS_DOCUMENTO["FACTURA_EXPORTACION"] == "09"


@pytest.mark.parametrize("kwargs", [
    dict(numero_identificacion_emisor="31011234AB"),
    dict(sucursal=1000),
    dict(terminal=0),
    dict(tipo_documento="99"),
    dict(numero_consecutivo=10_000_000_000),
])
def test_rechaza_datos_invalidos(kwargs):
    base = dict(numero_identificacion_emisor="3101123456", sucursal=1, terminal=1,
                tipo_documento=FE, numero_consecutivo=1, fecha_emision=HOY)
    base.update(kwargs)
    with pytest.raises(ValueError):
        generar_clave(**base)
