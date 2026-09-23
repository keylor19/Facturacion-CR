"""
Firma con un certificado REAL emitido por Hacienda (sandbox o producción).
Se omite si no se indica. El certificado nunca se copia al proyecto:

    TEST_P12_PATH=/ruta/certificado.p12  TEST_P12_PIN=1234  (o TEST_P12_PIN_FILE)
"""
import os
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.serialization import pkcs12

from api.models.schemas import FacturaRequest
from api.services.fechas import ahora_cr
from api.services.firma import firmar_xml, inspeccionar_certificado, verificar_firma_local
from api.services.xml_generator import generar_xml, validar_xsd
from tests.conftest import factura_payload, persona_emisor_prueba

RUTA = os.environ.get("TEST_P12_PATH")
if not RUTA or not os.path.isfile(RUTA):
    pytest.skip("Sin certificado real (TEST_P12_PATH)", allow_module_level=True)


def _pin() -> str:
    if os.environ.get("TEST_P12_PIN"):
        return os.environ["TEST_P12_PIN"]
    with open(os.environ["TEST_P12_PIN_FILE"], encoding="utf-8") as f:
        lineas = [x.strip() for x in f.read().splitlines() if x.strip()]
    return next(x for x in reversed(lineas) if x.isdigit())


P12 = open(RUTA, "rb").read()
PIN = _pin()


def test_certificado_es_de_hacienda_y_vigente():
    info = inspeccionar_certificado(P12, PIN)
    assert info["dias_para_vencer"] > 0
    _, cert, cadena = pkcs12.load_key_and_certificates(P12, PIN.encode())
    assert "MINISTERIO DE HACIENDA" in cert.issuer.rfc4514_string().upper()
    assert cert.not_valid_before_utc <= datetime.now(timezone.utc)


def test_firma_con_certificado_real_verifica_y_cumple_xsd(monkeypatch):
    _, cert, _ = pkcs12.load_key_and_certificates(P12, PIN.encode())
    # Emisor = titular del certificado (su identificación viene en el serialNumber: CPF-02-0650-0188)
    serial = [a.value for a in cert.subject if a.oid.dotted_string == "2.5.4.5"][0]
    cedula = "".join(ch for ch in serial if ch.isdigit()).lstrip("0")
    tipo = "01" if serial.upper().startswith("CPF") else "02"
    emisor = persona_emisor_prueba(tipo_identificacion=tipo, numero_identificacion=cedula,
                                   nombre=cert.subject.rfc4514_string().split("CN=")[1].split(",")[0])

    datos = FacturaRequest(**factura_payload())
    consecutivo = "00100001010000000001"
    clave = "506" + ahora_cr().strftime("%d%m%y") + cedula.zfill(12) + consecutivo + "1" + "12345678"
    xml, _, _ = generar_xml(clave, consecutivo, ahora_cr(), emisor, datos)
    firmado = firmar_xml(xml, P12, PIN)
    assert verificar_firma_local(firmado)

    xsd_dir = os.path.join(os.path.dirname(__file__), "..", "xsd")
    if os.path.isfile(os.path.join(xsd_dir, "FacturaElectronica_V4.4.xsd")):
        from config.settings import get_settings
        monkeypatch.setattr(get_settings(), "XSD_DIR", xsd_dir)
        validar_xsd(firmado, "01")
