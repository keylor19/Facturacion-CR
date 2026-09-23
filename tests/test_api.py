import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from api.models.database import Factura, EstadoFactura
from api.services import hacienda_publico
from api.services.firma import verificar_firma_local
from tests.conftest import factura_payload, crear_emisor, CALLBACK_TOKEN


def test_sin_api_key_es_rechazado(app_client):
    assert app_client.post("/api/v1/facturas", json=factura_payload()).status_code == 401
    r = app_client.get("/api/v1/facturas", headers={"X-API-Key": "fcr_llave-inventada"})
    assert r.status_code == 401


def test_llave_de_emisor_no_accede_a_administracion(client):
    assert client.get("/api/v1/emisores").status_code == 403
    assert client.post("/api/v1/api-keys", json={"nombre": "x", "es_admin": True}).status_code == 403


def test_crear_y_consultar_factura(client, cola):
    r = client.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 202, r.text
    data = r.json()
    assert len(data["clave"]) == 50
    assert data["estado"] == "PENDIENTE"
    assert ("enviar_documento", ("factura", data["factura_id"])) in cola

    r = client.get(f"/api/v1/facturas/{data['factura_id']}")
    assert r.status_code == 200, r.text
    detalle = r.json()
    assert Decimal(detalle["monto_total"]) == 116700
    assert Decimal(detalle["monto_impuesto"]) == 11700

    r = client.get(f"/api/v1/facturas/{data['factura_id']}/xml")
    assert r.headers["content-type"].startswith("application/xml")
    assert verificar_firma_local(r.text)

    r = client.get(f"/api/v1/facturas/{data['factura_id']}/pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")

    assert client.get(f"/api/v1/facturas/{data['factura_id']}/eventos").status_code == 200


def test_emisor_sin_certificado_no_puede_emitir(db, app_client):
    from api.security import crear_api_key
    sin_cert = crear_emisor(db, numero="3101000001", con_certificado=False)
    _, llave = crear_api_key(db, "k", False, sin_cert.id)
    r = app_client.post("/api/v1/facturas", json=factura_payload(), headers={"X-API-Key": llave})
    assert r.status_code == 409
    assert "certificado" in r.json()["detail"]


def test_aislamiento_entre_emisores(db, client, app_client):
    from api.security import crear_api_key
    factura_id = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]

    otro = crear_emisor(db, numero="3101999999", nombre="Otra S.A.")
    _, llave_otro = crear_api_key(db, "otro", False, otro.id)
    h = {"X-API-Key": llave_otro}
    assert app_client.get(f"/api/v1/facturas/{factura_id}", headers=h).status_code == 404
    assert app_client.get("/api/v1/facturas", headers=h).json() == []
    # Tampoco puede "saltar" a otro emisor con el header
    r = app_client.get("/api/v1/facturas", headers={**h, "X-Emisor-Id": str(client.get("/api/v1/facturas").json()[0]["emisor_id"])})
    assert r.status_code == 403


def test_admin_opera_con_x_emisor_id(admin, emisor):
    assert admin.post("/api/v1/facturas", json=factura_payload()).status_code == 400
    r = admin.post("/api/v1/facturas", json=factura_payload(), headers={"X-Emisor-Id": str(emisor.id)})
    assert r.status_code == 202, r.text


def test_idempotencia_por_referencia_externa(client):
    r1 = client.post("/api/v1/facturas", json=factura_payload(referencia_externa="POS-1-000123"))
    r2 = client.post("/api/v1/facturas", json=factura_payload(referencia_externa="POS-1-000123"))
    assert r1.status_code == 202
    assert r2.status_code == 200
    assert r1.json()["clave"] == r2.json()["clave"]


def test_consecutivos_por_sucursal_terminal_y_tipo(client):
    claves = [client.post("/api/v1/facturas", json=factura_payload()).json()["clave"] for _ in range(2)]
    otra_terminal = client.post("/api/v1/facturas", json=factura_payload(terminal=2)).json()["clave"]
    tiquete = client.post("/api/v1/facturas", json=factura_payload(tipo_documento="04")).json()["clave"]

    assert [c[21:41] for c in claves] == ["00100001010000000001", "00100001010000000002"]
    assert otra_terminal[21:41] == "00100002010000000001"
    assert tiquete[21:41] == "00100001040000000001"


