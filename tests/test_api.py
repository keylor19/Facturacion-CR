import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

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


class _RespHacienda:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


@pytest.fixture
def hacienda_falsa(monkeypatch):
    """Caché en memoria y respuestas de Hacienda programables; registra las llamadas."""
    cache, llamadas, respuestas = {}, [], {}
    monkeypatch.setattr(hacienda_publico, "obtener_json", lambda k: cache.get(k))
    monkeypatch.setattr(hacienda_publico, "guardar_json", lambda k, v, ttl: cache.__setitem__(k, v))
    monkeypatch.setattr(hacienda_publico, "_esperar_turno", lambda: None)

    def get(url, params=None, timeout=None):
        llamadas.append((url, params))
        return respuestas[url.split("api.hacienda.go.cr")[-1]]
    monkeypatch.setattr(hacienda_publico.requests, "get", get)
    return respuestas, llamadas, cache


def test_contribuyente_no_inscrito_o_invalido(client, hacienda_falsa):
    respuestas, llamadas, _ = hacienda_falsa
    respuestas["/fe/ae"] = _RespHacienda(404)
    assert client.get("/api/v1/hacienda/contribuyentes/399999999999").status_code == 404
    # El "no encontrado" queda en caché: no se vuelve a consultar a Hacienda
    assert client.get("/api/v1/hacienda/contribuyentes/399999999999").status_code == 404
    assert len(llamadas) == 1
    respuestas["/fe/ae"] = _RespHacienda(400)
    assert client.get("/api/v1/hacienda/contribuyentes/111111111").status_code == 422


def test_bloqueo_429_suspende_consultas(client, hacienda_falsa):
    respuestas, llamadas, cache = hacienda_falsa
    respuestas["/fe/ae"] = _RespHacienda(429)
    assert client.get("/api/v1/hacienda/contribuyentes/206500188").status_code == 503
    assert cache[hacienda_publico.CLAVE_BLOQUEO] is True
    # Durante el bloqueo no se envían más solicitudes
    assert client.get("/api/v1/hacienda/contribuyentes/3101005744").status_code == 503
    assert len(llamadas) == 1


def test_productores_agropecuario_y_pesca(client, hacienda_falsa):
    respuestas, _, _ = hacienda_falsa
    # Hacienda responde HTTP 200 con el 404 en el cuerpo cuando no está registrado
    respuestas["/fe/agropecuario"] = _RespHacienda(200, {"title": "Not Found", "status": 404})
    respuestas["/fe/pesca"] = _RespHacienda(200, {"identificacion": "206500188", "nombre": "PESCADOR"})
    r = client.get("/api/v1/hacienda/productores/206500188").json()
    assert r["agropecuario"] is None and r["pesca"]["nombre"] == "PESCADOR" and r["registrado"] is True


EXO_HACIENDA = {"numeroDocumento": "AL-00460853-20", "identificacion": "401760738", "porcentajeExoneracion": 13,
                "fechaEmision": "2020-12-15T00:00:00", "fechaVencimiento": "2099-12-15T00:00:00",
                "cabys": ["7211200000100"], "poseeCabys": True, "tipoDocumento": {"codigo": "04"}}


def test_exoneracion_con_lista_de_cabys(client, hacienda_falsa):
    respuestas, _, _ = hacienda_falsa
    respuestas["/fe/ex"] = _RespHacienda(200, EXO_HACIENDA)
    respuestas["/fe/cabys"] = _RespHacienda(200, [{"codigo": "7211200000100", "descripcion": "Alquiler de vivienda", "impuesto": 13}])
    r = client.get("/api/v1/hacienda/exoneraciones/AL-00460853-20?detalle=true").json()
    assert r["aplica_a_todo"] is False
    assert r["cabys_detalle"] == [{"codigo": "7211200000100", "descripcion": "Alquiler de vivienda", "impuesto": 13}]


