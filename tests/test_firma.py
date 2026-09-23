from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from api.models.schemas import FacturaRequest
from api.services.firma import firmar_xml, verificar_firma_local, inspeccionar_certificado, FirmaError, DS, XADES
from api.services.xml_generator import generar_xml
from api.services.xml_seguro import parsear
from tests.conftest import factura_payload, persona_emisor_prueba, crear_p12, CERT_PASSWORD, P12

CONSECUTIVO = "00100001010000000001"
CLAVE = "506250826003101123456" + CONSECUTIVO + "112345678"


@pytest.fixture(scope="module")
def xml_sin_firmar():
    datos = FacturaRequest(**factura_payload())
    fecha = datetime(2026, 8, 25, 10, 0, tzinfo=ZoneInfo("America/Costa_Rica"))
    xml, _, _ = generar_xml(CLAVE, CONSECUTIVO, fecha, persona_emisor_prueba(), datos)
    return xml


@pytest.fixture(scope="module")
def xml_firmado(xml_sin_firmar):
    return firmar_xml(xml_sin_firmar, P12, CERT_PASSWORD)


def test_firma_verifica(xml_firmado):
    assert verificar_firma_local(xml_firmado)
    assert verificar_firma_local(xml_firmado, externo=True)


def test_estructura_xades(xml_firmado):
    root = parsear(xml_firmado)
    firma = root[-1]
    assert firma.tag == f"{{{DS}}}Signature"  # enveloped, último hijo

    refs = firma.findall(f"{{{DS}}}SignedInfo/{{{DS}}}Reference")
    assert [r.get("URI")[:1] for r in refs] == ["", "#", "#"]
    ref_props = refs[2]
    assert ref_props.get("Type") == "http://uri.etsi.org/01903#SignedProperties"

    props = firma.find(f"{{{DS}}}Object/{{{XADES}}}QualifyingProperties/{{{XADES}}}SignedProperties")
    assert props is not None
    assert "#" + props.get("Id") == ref_props.get("URI")

    ssp = props.find(f"{{{XADES}}}SignedSignatureProperties")
    assert ssp.find(f"{{{XADES}}}SigningTime").text.endswith("-06:00")
    assert ssp.find(f".//{{{XADES}}}CertDigest/{{{DS}}}DigestValue").text
    assert ssp.find(f".//{{{XADES}}}SigPolicyHash/{{{DS}}}DigestValue").text
    assert ssp.find(f".//{{{XADES}}}SigPolicyId/{{{XADES}}}Identifier").text.startswith("https://")


@pytest.mark.parametrize("original,alterado", [
    ("<TotalComprobante>116700.00000<", "<TotalComprobante>1.00000<"),
    ("-06:00</xades:SigningTime>", "-05:00</xades:SigningTime>"),
])
def test_alteracion_invalida_la_firma(xml_firmado, original, alterado):
    assert original in xml_firmado
    assert not verificar_firma_local(xml_firmado.replace(original, alterado, 1))


def test_no_firma_dos_veces(xml_firmado):
    with pytest.raises(FirmaError):
        firmar_xml(xml_firmado, P12, CERT_PASSWORD)


def test_contrasena_incorrecta(xml_sin_firmar):
    with pytest.raises(FirmaError):
        firmar_xml(xml_sin_firmar, P12, "incorrecta")


def test_certificado_vencido(xml_sin_firmar):
    vencido = crear_p12(dias_validez=10, inicio_offset_dias=-30)
    with pytest.raises(FirmaError, match="venció"):
        firmar_xml(xml_sin_firmar, vencido, CERT_PASSWORD)


def test_inspeccionar_certificado():
    info = inspeccionar_certificado(P12, CERT_PASSWORD)
    assert "3101123456" in info["sujeto"]
    assert info["dias_para_vencer"] >= 360
