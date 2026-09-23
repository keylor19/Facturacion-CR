"""Comprobantes recibidos de proveedores y Mensaje Receptor."""
import base64
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from lxml import etree

from api.models.database import DocumentoRecibido
from api.models.schemas import FacturaRequest
from api.services.firma import firmar_xml
from api.services.xml_generator import generar_xml
from api.services.xml_seguro import parsear
from tests.conftest import factura_payload, persona_emisor_prueba, crear_p12, CERT_PASSWORD

CLAVE_PROVEEDOR = "506250826003101777777" + "00100001010000000099" + "112345678"


def xml_de_proveedor(receptor_numero="3101123456", clave=CLAVE_PROVEEDOR, receptor_tipo="02") -> bytes:
    """Factura firmada por un proveedor (3101777777) dirigida a nuestro emisor."""
    receptor = {"nombre": "Pruebas S.A.", "tipo_identificacion": receptor_tipo, "numero_identificacion": receptor_numero}
    datos = FacturaRequest(**factura_payload(receptor=receptor))
    proveedor = persona_emisor_prueba(nombre="Proveedor S.A.", numero_identificacion="3101777777",
                                      proveedor_sistemas="3101777777")
    fecha = datetime(2026, 8, 25, 10, 0, tzinfo=ZoneInfo("America/Costa_Rica"))
    xml, _, _ = generar_xml(clave, clave[21:41], fecha, proveedor, datos)
    return firmar_xml(xml, crear_p12("3101777777"), CERT_PASSWORD).encode()


def _registrar(client, xml: bytes):
    return client.post("/api/v1/recepcion", json={"xml_base64": base64.b64encode(xml).decode()})


def test_registrar_y_aceptar(client, db, cola):
    r = _registrar(client, xml_de_proveedor())
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["proveedor_identificacion"] == "3101777777"
    assert doc["firma_valida"] is True
    assert float(doc["total_impuesto"]) == 11700
    assert doc["estado"] is None

    assert len(client.get("/api/v1/recepcion?pendientes=true").json()) == 1

    # Con impuesto hay que indicar la condición
    assert client.post(f"/api/v1/recepcion/{doc['id']}/mensaje", json={"mensaje": "1"}).status_code == 422

    r = client.post(f"/api/v1/recepcion/{doc['id']}/mensaje", json={"mensaje": "1", "condicion_impuesto": "01"})
    assert r.status_code == 202, r.text
    assert r.json()["estado"] == "PENDIENTE"
    assert r.json()["consecutivo_receptor"] == "00100001050000000001"
    assert float(r.json()["monto_impuesto_acreditar"]) == 11700
    assert ("enviar_documento", ("recibido", doc["id"])) in cola

    d = db.get(DocumentoRecibido, doc["id"])
    assert d.clave_consulta == f"{CLAVE_PROVEEDOR}-00100001050000000001"
    assert d.envio_json["consecutivoReceptor"] == "00100001050000000001"
    assert d.envio_json["emisor"]["numeroIdentificacion"] == "3101777777"
    mensaje = parsear(d.xml_firmado)
    assert etree.QName(mensaje).localname == "MensajeReceptor"

    # No se puede responder dos veces
    r = client.post(f"/api/v1/recepcion/{doc['id']}/mensaje", json={"mensaje": "3", "detalle_mensaje": "x"})
    assert r.status_code == 409


def test_rechazo_usa_consecutivo_tipo_07(client):
    doc_id = _registrar(client, xml_de_proveedor()).json()["id"]
    r = client.post(f"/api/v1/recepcion/{doc_id}/mensaje",
                    json={"mensaje": "3", "detalle_mensaje": "Mercadería no recibida"})
    assert r.status_code == 202, r.text
    assert r.json()["consecutivo_receptor"][8:10] == "07"


def test_documento_de_otro_receptor_es_rechazado(client):
    r = _registrar(client, xml_de_proveedor(receptor_numero="3101000000"))
    assert r.status_code == 422
    assert "no está dirigido" in r.json()["detail"]


def test_documento_duplicado(client):
    assert _registrar(client, xml_de_proveedor()).status_code == 201
    assert _registrar(client, xml_de_proveedor()).status_code == 409


def test_subir_archivo(client):
    r = client.post("/api/v1/recepcion/archivo",
                    files={"archivo": ("factura.xml", xml_de_proveedor(), "application/xml")})
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("contenido", [b"<no-es-xml", b"<?xml version='1.0'?><Otro/>"])
def test_xml_invalido(client, contenido):
    assert _registrar(client, contenido).status_code == 422


def test_firma_alterada_se_marca_invalida(client):
    xml = xml_de_proveedor().replace(b"<TotalComprobante>116700", b"<TotalComprobante>100")
    r = _registrar(client, xml)
    assert r.status_code == 201
    assert r.json()["firma_valida"] is False