def test_consecutivo_sin_duplicados_con_concurrencia(client):
    def crear(_):
        return client.post("/api/v1/facturas", json=factura_payload()).json()["clave"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        claves = list(pool.map(crear, range(16)))

    assert sorted(int(c[31:41]) for c in claves) == list(range(1, 17))


def test_tipo_de_cambio_automatico(client, monkeypatch):
    monkeypatch.setattr(hacienda_publico, "tipo_cambio", lambda moneda: Decimal("505.25"))
    r = client.post("/api/v1/facturas", json=factura_payload(moneda="USD"))
    assert r.status_code == 202, r.text
    assert Decimal(client.get(f"/api/v1/facturas/{r.json()['factura_id']}").json()["tipo_cambio"]) == Decimal("505.25")


def test_validaciones_devuelven_422(client):
    assert client.post("/api/v1/facturas", json=factura_payload(productos=[])).status_code == 422
    assert client.get("/api/v1/facturas/no-es-un-uuid").status_code == 422
    assert client.get("/api/v1/facturas?estado=INVENTADO").status_code == 422
    assert client.get(f"/api/v1/facturas/{uuid.uuid4()}").status_code == 404


def test_listar_con_filtros(client):
    client.post("/api/v1/facturas", json=factura_payload())
    client.post("/api/v1/facturas", json=factura_payload(tipo_documento="04"))
    assert len(client.get("/api/v1/facturas?estado=PENDIENTE").json()) == 2
    assert len(client.get("/api/v1/facturas?tipo_documento=04").json()) == 1
    assert client.get("/api/v1/facturas?estado=ACEPTADO").json() == []


def test_anular_factura_aceptada(client, db, cola):
    factura_id = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    r = client.post(f"/api/v1/facturas/{factura_id}/anular", json={"razon": "Error en el precio"})
    assert r.status_code == 409  # todavía no está aceptada

    f = db.get(Factura, factura_id)
    f.estado = EstadoFactura.ACEPTADO
    db.commit()

    r = client.post(f"/api/v1/facturas/{factura_id}/anular", json={"razon": "Error en el precio"})
    assert r.status_code == 202, r.text
    nota = db.get(Factura, r.json()["factura_id"])
    assert nota.tipo_documento == "03"
    assert nota.factura_origen_id == factura_id
    assert nota.monto_total == f.monto_total
    assert f.clave in nota.xml_firmado  # InformacionReferencia

    # No se puede anular dos veces
    assert client.post(f"/api/v1/facturas/{factura_id}/anular", json={"razon": "otra"}).status_code == 409


def test_no_se_reenvia_una_factura_aceptada(client, db):
    factura_id = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    db.get(Factura, factura_id).estado = EstadoFactura.ACEPTADO
    db.commit()
    assert client.post(f"/api/v1/facturas/{factura_id}/reenviar").status_code == 409


def test_callback_requiere_token_y_no_confia_en_el_payload(client, cola, db):
    data = client.post("/api/v1/facturas", json=factura_payload()).json()
    falso = {"clave": data["clave"], "ind-estado": "aceptado"}

    assert client.post("/api/v1/hacienda/callback/token-falso", json=falso).status_code == 404

    r = client.post(f"/api/v1/hacienda/callback/{CALLBACK_TOKEN}", json=falso)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Factura, data["factura_id"]).estado == EstadoFactura.PENDIENTE
    assert ("consultar_documento", ("factura", data["factura_id"])) in cola


def test_consultas_publicas_de_hacienda(client, monkeypatch):
    monkeypatch.setattr(hacienda_publico, "_get", lambda path, params, key, ttl: {"path": path, **params})
    assert client.get("/api/v1/hacienda/contribuyentes/3101123456").json()["path"] == "/fe/ae"
    assert client.get("/api/v1/hacienda/exoneraciones/AL-00012345-24").json()["path"] == "/fe/ex"
    assert client.get("/api/v1/hacienda/cabys?q=cafe").json()["q"] == "cafe"
    assert client.get("/api/v1/hacienda/cabys?q=a").status_code == 422
    assert client.get("/api/v1/hacienda/contribuyentes/abc").status_code == 422


