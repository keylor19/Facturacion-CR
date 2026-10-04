"""
Valida cada tipo de documento firmado contra los XSD OFICIALES v4.4.
Se omite si no están descargados (python -m api.cli descargar-xsd).
Carpeta: XSD_TEST_DIR o ./xsd
"""
import os
from datetime import timedelta
from decimal import Decimal

import pytest

from api.models.schemas import FacturaRequest
from api.services import xml_generator
from api.services.fechas import ahora_cr
from api.services.firma import firmar_xml
from api.services.xml_generator import generar_xml, generar_mensaje_receptor, validar_xsd
from tests.conftest import factura_payload, persona_emisor_prueba, P12, CERT_PASSWORD

XSD_DIR = os.environ.get("XSD_TEST_DIR") or os.path.join(os.path.dirname(__file__), "..", "xsd")
if not os.path.isfile(os.path.join(XSD_DIR, "FacturaElectronica_V4.4.xsd")):
    pytest.skip("XSD oficiales no descargados (python -m api.cli descargar-xsd)", allow_module_level=True)

REF = {"tipo_documento": "01", "numero": "5" * 50, "fecha_emision": "2026-08-20T10:00:00", "codigo": "01", "razon": "Anula"}
EXO = {"tipo_documento": "04", "numero_documento": "AL-00012345-24", "nombre_institucion": "01",
       "fecha_emision": "2026-01-10T08:00:00", "tarifa_exonerada": "6.5"}
PROVEEDOR = {"nombre": "Proveedor", "tipo_identificacion": "01", "numero_identificacion": "206540321",
             "ubicacion": {"provincia": "2", "canton": "01", "distrito": "01", "otras_senas": "Alajuela"}}


def _caso(nombre):
    p = factura_payload()
    if nombre == "factura_completa":
        p.update(codigo_actividad_receptor="620100", condicion_venta="02", plazo_credito=30, moneda="USD",
                 tipo_cambio="451.86", notas="Gracias", medios_pago=[{"tipo": "04"}],
                 otros_cargos=[{"tipo_documento": "06", "detalle": "Servicio 10%", "porcentaje": "10"}])
    elif nombre == "exoneracion":
        p["productos"][0]["exoneracion"] = EXO
    elif nombre == "selectivo":
        p["productos"] = [{"codigo_cabys": "2211000000100", "descripcion": "Bebida", "cantidad": "1",
                           "precio_unitario": "1000", "impuestos": [{"codigo": "02", "tarifa": "10"},
                                                                    {"codigo": "01", "codigo_tarifa_iva": "08"}]}]
    elif nombre == "tiquete":
        p.update(tipo_documento="04", receptor=None)
    elif nombre == "nota_credito":
        p.update(tipo_documento="03", referencia=REF)
    elif nombre == "nota_debito":
        p.update(tipo_documento="02", referencia=dict(REF, codigo="04"))
    elif nombre == "compra":
        p.update(tipo_documento="08", receptor=None, proveedor=PROVEEDOR,
                 referencia=dict(REF, tipo_documento="14", numero="00100001010000000001", codigo="04"))
    elif nombre == "exportacion":
        p.update(tipo_documento="09", moneda="USD", tipo_cambio="451.86",
                 receptor={"nombre": "ACME", "identificacion_extranjero": "US123", "otras_senas_extranjero": "Miami"})
        p["productos"][1]["partida_arancelaria"] = "490199000000"
    return FacturaRequest(**p)


@pytest.fixture(autouse=True)
def _xsd_dir(monkeypatch):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "XSD_DIR", XSD_DIR)


@pytest.mark.parametrize("nombre", ["factura", "factura_completa", "exoneracion", "selectivo", "tiquete",
                                    "nota_credito", "nota_debito", "compra", "exportacion"])
def test_documento_cumple_xsd_oficial(nombre):
    datos = _caso(nombre)
    consecutivo = f"00100001{datos.tipo_documento}0000000001"
    clave = "506230926003101123456" + consecutivo + "112345678"
    xml, _, _ = generar_xml(clave, consecutivo, ahora_cr(), persona_emisor_prueba(), datos)
    validar_xsd(firmar_xml(xml, P12, CERT_PASSWORD), datos.tipo_documento)