def test_emision_rechaza_cabys_no_contemplado_en_exoneracion(client, hacienda_falsa, monkeypatch, db):
    from config.settings import get_settings
    respuestas, _, _ = hacienda_falsa
    monkeypatch.setattr(get_settings(), "VALIDAR_CABYS", True)
    monkeypatch.setattr(hacienda_publico, "cabys_inexistentes", lambda codigos: [])
    respuestas["/fe/ex"] = _RespHacienda(200, EXO_HACIENDA)
    payload = factura_payload()
    payload["productos"][0]["exoneracion"] = {
        "tipo_documento": "04", "numero_documento": "AL-00460853-20", "nombre_institucion": "01",
        "fecha_emision": "2020-12-15T00:00:00", "tarifa_exonerada": "13"}
    r = client.post("/api/v1/facturas", json=payload)
    assert r.status_code == 422 and "no está contemplado" in r.json()["detail"]
    assert db.query(Factura).count() == 0
    # Con un CABYS de la lista sí se emite
    payload["productos"][0]["codigo_cabys"] = "7211200000100"
    assert client.post("/api/v1/facturas", json=payload).status_code == 202


def test_validaciones_segun_documentacion_de_hacienda(client, hacienda_falsa):
    respuestas, llamadas, _ = hacienda_falsa
    assert client.get("/api/v1/hacienda/exoneraciones/AL-0460853-20").status_code == 422
    assert client.get("/api/v1/hacienda/cabys?codigo=123").status_code == 422
    assert llamadas == []
    respuestas["/fe/ex"] = _RespHacienda(200, {"numeroDocumento": "AL-00460853-20"})
    assert client.get("/api/v1/hacienda/exoneraciones/al-00460853-20").status_code == 200
    assert llamadas[-1][1] == {"autorizacion": "AL-00460853-20"}


def test_tipos_de_cambio_en_una_consulta(client, hacienda_falsa):
    respuestas, llamadas, _ = hacienda_falsa
    respuestas["/indicadores/tc"] = _RespHacienda(200, {
        "dolar": {"venta": {"fecha": "2026-10-06", "valor": 460.35}, "compra": {"fecha": "2026-10-06", "valor": 454.5}},
        "euro": {"fecha": "2026-10-05", "dolares": 1.1193, "colones": 515.27}})
    r = client.get("/api/v1/hacienda/tipo-cambio").json()
    assert r["USD"]["venta"] == 460.35 and r["EUR"]["colones"] == 515.27
    assert Decimal(str(client.get("/api/v1/hacienda/tipo-cambio/EUR").json()["tipo_cambio"])) == Decimal("515.27")
    assert len(llamadas) == 1


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


def test_cabys_inexistente_se_rechaza_antes_de_firmar(client, monkeypatch, db):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "VALIDAR_CABYS", True)
    existentes = {"8314100000000"}
    monkeypatch.setattr(hacienda_publico, "_get",
                        lambda path, params, key, ttl: [{"codigo": params["codigo"]}] if params.get("codigo") in existentes else [])
    r = client.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 422 and "2399999009900" in r.json()["detail"]
    assert db.query(Factura).count() == 0

    # Si el servicio de Hacienda no responde, no se bloquea la facturación
    def caido(*a, **k):
        raise hacienda_publico.HaciendaPublicoError("caído")
    monkeypatch.setattr(hacienda_publico, "_get", caido)
    assert client.post("/api/v1/facturas", json=factura_payload()).status_code == 202


CONTRIBUYENTE = {"nombre": "PURDY MOTOR SOCIEDAD ANONIMA", "tipoIdentificacion": "02",
                 "situacion": {"estado": "Inscrito"}, "actividades": []}


def _envejecer(db, dias):
    from datetime import timedelta
    from api.models.database import RegistroHacienda, utcnow
    for r in db.query(RegistroHacienda).all():
        r.actualizado_en = utcnow() - timedelta(days=dias)
    db.commit()


