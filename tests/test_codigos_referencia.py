"""
Códigos de referencia de Anexos y Estructuras 4.4, actualización del 22-04-2026
(obligatoria desde el 01-11-2026): notas 9 y 10, uso por tipo de comprobante,
anulación por error material, período fiscal y tope de las notas de crédito.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from api.models.database import EstadoFactura, Factura
from api.models.schemas import FacturaRequest
from api.services import reportes
from api.services.fechas import ahora_cr
from api.services.xml_generator import q
from tests.conftest import factura_payload

CLAVE = "5" * 50


def _ref(**cambios):
    return {"tipo_documento": "01", "numero": CLAVE, "fecha_emision": "2026-10-15T10:00:00", "codigo": "01",
            "razon": "Prueba", **cambios}


def _nota(tipo="03", **ref):
    return FacturaRequest(**factura_payload(tipo_documento=tipo, referencia=_ref(**ref)))


@pytest.mark.parametrize("tipo,codigo", [("03", "13"), ("03", "14"), ("02", "14"), ("03", "12"), ("01", "15"), ("01", "16")])
def test_codigos_nuevos_aceptados_donde_corresponden(tipo, codigo):
    assert _nota(tipo, codigo=codigo).referencias[0].codigo == codigo


@pytest.mark.parametrize("tipo,codigo,mensaje", [
    ("01", "13", "solo se usa en notas"),
    ("04", "14", "solo se usa en notas"),
    ("03", "15", "comprobante nuevo que sustituye"),
    ("02", "16", "comprobante nuevo que sustituye"),
    ("02", "12", "solo se usa en notas de crédito"),
    ("03", "17", "exclusivo del recibo electrónico de pago"),
    ("03", "03", "no existe en la nota 9"),
])
def test_codigos_fuera_de_lugar_se_rechazan(tipo, codigo, mensaje):
    with pytest.raises(ValidationError, match=mensaje):
        _nota(tipo, codigo=codigo)


def test_reglas_de_la_informacion_de_referencia():
    with pytest.raises(ValidationError, match="codigo_otro"):
        _nota(codigo="99")
    assert _nota(codigo="99", codigo_otro="Ajuste por convenio").referencias[0].codigo_otro
    with pytest.raises(ValidationError, match="tipo_documento_otro"):
        _nota(tipo_documento="99", numero="123")
    with pytest.raises(ValidationError, match="clave de 50 caracteres"):
        _nota(numero="00100001010000000001")
    with pytest.raises(ValidationError, match="Indique 'codigo'"):
        _nota(codigo=None)
    with pytest.raises(ValidationError, match="no existe en la nota 10"):
        _nota(tipo_documento="21")
    with pytest.raises(ValidationError, match="proveedor no domiciliado"):
        _nota(tipo_documento="16", numero="1" * 20)
    with pytest.raises(ValidationError, match="más de 10 años"):
        _nota(fecha_emision="2010-01-01T00:00:00")
    # Facturación mes vencido (tipo 13): el código es opcional
    assert FacturaRequest(**factura_payload(referencia=_ref(tipo_documento="13", codigo=None, numero=None)))
    # Exportación y recibo de pago como documento referido (tipos 19 y 20) y clave alfanumérica
    assert _nota(tipo_documento="19", numero="A" * 50)
    assert _nota(tipo_documento="20")


def _aceptada(db, factura_id, dias_atras=0):
    f = db.get(Factura, factura_id)
    f.estado = EstadoFactura.ACEPTADO
    if dias_atras:
        f.fecha_emision = f.fecha_emision - timedelta(days=dias_atras)
        f.periodo_fiscal = f.fecha_emision.astimezone(ahora_cr().tzinfo).date().replace(day=1)
    db.commit()
    return f


def test_anular_por_error_material_va_al_mes_de_la_factura(client, db, emisor):
    hoy = ahora_cr()
    original = _aceptada(db, client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"], dias_atras=40)
    mes_original = original.periodo_fiscal
    assert mes_original < hoy.date().replace(day=1)

    r = client.post(f"/api/v1/facturas/{original.id}/anular", json={"razon": "Cliente equivocado", "codigo": "13"})
    assert r.status_code == 202, r.text
    nota = db.get(Factura, r.json()["factura_id"])
    assert nota.codigo_referencia == "13" and nota.referencia_clave == original.clave
    assert nota.periodo_fiscal == mes_original                       # no el mes de la nota
    assert "<Codigo>13</Codigo>" in nota.xml_firmado and "<TipoDocIR>01</TipoDocIR>" in nota.xml_firmado
    detalle = client.get(f"/api/v1/facturas/{nota.id}").json()
    assert detalle["periodo_fiscal"] == mes_original.isoformat() and detalle["codigo_referencia"] == "13"

    nota.estado = EstadoFactura.ACEPTADO
    db.commit()
    # El mes de la nota no la suma, pero avisa que hay que rectificar el mes original
    ahora = reportes.resumen_iva(db, emisor, hoy.year, hoy.month)
    assert ahora["ventas"]["documentos"].get("Nota de crédito electrónica") is None
    assert ahora["rectificaciones_pendientes"] == [mes_original.strftime("%Y-%m")]
    # El mes original sí la suma (la factura y su anulación se cancelan) y la señala como posterior
    antes = reportes.resumen_iva(db, emisor, mes_original.year, mes_original.month)
    assert antes["ventas"]["total"] == Decimal("0.00")
    assert [n["clave"] for n in antes["notas_error_material"]["emitidas_despues_que_afectan_este_mes"]] == [nota.clave]


def test_anulacion_normal_va_al_mes_de_la_nota(client, db, emisor):
    hoy = ahora_cr()
    original = _aceptada(db, client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"], dias_atras=40)
    r = client.post(f"/api/v1/facturas/{original.id}/anular", json={"razon": "Devolución"})
    nota = db.get(Factura, r.json()["factura_id"])
    assert nota.codigo_referencia == "01" and nota.periodo_fiscal == hoy.date().replace(day=1)
    assert client.post(f"/api/v1/facturas/{original.id}/anular", json={"razon": "x", "codigo": "02"}).status_code == 422


def test_tipo_de_referencia_de_cada_comprobante():
    from api.services.emision import tipo_referencia
    assert [tipo_referencia(t, "03") for t in ("01", "02", "03", "04", "09", "10")] == ["01", "02", "03", "04", "19", "20"]
    # Notas a una factura de compra
    assert (tipo_referencia("08", "03"), tipo_referencia("08", "02")) == ("17", "18")


def test_nota_de_credito_no_supera_el_comprobante(client, db):
    original = _aceptada(db, client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"])

    nota = factura_payload(tipo_documento="03", referencia=_ref(numero=original.clave, codigo="02",
                                                                fecha_emision=original.fecha_emision.isoformat()))
    # Una nota igual a la factura cabe; una segunda ya no
    assert client.post("/api/v1/facturas", json=nota).status_code == 202
    r = client.post("/api/v1/facturas", json=nota)
    assert r.status_code == 422 and "supera lo que queda por acreditar" in r.json()["detail"]
    # Una nota de débito amplía el tope
    debito = factura_payload(tipo_documento="02", referencia=_ref(numero=original.clave, codigo="02",
                                                                  fecha_emision=original.fecha_emision.isoformat()))
    assert client.post("/api/v1/facturas", json=debito).status_code == 202
    assert client.post("/api/v1/facturas", json=nota).status_code == 202


def test_recibo_de_pago_usa_el_codigo_17(client, db):
    original = _aceptada(db, client.post(
        "/api/v1/facturas", json=factura_payload(condicion_venta="10", plazo_credito=60)).json()["factura_id"])
    r = client.post(f"/api/v1/facturas/{original.id}/recibo-pago", json={"monto": "1000"})
    assert r.status_code == 202, r.text
    recibo = db.get(Factura, r.json()["factura_id"])
    assert "<Codigo>17</Codigo>" in recibo.xml_firmado and recibo.codigo_referencia == "17"
    assert recibo.referencia_clave == original.clave
    assert recibo.periodo_fiscal == ahora_cr().date().replace(day=1)


# --- Otros cambios de la misma actualización (Anexos 4.4, abril 2026) ---

def test_cedula_juridica_alfanumerica_y_telefono_corto():
    datos = FacturaRequest(**factura_payload(receptor={
        "nombre": "Sociedad Nueva", "tipo_identificacion": "02", "numero_identificacion": "3101abc123", "telefono": "911"}))
    assert datos.receptor.numero_identificacion == "3101ABC123" and datos.receptor.telefono == "911"
    with pytest.raises(ValidationError, match="10 caracteres"):
        FacturaRequest(**factura_payload(receptor={"nombre": "X S.A.", "tipo_identificacion": "02", "numero_identificacion": "31AB"}))
    with pytest.raises(ValidationError, match="solo dígitos"):
        FacturaRequest(**factura_payload(receptor={"nombre": "Juan", "tipo_identificacion": "01", "numero_identificacion": "1A2345678"}))


def test_clave_con_cedula_alfanumerica():
    from api.services.clave_generator import generar_clave
    clave = generar_clave("3101ABC123", 1, 1, "01", 1, ahora_cr().date())
    assert len(clave) == 50 and "003101ABC123" in clave


def test_iva_devuelto_requiere_tarjeta_y_respeta_la_formula():
    from api.services.xml_generator import XMLValidacionError
    from tests.test_xml import _generar
    with pytest.raises(XMLValidacionError, match="tarjeta"):
        _generar(tipo_documento="04", receptor=None, iva_devuelto="100")
    # Pago mixto: (pagado con tarjeta / venta neta) x impuesto. El total (116 700) ya rebaja el IVA devuelto.
    def mixto(devuelto):
        return dict(tipo_documento="04", receptor=None, iva_devuelto=str(devuelto), medios_pago=[
            {"tipo": "02", "monto": "50000"}, {"tipo": "01", "monto": str(Decimal("66700") - devuelto)}])
    _, _, t = _generar(**mixto(Decimal("100")))
    tope = q(Decimal("50000") / t.venta_neta * t.impuesto)
    assert _generar(**mixto(tope))[2].iva_devuelto == tope
    with pytest.raises(XMLValidacionError, match="supera el máximo"):
        _generar(**mixto(tope + 1))


@pytest.mark.parametrize("monto", ["1000", "58350", "33333.33", "116700"])
def test_recibo_de_pago_impuesto_es_tarifa_por_subtotal(client, db, monto):
    original = _aceptada(db, client.post(
        "/api/v1/facturas", json=factura_payload(condicion_venta="10", plazo_credito=60)).json()["factura_id"])
    r = client.post(f"/api/v1/facturas/{original.id}/recibo-pago", json={"monto": monto})
    assert r.status_code == 202, r.text
    recibo = db.get(Factura, r.json()["factura_id"])
    assert recibo.monto_total == Decimal(monto)
    from api.services.emision import _lineas_recibo
    for ln in _lineas_recibo(original, Decimal(monto)):
        assert ln.impuesto == q(ln.subtotal * Decimal(ln.tarifa or 0) / 100)


def test_tope_cuenta_notas_que_citan_la_factura_en_otra_referencia(client, db):
    original = _aceptada(db, client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"])
    fecha = original.fecha_emision.isoformat()
    # Nota que cita otro documento primero y la factura después, por el total de la factura
    nota = factura_payload(tipo_documento="03", referencias=[
        _ref(numero="7" * 50, codigo="02", fecha_emision=fecha), _ref(numero=original.clave, codigo="02", fecha_emision=fecha)])
    assert client.post("/api/v1/facturas", json=nota).status_code == 202
    # Una segunda nota que cita solo la factura ya no cabe
    otra = factura_payload(tipo_documento="03", referencia=_ref(numero=original.clave, codigo="02", fecha_emision=fecha))
    r = client.post("/api/v1/facturas", json=otra)
    assert r.status_code == 422 and "supera lo que queda" in r.json()["detail"]
