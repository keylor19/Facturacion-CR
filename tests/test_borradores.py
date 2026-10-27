"""Proformas y documentos preliminares."""
from datetime import date
from decimal import Decimal

from api.models.database import Factura
from tests.conftest import crear_emisor, factura_payload

URL = "/api/v1/borradores"


def test_proforma_numerada_con_totales_y_pdf(client):
    r = client.post(URL, json={"clase": "proforma", "datos": factura_payload()})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["numero"] == 1 and p["estado"] == "ABIERTO" and p["errores"] is None
    # Mismo cálculo que la emisión: 90 000 gravado + 11 700 IVA + 15 000 exento
    assert Decimal(p["monto_total"]) == Decimal("116700") and Decimal(p["monto_impuesto"]) == Decimal("11700")
    assert p["receptor_nombre"] == "Juan Pérez" and p["vence"] is not None
    assert client.post(URL, json={"clase": "proforma", "datos": factura_payload()}).json()["numero"] == 2

    pdf = client.get(f"{URL}/{p['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert [x["id"] for x in client.get(URL, params={"clase": "proforma", "q": "PF-000001"}).json()] == [p["id"]]


def test_proforma_incompleta_se_rechaza(client):
    r = client.post(URL, json={"clase": "proforma", "datos": factura_payload(productos=[])})
    assert r.status_code == 422


def test_preliminar_se_guarda_incompleto_y_se_completa(client):
    r = client.post(URL, json={"clase": "preliminar", "datos": {"tipo_documento": "01", "productos": []}})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["errores"] and b["monto_total"] is None and b["numero"] is None
    assert client.post(f"{URL}/{b['id']}/emitir").status_code == 422

    r = client.put(f"{URL}/{b['id']}", json={"datos": factura_payload()})
    assert r.json()["errores"] is None and r.json()["datos"]["receptor"]["nombre"] == "Juan Pérez"


def test_emitir_es_idempotente_y_cierra_el_borrador(db, client):
    b = client.post(URL, json={"clase": "proforma", "datos": factura_payload()}).json()
    r = client.post(f"{URL}/{b['id']}/emitir")
    assert r.status_code == 202, r.text
    factura_id = r.json()["factura_id"]
    assert db.get(Factura, factura_id).referencia_externa == f"borrador-{b['id']}"

    detalle = client.get(f"{URL}/{b['id']}").json()
    assert detalle["estado"] == "FACTURADO" and detalle["factura_id"] == factura_id
    # Reintento: devuelve el mismo comprobante, no emite otro
    assert client.post(f"{URL}/{b['id']}/emitir").json()["factura_id"] == factura_id
    assert db.query(Factura).count() == 1
    # Ya no se modifica ni se anula
    assert client.put(f"{URL}/{b['id']}", json={"datos": factura_payload()}).status_code == 409
    assert client.delete(f"{URL}/{b['id']}").status_code == 409


def test_anular_proforma_y_borrar_preliminar(client):
    p = client.post(URL, json={"clase": "proforma", "datos": factura_payload()}).json()
    assert client.delete(f"{URL}/{p['id']}").status_code == 204
    assert client.get(f"{URL}/{p['id']}").json()["estado"] == "ANULADO"
    assert client.post(f"{URL}/{p['id']}/emitir").status_code == 409

    b = client.post(URL, json={"clase": "preliminar", "datos": factura_payload()}).json()
    assert client.delete(f"{URL}/{b['id']}").status_code == 204
    assert client.get(f"{URL}/{b['id']}").status_code == 404


def test_proforma_vencida(client):
    p = client.post(URL, json={"clase": "proforma", "datos": factura_payload(), "vence": "2020-01-01"}).json()
    assert p["estado"] == "VENCIDO"
    assert [x["id"] for x in client.get(URL, params={"clase": "proforma", "estado": "VENCIDO"}).json()] == [p["id"]]
    assert client.get(URL, params={"clase": "proforma", "estado": "ABIERTO"}).json() == []
    r = client.put(f"{URL}/{p['id']}", json={"vence": date.today().replace(year=date.today().year + 1).isoformat()})
    assert r.json()["estado"] == "ABIERTO"


def test_borradores_aislados_por_empresa(db, client):
    from api.security import crear_api_key

    b = client.post(URL, json={"clase": "preliminar", "datos": factura_payload()}).json()
    otra = crear_emisor(db, numero="3101999999", nombre="Otra S.A.")
    _, llave = crear_api_key(db, "otra", False, otra.id)
    h = {"X-API-Key": llave}
    assert client.get(f"{URL}/{b['id']}", headers=h).status_code == 404
    assert client.get(URL, params={"clase": "preliminar"}, headers=h).json() == []