def test_datos_de_hacienda_se_guardan_y_se_reutilizan(client, db, hacienda_falsa):
    from api.models.database import RegistroHacienda
    respuestas, llamadas, cache = hacienda_falsa
    respuestas["/fe/ae"] = _RespHacienda(200, CONTRIBUYENTE)
    assert client.get("/api/v1/hacienda/contribuyentes/3101005744").json()["nombre"] == CONTRIBUYENTE["nombre"]
    assert db.query(RegistroHacienda).filter_by(tipo="ae", clave="3101005744").one().encontrado
    cache.clear()   # aunque Redis se vacíe, se responde con lo guardado sin consultar a Hacienda
    assert client.get("/api/v1/hacienda/contribuyentes/3101005744").json()["nombre"] == CONTRIBUYENTE["nombre"]
    assert len(llamadas) == 1


def test_si_hacienda_falla_se_usan_los_datos_guardados(client, db, hacienda_falsa):
    respuestas, llamadas, cache = hacienda_falsa
    respuestas["/fe/ae"] = _RespHacienda(200, CONTRIBUYENTE)
    client.get("/api/v1/hacienda/contribuyentes/3101005744")
    _envejecer(db, 20)   # más de 15 días: toca refrescar...
    cache.clear()
    respuestas["/fe/ae"] = _RespHacienda(503)   # ...pero Hacienda está caída
    r = client.get("/api/v1/hacienda/contribuyentes/3101005744")
    assert r.status_code == 200
    assert r.json()["nombre"] == CONTRIBUYENTE["nombre"] and "_respaldo_local" in r.json()


def test_actualizacion_periodica_de_datos_de_hacienda(client, db, hacienda_falsa):
    from api.models.database import RegistroHacienda
    respuestas, llamadas, cache = hacienda_falsa
    crear_emisor(db, numero="3101005744")
    respuestas["/fe/ae"] = _RespHacienda(200, CONTRIBUYENTE)
    # Precarga las cédulas de empresas y clientes que no están guardadas
    r = hacienda_publico.actualizar_registros(pausa=0)
    assert r["actualizados"] >= 1
    assert db.query(RegistroHacienda).filter_by(tipo="ae", clave="3101005744").count() == 1
    # Lo vigente no se vuelve a consultar; lo de más de 15 días sí
    n = len(llamadas)
    assert hacienda_publico.actualizar_registros(pausa=0)["actualizados"] == 0 and len(llamadas) == n
    _envejecer(db, 16)
    respuestas["/fe/ae"] = _RespHacienda(200, {**CONTRIBUYENTE, "nombre": "PURDY MOTOR S.A."})
    assert hacienda_publico.actualizar_registros(pausa=0)["actualizados"] >= 1
    db.expire_all()
    assert db.query(RegistroHacienda).filter_by(clave="3101005744").one().datos["nombre"] == "PURDY MOTOR S.A."
    # Si Hacienda limita (429) se detiene y sigue en la próxima ejecución
    _envejecer(db, 16)
    respuestas["/fe/ae"] = _RespHacienda(429)
    assert hacienda_publico.actualizar_registros(pausa=0)["detenido"] is True


