"""Categorías de productos, descuentos automáticos y combos."""
from decimal import Decimal

from api.models.database import Producto
from tests.conftest import factura_payload

CAT = "/api/v1/catalogo/categorias"
PROD = "/api/v1/catalogo/productos"
DESC = "/api/v1/catalogo/descuentos"


def _producto(client, codigo, existencia="10", **cambios):
    datos = {"codigo": codigo, "codigo_cabys": "4299900000000", "descripcion": f"Producto {codigo}",
             "precio_unitario": "1000", "controla_inventario": True, "existencia_inicial": existencia, **cambios}
    r = client.post(PROD, json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def _venta(producto, cantidad):
    return factura_payload(productos=[{
        "codigo_cabys": producto["codigo_cabys"], "codigo_comercial": producto["codigo"], "descripcion": producto["descripcion"],
        "cantidad": str(cantidad), "unidad_medida": "Unid", "precio_unitario": "3000", "codigo_tarifa_iva": "08",
        "producto_id": producto["id"],
    }])


def _existencia(db, pid):
    db.expire_all()
    return db.get(Producto, pid).existencia


def test_categorias(client):
    cat = client.post(CAT, json={"nombre": "Bebidas"}).json()
    assert client.post(CAT, json={"nombre": "Bebidas"}).status_code == 409
    p = _producto(client, "COLA", categoria_id=cat["id"])
    assert p["categoria"] == "Bebidas"
    _producto(client, "PAN")
    assert [x["codigo"] for x in client.get(PROD, params={"categoria_id": cat["id"]}).json()] == ["COLA"]
    assert client.get(CAT).json()[0]["productos"] == 1

    assert client.put(CAT + f"/{cat['id']}", json={"nombre": "Refrescos"}).json()["nombre"] == "Refrescos"
    # Quitar la categoría de un producto
    assert client.patch(f"{PROD}/{p['id']}", json={"categoria_id": ""}).json()["categoria"] is None
    client.patch(f"{PROD}/{p['id']}", json={"categoria_id": cat["id"]})
    # Borrar la categoría deja el producto sin categoría
    assert client.delete(CAT + f"/{cat['id']}").status_code == 204
    assert client.get(f"{PROD}/{p['id']}").json()["categoria_id"] is None


def test_combo_descuenta_componentes(db, client):
    hamburguesa = _producto(client, "HAMB", "10")
    papas = _producto(client, "PAPAS", "20")
    r = client.post(PROD, json={"codigo": "COMBO1", "codigo_cabys": "4299900000000", "descripcion": "Combo hamburguesa",
                                "precio_unitario": "3000", "controla_inventario": True,
                                "componentes": [{"producto_id": hamburguesa["id"], "cantidad": "1"},
                                                {"producto_id": papas["id"], "cantidad": "2"}]})
    assert r.status_code == 201, r.text
    combo = r.json()
    assert combo["es_combo"] and not combo["controla_inventario"] and len(combo["componentes"]) == 2
    assert Decimal(combo["combo_disponible"]) == 10

    assert client.post("/api/v1/facturas", json=_venta(combo, 3)).status_code == 202
    assert _existencia(db, hamburguesa["id"]) == 7 and _existencia(db, papas["id"]) == 14
    assert Decimal(client.get(f"{PROD}/{combo['id']}").json()["combo_disponible"]) == 7

    r = client.post("/api/v1/facturas", json=_venta(combo, 8))
    assert r.status_code == 422 and "Existencia insuficiente" in r.json()["detail"]


def test_combo_no_contiene_combos_ni_repetidos(client):
    a = _producto(client, "A")
    combo = client.post(PROD, json={"codigo": "C1", "codigo_cabys": "4299900000000", "descripcion": "Combo",
                                    "componentes": [{"producto_id": a["id"], "cantidad": "1"}]}).json()
    r = client.post(PROD, json={"codigo": "C2", "codigo_cabys": "4299900000000", "descripcion": "Combo de combo",
                                "componentes": [{"producto_id": combo["id"], "cantidad": "1"}]})
    assert r.status_code == 422
    r = client.patch(f"{PROD}/{combo['id']}", json={"componentes": [{"producto_id": a["id"], "cantidad": "1"},
                                                                    {"producto_id": a["id"], "cantidad": "2"}]})
    assert r.status_code == 422
    # Lista vacía: deja de ser combo
    assert client.patch(f"{PROD}/{combo['id']}", json={"componentes": []}).json()["es_combo"] is False


def test_descuentos(client):
    cat = client.post(CAT, json={"nombre": "Ferretería"}).json()
    p = _producto(client, "MART")
    r = client.post(DESC, json={"nombre": "10% ferretería", "tipo": "porcentaje", "valor": "10", "alcance": "categoria",
                                "categoria_id": cat["id"]})
    assert r.status_code == 201, r.text
    client.post(DESC, json={"nombre": "Martillo 200 menos", "tipo": "monto", "valor": "200", "alcance": "producto",
                            "producto_id": p["id"], "cantidad_minima": "3", "codigo_descuento": "04"})
    client.post(DESC, json={"nombre": "Vencido", "tipo": "porcentaje", "valor": "5", "alcance": "todos",
                            "desde": "2020-01-01", "hasta": "2020-12-31"})
    assert len(client.get(DESC).json()) == 3
    vigentes = {d["nombre"] for d in client.get(DESC, params={"vigentes": True}).json()}
    assert vigentes == {"10% ferretería", "Martillo 200 menos"}

    assert client.post(DESC, json={"nombre": "x", "tipo": "porcentaje", "valor": "150", "alcance": "todos"}).status_code == 422
    assert client.post(DESC, json={"nombre": "x", "tipo": "monto", "valor": "1", "alcance": "categoria"}).status_code == 422
    did = r.json()["id"]
    assert client.put(f"{DESC}/{did}", json={**r.json(), "activo": False, "valor": "15"}).json()["activo"] is False
    assert client.delete(f"{DESC}/{did}").status_code == 204
