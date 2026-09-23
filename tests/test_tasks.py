"""Pruebas de los workers con Hacienda simulada."""
import base64

import pytest
import requests
from celery.exceptions import Retry

from api.models.database import Factura, EstadoFactura
from api.services import hacienda_client, webhooks
from tests.conftest import factura_payload
from workers import tasks


def _respuesta(status, headers=None, text=""):
    resp = requests.Response()
    resp.status_code = status
    resp.headers.update(headers or {})
    resp._content = text.encode()
    return resp


@pytest.fixture
def factura_id(client):
    return client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]


def _estado(db, factura_id):
    db.expire_all()
    return db.get(Factura, factura_id)


def _enviar_con(monkeypatch, respuesta):
    monkeypatch.setattr(hacienda_client, "enviar", lambda emisor, envio, xml: respuesta(envio))


def test_envio_exitoso_programa_consulta(monkeypatch, db, cola, factura_id):
    enviados = []
    monkeypatch.setattr(hacienda_client, "enviar", lambda e, envio, xml: enviados.append(envio) or _respuesta(202))
    assert tasks.enviar_documento("factura", factura_id)["status"] == "enviado"
    f = _estado(db, factura_id)
    assert f.estado == EstadoFactura.ENVIADO and f.intentos_envio == 1
    assert ("consultar_documento", ("factura", factura_id)) in cola
    assert enviados[0]["clave"] == f.clave
    assert enviados[0]["emisor"] == {"tipoIdentificacion": "02", "numeroIdentificacion": "3101123456"}
    assert enviados[0]["receptor"]["numeroIdentificacion"] == "112345678"

    # Un segundo envío simultáneo/duplicado se omite
    assert tasks.enviar_documento("factura", factura_id)["status"] == "omitido"


def test_rechazo_de_recepcion_guarda_x_error_cause(monkeypatch, db, cola, factura_id):
    _enviar_con(monkeypatch, lambda _: _respuesta(400, {"X-Error-Cause": "La firma del comprobante no es válida"}))
    assert tasks.enviar_documento("factura", factura_id)["status"] == "rechazado"
    f = _estado(db, factura_id)
    assert f.estado == EstadoFactura.RECHAZADO
    assert "firma" in f.mensaje_hacienda
    assert ("notificar_webhook", ("factura", factura_id, "comprobante.rechazado")) in cola


def test_clave_ya_recibida_consulta_en_vez_de_rechazar(monkeypatch, db, cola, factura_id):
    _enviar_con(monkeypatch, lambda _: _respuesta(400, {"X-Error-Cause": "El comprobante ya fue recibido anteriormente"}))
    assert tasks.enviar_documento("factura", factura_id)["status"] == "duplicado"
    assert _estado(db, factura_id).estado == EstadoFactura.ENVIADO


def test_error_401_no_marca_rechazo(monkeypatch, db, factura_id):
    _enviar_con(monkeypatch, lambda _: _respuesta(401))
    tasks.enviar_documento("factura", factura_id)
    assert _estado(db, factura_id).estado == EstadoFactura.ERROR_COMUNICACION


def test_credenciales_invalidas_no_reintenta(monkeypatch, db, factura_id):
    from api.services.hacienda_auth import HaciendaAuthError

    def falla(*a):
        raise HaciendaAuthError("Invalid user credentials")
    monkeypatch.setattr(hacienda_client, "enviar", falla)
    assert tasks.enviar_documento("factura", factura_id)["status"] == "error_autenticacion"  # sin Retry
    f = _estado(db, factura_id)
    assert f.estado == EstadoFactura.ERROR_COMUNICACION
    assert f.eventos[-1].evento == "ERROR_AUTENTICACION"


@pytest.mark.parametrize("falla", [
    lambda _: _respuesta(503),
    lambda _: (_ for _ in ()).throw(requests.ConnectionError("sin red")),
])
def test_error_de_comunicacion_reintenta(monkeypatch, db, factura_id, falla):
    _enviar_con(monkeypatch, falla)
    with pytest.raises(Retry):
        tasks.enviar_documento("factura", factura_id)
    assert _estado(db, factura_id).estado == EstadoFactura.ERROR_COMUNICACION


def _mensaje_hacienda(estado, detalle):
    xml = (
        '<MensajeHacienda xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/mensajeHacienda">'
        f"<Mensaje>{estado}</Mensaje><DetalleMensaje>{detalle}</DetalleMensaje></MensajeHacienda>"
    )
    return base64.b64encode(xml.encode()).decode()


@pytest.mark.parametrize("ind_estado,esperado", [
    ("aceptado", EstadoFactura.ACEPTADO),
    ("rechazado", EstadoFactura.RECHAZADO),
])
def test_consulta_de_estado_final(monkeypatch, db, cola, factura_id, ind_estado, esperado):
    monkeypatch.setattr(hacienda_client, "consultar_estado", lambda emisor, clave: {
        "clave": clave, "ind-estado": ind_estado, "respuesta-xml": _mensaje_hacienda("1", "Detalle de Hacienda"),
    })
    tasks.consultar_documento("factura", factura_id)
    f = _estado(db, factura_id)
    assert f.estado == esperado
    assert f.mensaje_hacienda == "Detalle de Hacienda"
    assert "MensajeHacienda" in f.xml_respuesta
    evento = f"comprobante.{esperado.value.lower()}"
    assert ("notificar_webhook", ("factura", factura_id, evento)) in cola
    # Al aceptarse se envía el correo al receptor
    assert (("enviar_correo", (factura_id,)) in cola) == (esperado == EstadoFactura.ACEPTADO)


def test_consulta_en_proceso_reintenta(monkeypatch, db, factura_id):
    monkeypatch.setattr(hacienda_client, "consultar_estado", lambda emisor, clave: {"ind-estado": "procesando"})
    with pytest.raises(Retry):
        tasks.consultar_documento("factura", factura_id)


def test_consulta_404_deja_para_reenvio(monkeypatch, db, factura_id):
    def no_existe(emisor, clave):
        raise hacienda_client.HaciendaClientError("no existe", status_code=404)
    monkeypatch.setattr(hacienda_client, "consultar_estado", no_existe)
    tasks.consultar_documento("factura", factura_id)
    assert _estado(db, factura_id).estado == EstadoFactura.ERROR_COMUNICACION


def test_webhook_firmado(monkeypatch, db, factura_id):
    from api.services import emisores
    f = _estado(db, factura_id)
    secreto = emisores.configurar_webhook(f.emisor, "https://erp.example.com/hook")
    db.commit()

    capturado = {}

    def post(url, data, headers, **k):
        capturado.update(url=url, data=data, headers=headers)
        return _respuesta(200)

    monkeypatch.setattr(webhooks.requests, "post", post)
    assert tasks.notificar_webhook("factura", factura_id, "comprobante.aceptado")["status"] == "enviado"
    assert capturado["headers"]["X-Facturacion-Firma"] == webhooks.firmar(capturado["data"], secreto)
