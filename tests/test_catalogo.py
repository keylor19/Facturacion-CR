"""Facturación en línea: catálogo de clientes y productos, inventario, logo y módulo por empresa."""
from decimal import Decimal
from io import BytesIO

import pytest

from api.models.database import EstadoFactura, Factura, MovimientoInventario, Producto
from api.services import inventario, usuarios
from tests.conftest import crear_emisor, factura_payload

CLIENTE = {"tipo_identificacion": "02", "numero_identificacion": "3101777777", "nombre": "Ferretería El Clavo S.A.",
           "correo": "compras@elclavo.cr"}
PRODUCTO = {"codigo": "MART-01", "codigo_cabys": "4299900000000", "descripcion": "Martillo de uña 16 oz",
            "unidad_medida": "Unid", "precio_unitario": "5000", "codigo_tarifa_iva": "08",
            "costo_unitario": "3000", "controla_inventario": True, "existencia_inicial": "10",
            "existencia_minima": "3"}


def _venta(producto_id, cantidad="3", tipo="01"):
    return factura_payload(tipo_documento=tipo, productos=[{
        "codigo_cabys": PRODUCTO["codigo_cabys"], "codigo_comercial": PRODUCTO["codigo"],
        "descripcion": PRODUCTO["descripcion"], "cantidad": cantidad, "unidad_medida": "Unid",
        "precio_unitario": PRODUCTO["precio_unitario"], "codigo_tarifa_iva": "08", "producto_id": producto_id,
    }])


def _existencia(db, producto_id) -> Decimal:
    db.expire_all()
    return db.get(Producto, producto_id).existencia


@pytest.fixture
def producto(client):
    r = client.post("/api/v1/catalogo/productos", json=PRODUCTO)
    assert r.status_code == 201, r.text
    return r.json()


# --- Clientes ----------------------------------------------------------------------

def test_clientes_crud_y_busqueda(client):
    r = client.post("/api/v1/catalogo/clientes", json=CLIENTE)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert client.post("/api/v1/catalogo/clientes", json=CLIENTE).status_code == 409
    assert [c["id"] for c in client.get("/api/v1/catalogo/clientes", params={"q": "clavo"}).json()] == [cid]
    assert [c["id"] for c in client.get("/api/v1/catalogo/clientes", params={"q": "3101777"}).json()] == [cid]
    assert client.get("/api/v1/catalogo/clientes", params={"q": "otra"}).json() == []

    r = client.put(f"/api/v1/catalogo/clientes/{cid}", json={**CLIENTE, "telefono": "22223333"})
    assert r.json()["telefono"] == "22223333"
    assert client.delete(f"/api/v1/catalogo/clientes/{cid}").status_code == 204
    assert client.get("/api/v1/catalogo/clientes").json() == []
    # Volver a crearlo lo reactiva
    assert client.post("/api/v1/catalogo/clientes", json=CLIENTE).json()["id"] == cid


def test_cliente_valida_identificacion(client):
    r = client.post("/api/v1/catalogo/clientes", json={**CLIENTE, "numero_identificacion": "123"})
    assert r.status_code == 422


def test_catalogo_aislado_entre_empresas(db, client, producto, admin):
    cid = client.post("/api/v1/catalogo/clientes", json=CLIENTE).json()["id"]
    otra = crear_emisor(db, numero="3101654321", nombre="Otra S.A.")
    h = {"X-Emisor-Id": otra.id}
    assert admin.get("/api/v1/catalogo/clientes", headers=h).json() == []
    assert admin.get("/api/v1/catalogo/productos", headers=h).json() == []
    assert admin.get(f"/api/v1/catalogo/clientes/{cid}", headers=h).status_code == 404
    assert admin.get(f"/api/v1/catalogo/productos/{producto['id']}", headers=h).status_code == 404
    assert admin.post("/api/v1/inventario/movimientos", headers=h,
                      json={"producto_id": producto["id"], "tipo": "entrada", "cantidad": "5"}).status_code == 422
    # Tampoco puede vender un producto de otra empresa
    r = admin.post("/api/v1/facturas", headers=h, json=_venta(producto["id"]))
    assert r.status_code == 422 and "catálogo" in r.json()["detail"]


