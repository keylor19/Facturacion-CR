"""Módulo de contabilidad: acceso solo del contador, asientos, contabilización automática, reportes e importación de XML."""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from api.models.database import Emisor, EstadoFactura, Factura
from api.models.schemas import FacturaRequest
from api.services import usuarios
from api.services.fechas import ahora_cr
from api.services.xml_generator import generar_xml
from tests.conftest import factura_payload, persona_emisor_prueba

PASSWORD = "Clave-Segura-2026"
CONTA = "/api/v1/contabilidad"


def _sesion(app_client, email):
    token = app_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}", "X-API-Key": ""}


def _cuenta(app_client, h, codigo):
    return next(c for c in app_client.get(f"{CONTA}/cuentas", headers=h).json() if c["codigo"] == codigo)


def test_el_contador_escoge_sus_empresas_y_el_dueno_ve_su_contabilidad(db, emisor, app_client, admin, client):
    r = admin.post("/api/v1/usuarios", json={"email": "conta@despacho.cr", "nombre": "Conta", "password": PASSWORD,
                                             "es_contador": True})
    assert r.status_code == 201, r.text
    h = _sesion(app_client, "conta@despacho.cr")
    assert app_client.get("/api/v1/auth/yo", headers=h).json()["empresas"] == []

    # El contador busca la empresa por su cédula y empieza a llevarla
    assert app_client.get(f"{CONTA}/buscar-empresa", headers=h, params={"cedula": "3101000000"}).status_code == 404
    e = app_client.get(f"{CONTA}/buscar-empresa", headers=h, params={"cedula": emisor.numero_identificacion}).json()
    assert e["id"] == emisor.id and e["ya_la_lleva"] is False
    assert app_client.post(f"{CONTA}/empresas/{emisor.id}/vincular", headers=h).status_code == 201
    h = _sesion(app_client, "conta@despacho.cr")
    assert app_client.post(f"{CONTA}/empresas/{emisor.id}/vincular", headers=h).status_code == 409
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["es_contador"] is True and [x["id"] for x in yo["empresas"]] == [emisor.id] and yo["permisos"] == ["contabilidad"]
    h["X-Emisor-Id"] = emisor.id
    assert app_client.get(f"{CONTA}/cuentas", headers=h).status_code == 200
    # No factura ni ve el resto del sistema
    assert app_client.get("/api/v1/facturas", headers=h).status_code == 403
    assert app_client.post("/api/v1/facturas", headers=h, json=factura_payload()).status_code == 403
    assert app_client.get("/api/v1/saldo", headers=h).status_code == 403

    # El dueño ve la contabilidad de su empresa; sus demás usuarios, el administrador y la API key no
    usuarios.crear_usuario(db, "duena@pruebas.cr", "Dueña", PASSWORD, False, emisor.id, "dueno")
    usuarios.crear_usuario(db, "caja@pruebas.cr", "Caja", PASSWORD, False, emisor.id, "cajero")
    duena = _sesion(app_client, "duena@pruebas.cr")
    assert app_client.get(f"{CONTA}/cuentas", headers=duena).status_code == 200
    assert app_client.get("/api/v1/reportes/resumen-iva", params={"anio": 2026, "mes": 1}, headers=duena).status_code == 200
    assert app_client.post(f"{CONTA}/empresas/{emisor.id}/vincular", headers=duena).status_code == 403   # no es contador
    caja = _sesion(app_client, "caja@pruebas.cr")
    assert app_client.get(f"{CONTA}/cuentas", headers=caja).status_code == 403
    assert admin.get(f"{CONTA}/cuentas", headers={"X-Emisor-Id": emisor.id}).status_code == 403
    assert client.get("/api/v1/reportes/resumen-iva", params={"anio": 2026, "mes": 1}).status_code == 403

    # El dueño ve quién lleva su contabilidad y le quita el acceso
    lista = app_client.get("/api/v1/empresa/contadores", headers=duena).json()
    assert [c["email"] for c in lista] == ["conta@despacho.cr"]
    assert app_client.delete(f"/api/v1/empresa/contadores/{lista[0]['id']}", headers=duena).status_code == 204
    h = _sesion(app_client, "conta@despacho.cr")
    assert app_client.get("/api/v1/auth/yo", headers=h).json()["empresas"] == []


