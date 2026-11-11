"""Cuentas por cobrar (abonos, antigüedad, estado de cuenta) y facturación recurrente."""
from datetime import timedelta
from decimal import Decimal

import pytest

from api.models.database import EstadoFactura, Factura, FacturaRecurrente
from api.services import recurrentes
from api.services.fechas import ahora_cr
from tests.conftest import factura_payload

TOTAL = Decimal("116700.00")   # 90 000 gravado + 11 700 IVA + 15 000 exento


def _credito(client, dias=30, **cambios):
    r = client.post("/api/v1/facturas", json=factura_payload(condicion_venta="02", plazo_credito=dias, **cambios))
    assert r.status_code == 202, r.text
    return r.json()["factura_id"]


def test_abonos_rebajan_el_saldo(client):
    fid = _credito(client)
    cartera = client.get("/api/v1/cobros/cartera").json()
    fila = next(f for f in cartera["facturas"] if f["factura_id"] == fid)
    assert Decimal(fila["saldo"]) == TOTAL and fila["tramo"] == "al_dia" and fila["plazo"] == 30
    assert Decimal(cartera["resumen"]["CRC"]["al_dia"]) == TOTAL

    r = client.post(f"/api/v1/cobros/facturas/{fid}/abonos", json={"monto": "50000", "medio_pago": "06", "referencia": "SINPE 123"})
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["saldo"]) == TOTAL - 50000
    # No se puede abonar más del saldo ni con fecha futura
    assert client.post(f"/api/v1/cobros/facturas/{fid}/abonos", json={"monto": "70000"}).status_code == 422
    manana = (ahora_cr().date() + timedelta(days=1)).isoformat()
    assert client.post(f"/api/v1/cobros/facturas/{fid}/abonos", json={"monto": "1", "fecha": manana}).status_code == 422

    abono = r.json()["id"]
    assert client.post(f"/api/v1/cobros/abonos/{abono}/anular").status_code == 200
    assert Decimal(client.get(f"/api/v1/cobros/facturas/{fid}").json()["saldo"]) == TOTAL

    # Pagada por completo: sale de la cartera
    assert client.post(f"/api/v1/cobros/facturas/{fid}/abonos", json={"monto": str(TOTAL)}).status_code == 201
    assert fid not in [f["factura_id"] for f in client.get("/api/v1/cobros/cartera").json()["facturas"]]


def test_solo_credito_comercial_lleva_abonos(client):
    contado = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    assert client.post(f"/api/v1/cobros/facturas/{contado}/abonos", json={"monto": "1"}).status_code == 409
    r = client.post("/api/v1/facturas", json=factura_payload(condicion_venta="10", plazo_credito=90))
    fid = r.json()["factura_id"]
    r = client.post(f"/api/v1/cobros/facturas/{fid}/abonos", json={"monto": "1"})
    assert r.status_code == 409 and "recibo" in r.json()["detail"]


def test_antiguedad_y_estado_de_cuenta(db, client):
    vieja = _credito(client, dias=30)
    f = db.get(Factura, vieja)
    f.fecha_emision = f.fecha_emision - timedelta(days=130)   # venció hace 100 días
    db.commit()
    nueva = _credito(client, dias=30, referencia_externa="NUEVA")

    cartera = client.get("/api/v1/cobros/cartera").json()
    tramos = {x["factura_id"]: (x["tramo"], x["dias_vencida"]) for x in cartera["facturas"]}
    assert tramos[vieja] == ("mas_90", 100) and tramos[nueva] == ("al_dia", 0)
    assert Decimal(cartera["resumen"]["CRC"]["mas_90"]) == TOTAL
    cliente = cartera["clientes"][0]
    assert cliente["identificacion"] == "112345678" and cliente["facturas"] == 2
    assert Decimal(cliente["vencido"]) == TOTAL and Decimal(cliente["saldo"]) == 2 * TOTAL

    ec = client.get("/api/v1/cobros/estado-cuenta/112345678").json()
    assert len(ec["facturas"]) == 2 and Decimal(ec["saldo"]["CRC"]) == 2 * TOTAL
    assert client.get("/api/v1/cobros/estado-cuenta/999999999").status_code == 404


def test_la_nota_de_credito_cancela_el_saldo(db, client):
    fid = _credito(client)
    db.get(Factura, fid).estado = EstadoFactura.ACEPTADO
    db.commit()
    assert client.post(f"/api/v1/facturas/{fid}/anular", json={"razon": "Devolución"}).status_code == 202
    assert Decimal(client.get(f"/api/v1/cobros/facturas/{fid}").json()["saldo"]) == 0


def test_activar_recordatorios(client):
    assert client.put("/api/v1/cobros/ajustes", json={"recordar_cobros": True}).json()["recordar_cobros"] is True
    assert client.get("/api/v1/cobros/cartera").json()["recordar_cobros"] is True


# --- Facturación recurrente ---------------------------------------------------------------