def test_reportes(client, db):
    ids = [client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"] for _ in range(2)]
    for fid in ids:
        db.get(Factura, fid).estado = EstadoFactura.ACEPTADO
    db.commit()
    fecha = db.get(Factura, ids[0]).fecha_emision

    from api.services.fechas import zona_cr
    local = fecha.astimezone(zona_cr())
    r = client.get(f"/api/v1/reportes/resumen-iva?anio={local.year}&mes={local.month}")
    assert r.status_code == 200, r.text
    resumen = r.json()
    assert Decimal(resumen["iva_debito_fiscal"]) == Decimal("23400.00")
    tarifas = {t["codigo_tarifa_iva"]: t for t in resumen["ventas"]["por_tarifa"]}
    assert Decimal(tarifas["08"]["base"]) == Decimal("180000.00")

    csv = client.get(f"/api/v1/reportes/ventas.csv?anio={local.year}&mes={local.month}")
    assert csv.status_code == 200
    assert csv.text.count("\n") == 3  # encabezado + 2 filas


def test_health_publico(app_client):
    r = app_client.get("/api/v1/health")
    assert r.json()["database"] is True


def test_contingencia_sin_internet_usa_fecha_real(client, db):
    from datetime import timedelta
    from api.services.fechas import ahora_cr
    venta = (ahora_cr() - timedelta(days=3)).replace(hour=15, minute=30, second=0)
    r = client.post("/api/v1/facturas", json=factura_payload(situacion="3", fecha_emision=venta.strftime("%Y-%m-%dT%H:%M:%S")))
    assert r.status_code == 202, r.text
    f = db.get(Factura, r.json()["factura_id"])
    assert f.clave[41] == "3"                           # situación en la clave
    assert f.clave[3:9] == venta.strftime("%d%m%y")     # fecha real de la venta
    assert venta.isoformat() in f.xml_firmado


def test_contingencia_rechaza_fechas_invalidas(client):
    futura = client.post("/api/v1/facturas", json=factura_payload(situacion="3", fecha_emision="2099-01-01T00:00:00"))
    vieja = client.post("/api/v1/facturas", json=factura_payload(situacion="3", fecha_emision="2020-01-01T00:00:00"))
    assert futura.status_code == vieja.status_code == 422


def test_recibo_electronico_de_pago(client, db, cola):
    factura_id = client.post(
        "/api/v1/facturas", json=factura_payload(condicion_venta="10", plazo_credito=60)).json()["factura_id"]
    # Aún no aceptada
    assert client.post(f"/api/v1/facturas/{factura_id}/recibo-pago", json={"monto": "1000"}).status_code == 409
    f = db.get(Factura, factura_id)
    f.estado = EstadoFactura.ACEPTADO
    db.commit()

    r = client.post(f"/api/v1/facturas/{factura_id}/recibo-pago", json={"monto": "58350"})   # la mitad
    assert r.status_code == 202, r.text
    recibo = db.get(Factura, r.json()["factura_id"])
    assert recibo.tipo_documento == "10" and recibo.condicion_venta == "11"
    assert recibo.monto_total == Decimal("58350")
    assert recibo.monto_impuesto == Decimal("5850")            # mitad del IVA de la factura
    assert f.clave in recibo.xml_firmado
    assert ("enviar_documento", ("factura", recibo.id)) in cola

    pagos = client.get(f"/api/v1/facturas/{factura_id}/pagos").json()
    assert Decimal(pagos["saldo_pendiente"]) == Decimal("58350")
    assert client.post(f"/api/v1/facturas/{factura_id}/recibo-pago", json={"monto": "60000"}).status_code == 422
    assert client.get(f"/api/v1/facturas/{recibo.id}/pdf").status_code == 200


def test_recibo_solo_para_credito_08_o_10(client, db):
    factura_id = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    db.get(Factura, factura_id).estado = EstadoFactura.ACEPTADO
    db.commit()
    assert client.post(f"/api/v1/facturas/{factura_id}/recibo-pago", json={"monto": "1"}).status_code == 409


def test_estadisticas(client):
    client.post("/api/v1/facturas", json=factura_payload())
    from api.services.fechas import ahora_cr
    hoy = ahora_cr()
    r = client.get(f"/api/v1/reportes/estadisticas?anio={hoy.year}&mes={hoy.month}")
    assert r.status_code == 200
    assert r.json()["comprobantes_por_estado"] == {"PENDIENTE": 1}