def test_contabilizar_ventas_y_estados_financieros(db, client, contador):
    assert client.post(f"{CONTA}/catalogo-base", headers=contador).status_code == 201
    fid = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    f = db.get(Factura, fid)
    f.estado = EstadoFactura.ACEPTADO
    db.commit()
    hoy = ahora_cr().date()

    r = client.post(f"{CONTA}/contabilizar", headers=contador, json={"anio": hoy.year, "mes": hoy.month})
    assert r.status_code == 200, r.text
    assert r.json()["creados"] == 1
    assert client.post(f"{CONTA}/contabilizar", headers=contador, json={"anio": hoy.year, "mes": hoy.month}).json()["creados"] == 0

    asiento = client.get(f"{CONTA}/asientos", headers=contador).json()[0]
    lineas = {ln["codigo"]: ln for ln in asiento["lineas"]}
    assert Decimal(lineas["1.1.01"]["debe"]) == Decimal("116700.00")      # caja (venta de contado)
    assert Decimal(lineas["4.1"]["haber"]) == Decimal("105000.00")        # ventas netas
    assert Decimal(lineas["2.1.02"]["haber"]) == Decimal("11700.00")      # IVA por pagar

    desde = hoy.replace(day=1).isoformat()
    comprobacion = client.get(f"{CONTA}/reportes/comprobacion", headers=contador, params={"desde": desde}).json()
    assert comprobacion["cuadra"] is True
    resultados = client.get(f"{CONTA}/reportes/resultados", headers=contador, params={"desde": desde}).json()
    assert Decimal(resultados["utilidad_neta"]) == Decimal("105000.00")
    balance = client.get(f"{CONTA}/reportes/balance", headers=contador).json()
    assert balance["cuadra"] is True and Decimal(balance["total_activo"]) == Decimal("116700.00")
    caja = _cuenta(client, contador, "1.1.01")
    mayor = client.get(f"{CONTA}/reportes/mayor", headers=contador, params={"cuenta_id": caja["id"], "desde": desde}).json()
    assert Decimal(mayor["saldo_final"]) == Decimal("116700.00")
    assert client.get(f"{CONTA}/reportes/balance", headers=contador, params={"formato": "csv"}).text.count("Total activo") == 1


def test_asientos_manuales_y_cierre_de_mes(client, contador):
    client.post(f"{CONTA}/catalogo-base", headers=contador)
    caja, capital = _cuenta(client, contador, "1.1.01"), _cuenta(client, contador, "3.1")
    grupo = _cuenta(client, contador, "1.1")
    dia = date(2026, 3, 15).isoformat()
    descuadrado = {"fecha": dia, "descripcion": "Aporte", "lineas": [
        {"cuenta_id": caja["id"], "debe": "1000"}, {"cuenta_id": capital["id"], "haber": "900"}]}
    assert client.post(f"{CONTA}/asientos", headers=contador, json=descuadrado).status_code == 422
    a_grupo = {"fecha": dia, "descripcion": "Aporte", "lineas": [
        {"cuenta_id": grupo["id"], "debe": "1000"}, {"cuenta_id": capital["id"], "haber": "1000"}]}
    assert client.post(f"{CONTA}/asientos", headers=contador, json=a_grupo).status_code == 422
    bueno = {"fecha": dia, "descripcion": "Aporte de capital", "lineas": [
        {"cuenta_id": caja["id"], "debe": "1000"}, {"cuenta_id": capital["id"], "haber": "1000"}]}
    r = client.post(f"{CONTA}/asientos", headers=contador, json=bueno)
    assert r.status_code == 201 and r.json()["numero"] == 1

    assert client.post(f"{CONTA}/periodos", headers=contador, json={"anio": 2026, "mes": 3}).status_code == 201
    assert client.post(f"{CONTA}/asientos", headers=contador, json=bueno).status_code == 409
    assert client.post(f"{CONTA}/asientos/{r.json()['id']}/anular", headers=contador).status_code == 409
    assert client.delete(f"{CONTA}/periodos/2026/3", headers=contador).status_code == 204
    assert client.post(f"{CONTA}/asientos/{r.json()['id']}/anular", headers=contador).json()["anulado"] is True