# --- Productos e inventario ------------------------------------------------------------

def test_producto_con_existencia_inicial(client, producto):
    assert producto["existencia"] == "10.000" and producto["bajo_minimo"] is False
    movs = client.get("/api/v1/inventario/movimientos", params={"producto_id": producto["id"]}).json()
    assert [(m["tipo"], m["cantidad"], m["nota"]) for m in movs] == [("entrada", "10.000", "Existencia inicial")]
    assert client.post("/api/v1/catalogo/productos", json=PRODUCTO).status_code == 409   # código repetido


def test_venta_descuenta_inventario(db, client, producto):
    r = client.post("/api/v1/facturas", json=_venta(producto["id"], "3"))
    assert r.status_code == 202, r.text
    assert _existencia(db, producto["id"]) == Decimal("7")
    mov = db.query(MovimientoInventario).filter_by(tipo="venta").one()
    assert mov.cantidad == Decimal("-3") and mov.factura_id == r.json()["factura_id"]
    assert mov.nota.startswith("Factura electrónica ")

    # Tiquete también descuenta; llega al mínimo
    client.post("/api/v1/facturas", json=_venta(producto["id"], "4", tipo="04"))
    p = client.get(f"/api/v1/catalogo/productos/{producto['id']}").json()
    assert p["existencia"] == "3.000" and p["bajo_minimo"] is True
    assert [x["id"] for x in client.get("/api/v1/catalogo/productos", params={"bajo_minimo": True}).json()] == [producto["id"]]


def test_sin_existencia_no_se_emite_ni_se_cobra(db, client, producto):
    antes = client.get("/api/v1/saldo").json()["disponible"]
    r = client.post("/api/v1/facturas", json=_venta(producto["id"], "11"))
    assert r.status_code == 422 and "Existencia insuficiente" in r.json()["detail"]
    assert _existencia(db, producto["id"]) == Decimal("10")
    assert db.query(Factura).count() == 0
    assert client.get("/api/v1/saldo").json()["disponible"] == antes


def test_lineas_repetidas_se_suman(db, client, producto):
    datos = _venta(producto["id"], "6")
    datos["productos"].append(dict(datos["productos"][0]))
    r = client.post("/api/v1/facturas", json=datos)   # 6 + 6 = 12 > 10
    assert r.status_code == 422


def test_servicio_sin_inventario_no_genera_movimientos(db, client):
    p = client.post("/api/v1/catalogo/productos", json={
        "codigo": "SERV-1", "codigo_cabys": "8314100000000", "descripcion": "Consultoría", "unidad_medida": "Sp",
        "es_servicio": True, "precio_unitario": "25000"}).json()
    datos = _venta(p["id"], "2")
    datos["productos"][0].update(unidad_medida="Sp", codigo_cabys="8314100000000")
    assert client.post("/api/v1/facturas", json=datos).status_code == 202
    assert db.query(MovimientoInventario).count() == 0


def test_anulacion_devuelve_inventario(db, client, producto):
    fid = client.post("/api/v1/facturas", json=_venta(producto["id"], "4")).json()["factura_id"]
    f = db.get(Factura, fid)
    f.estado = EstadoFactura.ACEPTADO
    db.commit()
    r = client.post(f"/api/v1/facturas/{fid}/anular", json={"razon": "Cliente devolvió la mercadería"})
    assert r.status_code == 202, r.text
    assert _existencia(db, producto["id"]) == Decimal("10")
    assert db.query(MovimientoInventario).filter_by(tipo="devolucion").one().cantidad == Decimal("4")


def test_nota_de_credito_por_descuento_no_mueve_inventario(db, client, producto):
    datos = _venta(producto["id"], "1", tipo="03")
    datos["referencia"] = {"tipo_documento": "01", "numero": "5" * 50, "fecha_emision": "2026-10-01T10:00:00",
                           "codigo": "03", "razon": "Descuento posterior"}
    assert client.post("/api/v1/facturas", json=datos).status_code == 202
    assert _existencia(db, producto["id"]) == Decimal("10")


