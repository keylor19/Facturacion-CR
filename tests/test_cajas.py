"""Punto de venta (cajas) y descarga de comprobantes en ZIP."""
import io
import zipfile
from decimal import Decimal

from api.models.database import Factura
from api.services.fechas import ahora_cr
from tests.conftest import factura_payload

URL = "/api/v1/cajas"
# factura_payload(): 116 700 colones (90 000 + 11 700 IVA + 15 000 exento)
TOTAL = Decimal("116700")


def _abrir(client, **cambios):
    r = client.post(URL, json={"sucursal": 1, "terminal": 2, "monto_apertura": "20000", **cambios})
    assert r.status_code == 201, r.text
    return r.json()


def test_una_sola_caja_abierta_por_terminal(client):
    caja = _abrir(client)
    assert caja["estado"] == "ABIERTA" and caja["resumen"]["documentos"] == 0
    assert client.post(URL, json={"sucursal": 1, "terminal": 2}).status_code == 409
    assert client.post(URL, json={"sucursal": 1, "terminal": 3}).status_code == 201
    assert len(client.get(URL, params={"estado": "ABIERTA"}).json()) == 2


def test_ventas_movimientos_y_arqueo(db, client):
    caja = _abrir(client)
    efectivo = client.post(f"{URL}/{caja['id']}/ventas", json=factura_payload(tipo_documento="04", terminal=9))
    assert efectivo.status_code == 202, efectivo.text
    f = db.get(Factura, efectivo.json()["factura_id"])
    # Usa la sucursal/terminal de la caja, no la que venga en la solicitud
    assert f.caja_id == caja["id"] and f.numero_consecutivo[3:8] == "00002"
    # Pago mixto (con varios medios cada uno lleva su monto): 50 000 con tarjeta y el resto en efectivo
    mixto = factura_payload(medios_pago=[{"tipo": "02", "monto": "50000"}, {"tipo": "01", "monto": str(TOTAL - 50000)}])
    assert client.post(f"{URL}/{caja['id']}/ventas", json=mixto).status_code == 202
    assert client.post(f"{URL}/{caja['id']}/movimientos", json={"tipo": "salida", "monto": "5000", "motivo": "Pago de hielo"}).status_code == 201

    r = client.get(f"{URL}/{caja['id']}").json()["resumen"]
    assert r["documentos"] == 2 and Decimal(r["total_ventas"]) == 2 * TOTAL
    assert Decimal(r["por_medio"]["02"]) == Decimal("50000")
    assert Decimal(r["por_medio"]["01"]) == 2 * TOTAL - 50000
    esperado = Decimal("20000") + (2 * TOTAL - 50000) - 5000
    assert Decimal(r["efectivo_esperado"]) == esperado
    assert len(client.get(f"{URL}/{caja['id']}/ventas").json()) == 2

    cerrada = client.post(f"{URL}/{caja['id']}/cerrar", json={"monto_contado": str(esperado - 1000)}).json()
    assert cerrada["estado"] == "CERRADA" and Decimal(cerrada["resumen"]["diferencia"]) == Decimal("-1000")
    # Cerrada: no admite más ventas ni movimientos
    assert client.post(f"{URL}/{caja['id']}/ventas", json=factura_payload()).status_code == 409
    assert client.post(f"{URL}/{caja['id']}/movimientos", json={"tipo": "entrada", "monto": "1", "motivo": "x"}).status_code == 409
    # Y se puede abrir otro turno en la misma terminal
    assert client.post(URL, json={"sucursal": 1, "terminal": 2}).status_code == 201


def test_caja_solo_factura_o_tiquete(client):
    caja = _abrir(client)
    r = client.post(f"{URL}/{caja['id']}/ventas", json=factura_payload(tipo_documento="09"))
    assert r.status_code == 422


def test_descarga_zip(client):
    client.post("/api/v1/facturas", json=factura_payload())
    hoy = ahora_cr().date().isoformat()
    r = client.get("/api/v1/reportes/documentos.zip", params={"desde": hoy, "hasta": hoy, "pdf": True})
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nombres = z.namelist()
    assert "indice.csv" in nombres
    assert any(n.startswith("emitidos/") and n.endswith(".xml") for n in nombres)
    assert any(n.endswith(".pdf") for n in nombres)
    assert "Juan Pérez" in z.read("indice.csv").decode("utf-8-sig")


def test_descarga_zip_vacia_o_rango_invalido(client):
    r = client.get("/api/v1/reportes/documentos.zip", params={"desde": "2020-01-01", "hasta": "2020-01-31"})
    assert r.status_code == 422 and "No hay documentos" in r.json()["detail"]
    r = client.get("/api/v1/reportes/documentos.zip", params={"desde": "2020-01-01", "hasta": "2022-01-01"})
    assert r.status_code == 422