def _plantilla(client, **cambios):
    hoy = ahora_cr().date()
    cuerpo = {"nombre": "Alquiler local 3", "datos": factura_payload(), "frecuencia": "mensual",
              "proxima": hoy.replace(day=min(hoy.day, 28)).isoformat(), **cambios}
    return client.post("/api/v1/recurrentes", json=cuerpo)


def test_recurrente_se_emite_y_avanza_un_mes(db, client):
    hoy = ahora_cr().date()
    if hoy.day > 28:
        pytest.skip("Las recurrentes mensuales usan días del 1 al 28")
    r = _plantilla(client, proxima=hoy.isoformat())
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    nuevos = recurrentes.emitir_pendientes(db, hoy)
    assert len(nuevos) == 1
    rec = db.get(FacturaRecurrente, rid)
    db.refresh(rec)
    assert rec.emitidas == 1 and rec.proxima == recurrentes.siguiente(hoy, "mensual")
    f = db.get(Factura, nuevos[0])
    assert f.referencia_externa == f"REC-{rid[:8]}-{hoy:%Y%m%d}" and f.receptor_nombre == "Juan Pérez"
    # Correr de nuevo el mismo día no duplica
    assert recurrentes.emitir_pendientes(db, hoy) == []


def test_emitir_ahora_no_duplica(client):
    rid = _plantilla(client, proxima=(ahora_cr().date() + timedelta(days=3)).isoformat(), frecuencia="semanal").json()["id"]
    primera = client.post(f"/api/v1/recurrentes/{rid}/emitir-ahora")
    assert primera.status_code == 202 and primera.json()["nueva"] is True
    segunda = client.post(f"/api/v1/recurrentes/{rid}/emitir-ahora")
    assert segunda.status_code == 200 and segunda.json()["factura_id"] == primera.json()["factura_id"]
    assert client.get(f"/api/v1/recurrentes/{rid}").json()["emitidas"] == 1


def test_recurrente_valida_la_plantilla(client):
    manana = (ahora_cr().date() + timedelta(days=1)).isoformat()
    r = client.post("/api/v1/recurrentes", json={"nombre": "Mala", "datos": {"productos": []}, "proxima": manana,
                                                 "frecuencia": "semanal"})
    assert r.status_code == 422
    nota = factura_payload(tipo_documento="03")
    assert client.post("/api/v1/recurrentes", json={"nombre": "Nota", "datos": nota, "proxima": manana,
                                                    "frecuencia": "semanal"}).status_code == 422
    assert _plantilla(client, proxima="2027-01-31").status_code == 422   # mensual en día 31


def test_siguiente_fecha():
    from datetime import date
    assert recurrentes.siguiente(date(2026, 1, 28), "mensual") == date(2026, 2, 28)
    assert recurrentes.siguiente(date(2026, 12, 15), "mensual") == date(2027, 1, 15)
    assert recurrentes.siguiente(date(2026, 3, 1), "quincenal") == date(2026, 3, 16)
    assert recurrentes.siguiente(date(2026, 3, 1), "anual") == date(2027, 3, 1)


# --- Enlace público para WhatsApp ---------------------------------------------------------

def test_enlace_publico_para_whatsapp(client, app_client):
    from urllib.parse import urlparse
    fid = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    otra = client.post("/api/v1/facturas", json=factura_payload(referencia_externa="OTRA")).json()["factura_id"]
    e = client.get(f"/api/v1/facturas/{fid}/enlace", params={"telefono": "8888-7777"}).json()
    assert e["whatsapp"].startswith("https://wa.me/50688887777?text=") and "Juan" in e["texto"]
    ruta = urlparse(e["pdf"]).path

    sin_sesion = app_client.get(ruta, headers={"X-API-Key": ""})
    assert sin_sesion.status_code == 200 and sin_sesion.content.startswith(b"%PDF")
    assert app_client.get(urlparse(e["xml"]).path).status_code == 200
    # Firma alterada o usada con otro comprobante: no sirve
    assert app_client.get(ruta.replace("/pdf", "x/pdf")).status_code == 404
    assert app_client.get(ruta.replace(fid, otra)).status_code == 404


# --- Borrador de la D-104 ---------------------------------------------------------------

def test_borrador_d104(db, client, contador):
    fid = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    f = db.get(Factura, fid)
    f.estado = EstadoFactura.ACEPTADO
    db.commit()
    hoy = ahora_cr().date()
    b = client.get("/api/v1/reportes/d104", params={"anio": hoy.year, "mes": hoy.month}, headers=contador).json()
    trece = next(x for x in b["ventas"] if x["codigo_tarifa_iva"] == "08")
    assert "13%" in trece["concepto"] and Decimal(trece["base"]) == 90000 and Decimal(trece["iva"]) == 11700
    assert Decimal(b["totales"]["iva_debito_fiscal"]) == 11700
    assert Decimal(b["totales"]["impuesto_a_pagar"]) == 11700 and Decimal(b["totales"]["saldo_a_favor"]) == 0
    csv = client.get("/api/v1/reportes/d104.csv", params={"anio": hoy.year, "mes": hoy.month}, headers=contador)
    assert csv.status_code == 200 and "Impuesto a pagar" in csv.text