def test_rechazo_de_hacienda_revierte_inventario(db, client, producto, monkeypatch):
    from workers import tasks
    fid = client.post("/api/v1/facturas", json=_venta(producto["id"], "5")).json()["factura_id"]
    assert _existencia(db, producto["id"]) == Decimal("5")

    monkeypatch.setattr(tasks.hacienda_client, "interpretar_respuesta",
                        lambda data: {"estado": "rechazado", "xml": None, "mensaje": "Rechazado"})
    f = db.get(Factura, fid)
    tasks.aplicar_respuesta_hacienda(db, f, {}, "CONSULTA")
    assert _existencia(db, producto["id"]) == Decimal("10")
    # Una segunda respuesta de rechazo no lo vuelve a sumar
    tasks.aplicar_respuesta_hacienda(db, db.get(Factura, fid), {}, "CALLBACK")
    assert _existencia(db, producto["id"]) == Decimal("10")
    assert db.query(MovimientoInventario).filter_by(tipo="reverso").count() == 1


def test_movimientos_manuales(db, client, producto):
    pid = producto["id"]
    url = "/api/v1/inventario/movimientos"
    # Entrada con costo: promedio ponderado (10 a 3000 + 10 a 4000 = 3500)
    r = client.post(url, json={"producto_id": pid, "tipo": "entrada", "cantidad": "10", "costo_unitario": "4000",
                               "nota": "Compra a Proveedor X"})
    assert r.status_code == 201 and r.json()["existencia_resultante"] == "20.000"
    assert client.get(f"/api/v1/catalogo/productos/{pid}").json()["costo_unitario"] == "3500.00000"
    # Salida mayor a la existencia
    assert client.post(url, json={"producto_id": pid, "tipo": "salida", "cantidad": "21"}).status_code == 422
    assert client.post(url, json={"producto_id": pid, "tipo": "salida", "cantidad": "2", "nota": "Merma"}).status_code == 201
    # Ajuste por conteo físico: había 18, se contaron 15
    r = client.post(url, json={"producto_id": pid, "tipo": "ajuste", "cantidad": "15"})
    assert r.json()["cantidad"] == "-3.000" and r.json()["existencia_resultante"] == "15.000"
    assert client.post(url, json={"producto_id": pid, "tipo": "ajuste", "cantidad": "15"}).status_code == 422
    assert client.post(url, json={"producto_id": pid, "tipo": "entrada", "cantidad": "0"}).status_code == 422

    resumen = client.get("/api/v1/inventario/resumen").json()
    assert resumen["productos_con_inventario"] == 1 and Decimal(resumen["valor_al_costo"]) == Decimal("52500")
    csv = client.get("/api/v1/inventario/existencias.csv").text
    assert "MART-01" in csv and "52500" in csv
    assert movimientos_usuario(client, pid)


def movimientos_usuario(client, pid):
    movs = client.get("/api/v1/inventario/movimientos", params={"producto_id": pid}).json()
    return all(m["usuario"] for m in movs if m["tipo"] in ("entrada", "salida", "ajuste"))


def test_producto_sin_inventario_no_acepta_movimientos(client):
    p = client.post("/api/v1/catalogo/productos", json={**PRODUCTO, "codigo": "X", "controla_inventario": False}).json()
    r = client.post("/api/v1/inventario/movimientos", json={"producto_id": p["id"], "tipo": "entrada", "cantidad": "1"})
    assert r.status_code == 422


def test_actualizar_producto_no_cambia_existencia(client, producto):
    r = client.patch(f"/api/v1/catalogo/productos/{producto['id']}",
                     json={"precio_unitario": "5500", "existencia": "999", "existencia_minima": None})
    assert r.status_code == 200
    assert r.json()["precio_unitario"] == "5500.00000" and r.json()["existencia"] == "10.000"
    assert r.json()["existencia_minima"] is None


# --- Módulo de facturación en línea por empresa ----------------------------------------