def test_empresa_propia_con_carga_de_xml(db, app_client, admin):
    usuarios.crear_usuario(db, "conta@despacho.cr", "Conta", PASSWORD, False, None, es_contador=True)
    h = _sesion(app_client, "conta@despacho.cr")
    r = app_client.post(f"{CONTA}/empresas", headers=h, json={
        "tipo_identificacion": "02", "numero_identificacion": "3101777888", "nombre": "Ferretería El Clavo S.A.",
        "codigo_actividad": "475201", "correo": "info@elclavo.cr", "provincia": "1", "canton": "01", "distrito": "01",
        "otras_senas": "Centro"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    h["X-Emisor-Id"] = eid
    # El administrador no la ve como cliente del servicio
    assert eid not in [e["id"] for e in admin.get("/api/v1/emisores").json()]

    # XML de una venta emitida en otro sistema por la ferretería
    datos = FacturaRequest(**factura_payload())
    fecha = datetime(2026, 4, 10, 10, 0, tzinfo=ZoneInfo("America/Costa_Rica"))
    consecutivo = "00100001010000000077"
    clave = "506" + "100426" + "003101777888" + consecutivo + "1" + "87654321"
    persona = persona_emisor_prueba(numero_identificacion="3101777888", nombre="Ferretería El Clavo S.A.")
    xml, _, _ = generar_xml(clave, consecutivo, fecha, persona, datos)
    r = app_client.post(f"{CONTA}/importar", headers=h, files=[("archivos", ("venta.xml", xml.encode(), "text/xml"))])
    assert r.status_code == 200 and r.json()["ventas"] == 1, r.text
    otra = app_client.post(f"{CONTA}/importar", headers=h, files=[("archivos", ("venta.xml", xml.encode(), "text/xml"))]).json()
    assert otra["ventas"] == 0 and "ya está cargado" in otra["errores"][0]["error"]

    f = db.query(Factura).filter_by(clave=clave).one()
    assert f.importada and f.estado == EstadoFactura.ACEPTADO and Decimal(f.monto_total) == Decimal("116700")
    assert app_client.post(f"{CONTA}/contabilizar", headers=h, json={"anio": 2026, "mes": 4}).json()["creados"] == 1
    iva = app_client.get("/api/v1/reportes/resumen-iva", headers=h, params={"anio": 2026, "mes": 4}).json()
    assert Decimal(iva["iva_debito_fiscal"]) == Decimal("11700.00")

    # Una empresa que ya está inscrita no se puede agregar: la asigna el administrador
    assert db.get(Emisor, eid).solo_contabilidad is True
    r = app_client.post(f"{CONTA}/empresas", headers=h, json={
        "tipo_identificacion": "02", "numero_identificacion": "3101777888", "nombre": "Otra", "codigo_actividad": "475201",
        "correo": "x@x.cr", "provincia": "1", "canton": "01", "distrito": "01", "otras_senas": "Centro"})
    assert r.status_code == 409


def test_costo_de_ventas_desde_el_inventario_y_cierre_anual(db, client, contador):
    client.post(f"{CONTA}/catalogo-base", headers=contador)
    p = client.post("/api/v1/catalogo/productos", json={
        "codigo": "MART", "codigo_cabys": "4292199990200", "descripcion": "Martillo", "precio_unitario": "10000",
        "costo_unitario": "6000", "controla_inventario": True, "existencia_inicial": "10"})
    assert p.status_code == 201, p.text
    linea = {"producto_id": p.json()["id"], "codigo_cabys": "4292199990200", "descripcion": "Martillo", "cantidad": "3",
             "unidad_medida": "Unid", "precio_unitario": "10000", "codigo_tarifa_iva": "08"}
    fid = client.post("/api/v1/facturas", json=factura_payload(productos=[linea])).json()["factura_id"]
    db.get(Factura, fid).estado = EstadoFactura.ACEPTADO
    db.commit()
    hoy = ahora_cr().date()

    r = client.post(f"{CONTA}/contabilizar", headers=contador, json={"anio": hoy.year, "mes": hoy.month}).json()
    assert r["por_origen"] == {"venta": 1, "costo": 1, "inventario": 1} and r["productos_sin_costo"] == []
    asientos = {a["origen"]: a for a in client.get(f"{CONTA}/asientos", headers=contador).json()}
    costo = {ln["codigo"]: ln for ln in asientos["costo"]["lineas"]}
    assert Decimal(costo["5.1"]["debe"]) == Decimal("18000.00") and Decimal(costo["1.1.04"]["haber"]) == Decimal("18000.00")
    inicial = {ln["codigo"]: ln for ln in asientos["inventario"]["lineas"]}   # 10 x 6 000 de existencia inicial
    assert Decimal(inicial["1.1.04"]["debe"]) == Decimal("60000.00") and Decimal(inicial["3.3"]["haber"]) == Decimal("60000.00")

    # Cierre del año: ventas 30 000 - costo 18 000 = utilidad 12 000
    propuesta = client.get(f"{CONTA}/cierre-anual", headers=contador, params={"anio": hoy.year}).json()
    lineas = {ln["codigo"]: ln for ln in propuesta["lineas"]}
    assert Decimal(propuesta["utilidad"]) == Decimal("12000.00")
    assert Decimal(lineas["4.1"]["debe"]) == Decimal("30000.00") and Decimal(lineas["5.1"]["haber"]) == Decimal("18000.00")
    assert Decimal(lineas["3.3"]["haber"]) == Decimal("12000.00") and propuesta["registrado"] is None
    archivo = client.get(f"{CONTA}/cierre-anual", headers=contador, params={"anio": hoy.year, "formato": "csv"})
    assert archivo.status_code == 200 and "Asiento de cierre anual" in archivo.text and "Propuesta" in archivo.text

    r = client.post(f"{CONTA}/cierre-anual", headers=contador, json={"anio": hoy.year})
    assert r.status_code == 201 and r.json()["origen"] == "cierre" and r.json()["fecha"] == f"{hoy.year}-12-31"
    assert client.post(f"{CONTA}/cierre-anual", headers=contador, json={"anio": hoy.year}).status_code == 409
    assert "Registrado como asiento" in client.get(f"{CONTA}/cierre-anual", headers=contador,
                                                    params={"anio": hoy.year, "formato": "csv"}).text
    # El estado de resultados del año sigue mostrando la utilidad; el balance cuadra
    desde, hasta = f"{hoy.year}-01-01", f"{hoy.year}-12-31"
    resultados = client.get(f"{CONTA}/reportes/resultados", headers=contador, params={"desde": desde, "hasta": hasta}).json()
    assert Decimal(resultados["utilidad_neta"]) == Decimal("12000.00")
    balance = client.get(f"{CONTA}/reportes/balance", headers=contador, params={"fecha": hasta}).json()
    assert balance["cuadra"] is True and Decimal(balance["resultado_acumulado"]) == 0