def _excel_cabys(filas):
    import io
    import openpyxl
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Catálogo"
    hoja.append([None])
    titulos = []
    for n in range(1, 10):
        titulos += [f"Categoría {n}", f"Descripción (categoría {n})"]
    hoja.append(titulos + ["Impuesto", "Nota explicativa 1. Incluye", "Nota explicativa 2. Excluye"])
    for codigo, descripcion, impuesto in filas:
        cats = []
        for n in range(1, 9):
            cats += [codigo[:n], f"Categoría {n} de {descripcion}"]
        hoja.append(cats + [codigo, descripcion, impuesto, None, None])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def test_catalogo_cabys_local(client, db, hacienda_falsa, monkeypatch):
    from api.services import catalogo_cabys
    respuestas, llamadas, _ = hacienda_falsa
    monkeypatch.setattr(catalogo_cabys, "MINIMO_COMPLETO", 2)
    catalogo_cabys._completo["hasta"] = 0
    r = catalogo_cabys.importar_excel(_excel_cabys([
        ("2399999009900", "Café molido, tostado", 0.01),
        ("8314100000000", "Servicios de consultoría informática", 0.13),
        ("1111111111111", "Té verde", 0.005),
    ]))
    assert r["importados"] == 3
    # Búsqueda sin tildes ni mayúsculas, sin consultar a Hacienda
    datos = client.get("/api/v1/hacienda/cabys?q=CAFE").json()
    assert datos["cabys"][0]["codigo"] == "2399999009900" and datos["cabys"][0]["impuesto"] == 1
    assert client.get("/api/v1/hacienda/cabys?q=consultoria informatica").json()["total"] == 1
    assert client.get("/api/v1/hacienda/cabys?codigo=1111111111111").json()[0]["impuesto"] == 0.5
    assert llamadas == []
    # Una versión nueva del catálogo reemplaza la anterior (borra los códigos eliminados)
    r = catalogo_cabys.importar_excel(_excel_cabys([
        ("2399999009900", "Café molido, tostado", 0.13), ("8314100000000", "Servicios de consultoría informática", 0.13)]))
    assert r["eliminados"] == 1
    assert client.get("/api/v1/hacienda/cabys?q=cafe").json()["cabys"][0]["impuesto"] == 13
    catalogo_cabys._completo["hasta"] = 0


def test_cabys_de_hacienda_se_guardan_y_sirven_si_hacienda_cae(client, db, hacienda_falsa):
    from api.services import catalogo_cabys
    respuestas, llamadas, cache = hacienda_falsa
    catalogo_cabys._completo["hasta"] = 0
    respuestas["/fe/cabys"] = _RespHacienda(200, {"total": 1, "cantidad": 1, "cabys": [
        {"codigo": "2399999009900", "descripcion": "Café molido", "categorias": ["Alimentos"], "impuesto": 1}]})
    client.get("/api/v1/hacienda/cabys?q=cafe")
    cache.clear()
    respuestas["/fe/cabys"] = _RespHacienda(503)
    r = client.get("/api/v1/hacienda/cabys?q=molido").json()
    assert r["cabys"][0]["codigo"] == "2399999009900" and "_respaldo_local" in r


def test_historico_propio_del_tipo_de_cambio(client, db, hacienda_falsa):
    from datetime import date, timedelta
    respuestas, llamadas, cache = hacienda_falsa
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    respuestas["/indicadores/tc"] = _RespHacienda(200, {
        "dolar": {"venta": {"fecha": ayer.isoformat(), "valor": 460.35}, "compra": {"fecha": ayer.isoformat(), "valor": 454.5}},
        "euro": {"fecha": ayer.isoformat(), "dolares": 1.1193, "colones": 515.27}})
    client.get("/api/v1/hacienda/tipo-cambio")   # se guarda el día
    r = client.get(f"/api/v1/hacienda/tipo-cambio/USD/historico?desde={ayer}&hasta={ayer}").json()
    assert r == [{"fecha": ayer.isoformat(), "compra": 454.5, "venta": 460.35}]
    assert not any("historico" in u for u, _ in llamadas)   # salió del histórico propio
    # Factura con fecha atrasada: tipo de cambio de ese día
    assert hacienda_publico.tipo_cambio_en_fecha("USD", ayer) == Decimal("460.35")
    assert hacienda_publico.tipo_cambio_en_fecha("EUR", ayer) == Decimal("515.27")


class _RespWeb:
    def __init__(self, status_code=200, text="", content=b"", headers=None):
        self.status_code, self.text, self.content, self.headers = status_code, text, content, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise hacienda_publico.requests.HTTPError(str(self.status_code))