@pytest.mark.parametrize("mensaje", ["1", "2", "3"])
def test_mensaje_receptor_cumple_xsd_oficial(mensaje):
    tipo = xml_generator.TIPO_DOC_MENSAJE_RECEPTOR[mensaje]
    xml = generar_mensaje_receptor(
        "5" * 50, "3101777777", ahora_cr(), mensaje, None if mensaje == "1" else "Motivo",
        Decimal("130"), "620100", "01" if mensaje != "3" else None,
        Decimal("130") if mensaje != "3" else None, None, Decimal("1130"), "3101123456",
        f"00100001{tipo}0000000001",
    )
    validar_xsd(firmar_xml(xml, P12, CERT_PASSWORD), tipo)


# --- IVA especial, contingencia y recibo de pago -------------------------------

HACE_TRES_DIAS = (ahora_cr() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")


def _linea(**extra):
    base = {"codigo_cabys": "2399999009900", "descripcion": "Producto", "cantidad": "2", "precio_unitario": "1000"}
    base.update(extra)
    return base


CASOS_ESPECIALES = {
    "no_sujeto": dict(productos=[_linea(no_sujeto=True), _linea()]),
    "iva_cobrado_fabrica_01": dict(productos=[_linea(iva_cobrado_fabrica="01")]),
    "iva_cobrado_fabrica_02": dict(productos=[_linea(iva_cobrado_fabrica="02")]),
    "impuesto_asumido": dict(productos=[_linea(impuesto_asumido_emisor=True), _linea()]),
    "bienes_usados": dict(productos=[_linea(impuestos=[{"codigo": "08", "codigo_tarifa_iva": "08", "factor_calculo_iva": "0.05"}])]),
    "bebida_alcoholica": dict(productos=[_linea(impuestos=[
        {"codigo": "04", "monto": "150", "datos_especificos": {"cantidad_unidad_medida": "0.75", "porcentaje": "12",
                                                                 "proporcion": "0.09", "impuesto_unidad": "833.33"}},
        {"codigo": "01", "codigo_tarifa_iva": "08"}])]),
    "iva_devuelto": dict(tipo_documento="04", receptor=None, iva_devuelto="100",
                         medios_pago=[{"tipo": "02"}]),
    "contingencia": dict(situacion="2", fecha_emision=HACE_TRES_DIAS, referencia={
        "tipo_documento": "08", "numero": "123", "fecha_emision": HACE_TRES_DIAS, "codigo": "05",
        "razon": "Sustituye comprobante provisional"}),
    "sin_internet": dict(situacion="3", fecha_emision=HACE_TRES_DIAS),
}


@pytest.mark.parametrize("nombre", list(CASOS_ESPECIALES))
def test_iva_especial_y_contingencia_cumplen_xsd(nombre):
    datos = FacturaRequest(**factura_payload(**CASOS_ESPECIALES[nombre]))
    consecutivo = f"00100001{datos.tipo_documento}0000000001"
    clave = "506230926003101123456" + consecutivo + datos.situacion + "12345678"
    xml, _, _ = generar_xml(clave, consecutivo, ahora_cr(), persona_emisor_prueba(registro_fiscal_8707="123456"), datos)
    validar_xsd(firmar_xml(xml, P12, CERT_PASSWORD), datos.tipo_documento)


def test_recibo_pago_cumple_xsd():
    from api.models.schemas import MedioPagoRequest
    from api.services.xml_generator import LineaRecibo, generar_recibo_pago

    xml = generar_recibo_pago(
        "506230926003101123456" + "00100001100000000001" + "112345678", "00100001100000000001", ahora_cr(),
        persona_emisor_prueba(), {"nombre": "Ministerio X", "tipo_identificacion": "02", "numero_identificacion": "2100042002"},
        "11", "CRC", None,
        [LineaRecibo("Pago factura (IVA 13%)", Decimal("1000"), "08", Decimal("13"), Decimal("130"))],
        [MedioPagoRequest(tipo="04")],
        {"tipo_documento": "01", "numero": "5" * 50, "fecha_emision": ahora_cr(), "codigo": "04", "razon": "Pago"},
    )
    validar_xsd(firmar_xml(xml, P12, CERT_PASSWORD), "10")