def test_modulo_desactivado_bloquea_al_usuario_de_la_empresa(db, emisor, app_client, admin, api_key):
    usuarios.crear_usuario(db, "cajera@empresa.cr", "Cajera", "Clave-Segura-2026", False, emisor.id)
    token = app_client.post("/api/v1/auth/login", json={"email": "cajera@empresa.cr", "password": "Clave-Segura-2026"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert app_client.get("/api/v1/catalogo/productos", headers=h).status_code == 200

    r = admin.patch(f"/api/v1/emisores/{emisor.id}", json={"facturacion_web": False})
    assert r.json()["facturacion_web"] is False
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["empresas"][0]["facturacion_web"] is False
    for metodo, ruta in [("get", "/api/v1/catalogo/productos"), ("get", "/api/v1/catalogo/clientes"),
                         ("get", "/api/v1/inventario/movimientos")]:
        assert getattr(app_client, metodo)(ruta, headers=h).status_code == 403, ruta
    r = app_client.post("/api/v1/facturas", json=factura_payload(), headers=h)
    assert r.status_code == 403 and "facturación en línea" in r.json()["detail"]
    # Puede seguir consultando sus comprobantes y reportes
    assert app_client.get("/api/v1/facturas", headers=h).status_code == 200
    # El sistema integrado por API y el administrador no se ven afectados
    assert app_client.post("/api/v1/facturas", json=factura_payload(), headers={"X-API-Key": api_key}).status_code == 202
    assert admin.get("/api/v1/catalogo/productos", headers={"X-Emisor-Id": emisor.id}).status_code == 200


# --- Logo -------------------------------------------------------------------------

def _png(ancho=200, alto=80) -> bytes:
    from PIL import Image
    salida = BytesIO()
    Image.new("RGB", (ancho, alto), (20, 60, 120)).save(salida, format="PNG")
    return salida.getvalue()


def test_logo_en_el_pdf(db, client):
    r = client.put("/api/v1/empresa/logo", files={"archivo": ("logo.png", _png(), "image/png")})
    assert r.status_code == 204, r.text
    assert client.get("/api/v1/empresa/logo").content.startswith(b"\x89PNG")
    fid = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    pdf = client.get(f"/api/v1/facturas/{fid}/pdf").content
    assert pdf.startswith(b"%PDF") and b"/Subtype /Image" in pdf

    assert client.delete("/api/v1/empresa/logo").status_code == 204
    assert client.get("/api/v1/empresa/logo").status_code == 404
    assert b"/Subtype /Image" not in client.get(f"/api/v1/facturas/{fid}/pdf").content


@pytest.mark.parametrize("contenido", [b"GIF89a....", b"<svg onload=alert(1)>", b"\x89PNG\r\n\x1a\nbasura"])
def test_logo_rechaza_archivos_invalidos(client, contenido):
    r = client.put("/api/v1/empresa/logo", files={"archivo": ("logo.png", contenido, "image/png")})
    assert r.status_code == 422


def test_logo_demasiado_grande(client):
    r = client.put("/api/v1/empresa/logo", files={"archivo": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 400_000, "image/png")})
    assert r.status_code == 413


def test_revertir_documento_sin_movimientos_no_hace_nada(db, client):
    fid = client.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    assert inventario.revertir_documento(db, db.get(Factura, fid)) == 0


def test_conexion_api_se_activa_por_empresa(db, emisor, api_key, admin, cola):
    """La API y la facturación en línea se venden por separado."""
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app, headers={"X-API-Key": api_key})
    app_client = TestClient(app)
    usuarios.crear_usuario(db, "cajera@empresa.cr", "Cajera", "Clave-Segura-2026", False, emisor.id)
    token = app_client.post("/api/v1/auth/login", json={"email": "cajera@empresa.cr", "password": "Clave-Segura-2026"}).json()["token"]
    panel = {"Authorization": f"Bearer {token}"}

    r = admin.patch(f"/api/v1/emisores/{emisor.id}", json={"acceso_api": False})
    assert r.json()["acceso_api"] is False
    r = client.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 403 and "API" in r.json()["detail"]
    assert client.get("/api/v1/facturas").status_code == 403
    assert admin.post("/api/v1/api-keys", json={"nombre": "POS", "emisor_id": emisor.id}).status_code == 409
    # El panel de la empresa sigue funcionando
    assert app_client.post("/api/v1/facturas", json=factura_payload(), headers=panel).status_code == 202

    admin.patch(f"/api/v1/emisores/{emisor.id}", json={"acceso_api": True})
    assert client.post("/api/v1/facturas", json=factura_payload()).status_code == 202