def test_catalogo_cabys_se_actualiza_solo(db, monkeypatch):
    from api.models.database import Auditoria, CodigoCabys
    from api.services import catalogo_cabys
    from config.settings import get_settings
    monkeypatch.setattr(catalogo_cabys, "MINIMO_COMPLETO", 2)
    catalogo_cabys._completo["hasta"] = 0
    v2025 = "https://www.bccr.fi.cr/content/dam/bccr/noticias/2025/2025-04-01-catalogo-de-bienes-servicios-1.xlsx"
    v2026 = "https://www.bccr.fi.cr/content/dam/bccr/noticias/2026/2026-04-01-catalogo-de-bienes-servicios-1.xlsx"
    monkeypatch.setattr(get_settings(), "CABYS_URL", v2025)
    web = {
        catalogo_cabys.NOTICIAS_BCCR: _RespWeb(text="<a href=\"/cr/es/noticias/listado-de-noticias/2025/subasta.html\">"),
        v2025: _RespWeb(content=_excel_cabys([("2399999009900", "Café", 0.01), ("1111111111111", "Té", 0.13)]),
                        headers={"ETag": "a"}),
    }
    descargas = []

    def get(url, **k):
        descargas.append(url)
        return web.get(url, _RespWeb(404))
    monkeypatch.setattr(catalogo_cabys.requests, "get", get)
    monkeypatch.setattr(catalogo_cabys.requests, "head", lambda url, **k: web.get(url, _RespWeb(404)))

    # Primera vez: importa el catálogo configurado
    assert catalogo_cabys.actualizar_si_hay_version_nueva()["cambios"] is True
    assert db.query(CodigoCabys).count() == 2
    # Sin cambios: no vuelve a descargar el Excel
    descargas.clear()
    assert catalogo_cabys.actualizar_si_hay_version_nueva()["cambios"] is False
    assert v2025 not in descargas
    # El BCCR publica una noticia con la versión nueva: se detecta y se importa sola
    web[catalogo_cabys.NOTICIAS_BCCR] = _RespWeb(
        text='<a href="/cr/es/noticias/listado-de-noticias/2026/actualizacion-del-catalogo-cabys-2026.html">')
    web[catalogo_cabys.BCCR + "/cr/es/noticias/listado-de-noticias/2026/actualizacion-del-catalogo-cabys-2026.html"] = _RespWeb(
        text=f'<a href="{v2026[len(catalogo_cabys.BCCR):]}">Catálogo</a> <a href="/x/2026-04-01-equivalencias-catalogo-de-bienes.xlsx">')
    web[v2026] = _RespWeb(content=_excel_cabys([("2399999009900", "Café", 0.13), ("2222222222222", "Nuevo", 0.04)]),
                          headers={"ETag": "b"})
    r = catalogo_cabys.actualizar_si_hay_version_nueva()
    assert r["cambios"] is True and r["url"] == v2026 and r["eliminados"] == 1
    db.expire_all()
    assert {c.codigo for c in db.query(CodigoCabys)} == {"2399999009900", "2222222222222"}
    assert db.query(Auditoria).filter(Auditoria.accion == "cabys.actualizado").count() == 2
    catalogo_cabys._completo["hasta"] = 0


def test_muestra_de_cabys_corrige_cambios_de_hacienda(db, hacienda_falsa, monkeypatch):
    from api.models.database import CodigoCabys
    from api.services import catalogo_cabys
    respuestas, _, _ = hacienda_falsa
    monkeypatch.setattr(catalogo_cabys, "MINIMO_COMPLETO", 2)
    catalogo_cabys.importar_excel(_excel_cabys([("2399999009900", "Café", 0.13), ("1111111111111", "Té", 0.13)]))
    oficiales = {"2399999009900": [{"codigo": "2399999009900", "descripcion": "Café", "impuesto": 1}],
                 "1111111111111": []}

    def get(url, params=None, timeout=None):
        return _RespHacienda(200, oficiales[params["codigo"]])
    monkeypatch.setattr(hacienda_publico.requests, "get", get)
    r = hacienda_publico.verificar_muestra_cabys(pausa=0)
    assert r == {"revisados": 2, "corregidos": 1, "eliminados": 1, "detenido": False}
    db.expire_all()
    assert [(c.codigo, float(c.impuesto)) for c in db.query(CodigoCabys)] == [("2399999009900", 1.0)]
    catalogo_cabys._completo["hasta"] = 0
