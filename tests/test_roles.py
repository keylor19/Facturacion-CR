"""Roles de los usuarios de una empresa: dueño, contador y cajero."""
import pytest

from api.services import usuarios
from tests.conftest import crear_emisor, factura_payload

PASSWORD = "Clave-Segura-2026"


def _sesion(db, c, email, emisor_id, rol):
    usuarios.crear_usuario(db, email, email.split("@")[0], PASSWORD, False, emisor_id, rol)
    token = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_cajero_vende_pero_no_anula_ni_ve_reportes(db, emisor, app_client):
    h = _sesion(db, app_client, "caja@tienda.cr", emisor.id, "cajero")
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["rol"] == "cajero" and "anular" not in yo["permisos"] and "pos" in yo["permisos"]

    r = app_client.post("/api/v1/facturas", json=factura_payload(), headers=h)
    assert r.status_code == 202, r.text
    fid = r.json()["factura_id"]
    assert app_client.get(f"/api/v1/facturas/{fid}", headers=h).status_code == 200

    r = app_client.post(f"/api/v1/facturas/{fid}/anular", json={"razon": "x"}, headers=h)
    assert r.status_code == 403 and "Cajero" in r.json()["detail"]
    nota = factura_payload(tipo_documento="03", referencia={
        "tipo_documento": "01", "numero": "5" * 50, "fecha_emision": "2026-08-20T10:00:00", "codigo": "01", "razon": "x"})
    assert app_client.post("/api/v1/facturas", json=nota, headers=h).status_code == 403
    assert app_client.get("/api/v1/reportes/resumen-iva", params={"anio": 2026, "mes": 1}, headers=h).status_code == 403
    assert app_client.get("/api/v1/recepcion", headers=h).status_code == 403
    assert app_client.get("/api/v1/usuarios", headers=h).status_code == 403
    # Ve el catálogo y registra clientes, pero no cambia precios
    assert app_client.get("/api/v1/catalogo/productos", headers=h).status_code == 200
    assert app_client.post("/api/v1/catalogo/productos", headers=h, json={
        "codigo": "P1", "descripcion": "X", "codigo_cabys": "4292199990200", "precio_unitario": "10"}).status_code == 403
    assert app_client.post("/api/v1/catalogo/clientes", headers=h, json={
        "tipo_identificacion": "01", "numero_identificacion": "206890580", "nombre": "Cliente"}).status_code == 201


def test_administrativo_maneja_proveedores_pero_no_la_caja_ni_la_contabilidad(db, emisor, app_client):
    h = _sesion(db, app_client, "conta@despacho.cr", emisor.id, "contador")
    assert app_client.get("/api/v1/reportes/resumen-iva", params={"anio": 2026, "mes": 1}, headers=h).status_code == 403
    assert app_client.get("/api/v1/recepcion", headers=h).status_code == 200
    assert app_client.get("/api/v1/cajas", headers=h).status_code == 403
    assert app_client.put("/api/v1/empresa/logo", headers=h, files={"archivo": ("l.png", b"x", "image/png")}).status_code == 403


def test_el_dueno_maneja_los_usuarios_de_su_empresa(db, emisor, app_client):
    h = _sesion(db, app_client, "duena@tienda.cr", emisor.id, "dueno")
    otra = crear_emisor(db, numero="3101654321", nombre="Otra S.A.")
    ajeno = usuarios.crear_usuario(db, "ajeno@otra.cr", "Ajeno", PASSWORD, False, otra.id)

    r = app_client.post("/api/v1/usuarios", headers=h, json={
        "email": "caja2@tienda.cr", "nombre": "Caja 2", "password": PASSWORD, "rol": "cajero"})
    assert r.status_code == 201, r.text
    nuevo = r.json()
    assert nuevo["emisor_id"] == emisor.id and nuevo["rol"] == "cajero" and nuevo["es_admin"] is False
    assert sorted(u["email"] for u in app_client.get("/api/v1/usuarios", headers=h).json()) == [
        "caja2@tienda.cr", "duena@tienda.cr"]

    # No puede crear administradores, ni usuarios de otra empresa, ni tocar usuarios ajenos
    assert app_client.post("/api/v1/usuarios", headers=h, json={
        "email": "x@tienda.cr", "nombre": "X", "password": PASSWORD, "es_admin": True}).status_code == 403
    r = app_client.post("/api/v1/usuarios", headers=h, json={
        "email": "y@tienda.cr", "nombre": "Y", "password": PASSWORD, "emisor_id": otra.id})
    assert r.status_code == 201 and r.json()["emisor_id"] == emisor.id
    assert app_client.patch(f"/api/v1/usuarios/{ajeno.id}", headers=h, json={"activo": False}).status_code == 404

    # Cambia el rol del cajero a contador
    r = app_client.patch(f"/api/v1/usuarios/{nuevo['id']}", headers=h, json={"rol": "contador"})
    assert r.status_code == 200 and r.json()["rol"] == "contador"
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert app_client.patch(f"/api/v1/usuarios/{yo['usuario']['id']}", headers=h, json={"rol": "cajero"}).status_code == 409


@pytest.mark.parametrize("rol", ["contador", "cajero"])
def test_solo_el_dueno_maneja_usuarios(db, emisor, app_client, rol):
    h = _sesion(db, app_client, f"{rol}@tienda.cr", emisor.id, rol)
    assert app_client.post("/api/v1/usuarios", headers=h, json={
        "email": "z@tienda.cr", "nombre": "Z", "password": PASSWORD}).status_code == 403


# --- La empresa configura su certificado y usuario de Hacienda ---------------------------

def test_primeros_pasos_y_configuracion_propia(db, app_client):
    from tests.conftest import CERT_PASSWORD, crear_p12
    nueva = crear_emisor(db, numero="3101123456", nombre="Recién llegada S.A.", con_certificado=False)
    h = _sesion(db, app_client, "duena@nueva.cr", nueva.id, "dueno")
    pasos = app_client.get("/api/v1/empresa/arranque", headers=h).json()
    assert pasos["listo_para_facturar"] is False
    assert {p["clave"]: p["hecho"] for p in pasos["pasos"]}["certificado"] is False

    r = app_client.put("/api/v1/empresa/certificado", headers=h, data={"password": CERT_PASSWORD},
                       files={"archivo": ("llave.p12", crear_p12("3101123456"), "application/x-pkcs12")})
    assert r.status_code == 200, r.text
    assert app_client.put("/api/v1/empresa/credenciales-hacienda", headers=h, json={
        "usuario": "cpj-3-101-123456@stag.comprobanteselectronicos.go.cr", "password": "secreta"}).status_code == 200
    assert app_client.get("/api/v1/empresa/arranque", headers=h).json()["listo_para_facturar"] is True

    cajero = _sesion(db, app_client, "caja@nueva.cr", nueva.id, "cajero")
    assert app_client.put("/api/v1/empresa/credenciales-hacienda", headers=cajero, json={
        "usuario": "cpj-otro@stag.comprobanteselectronicos.go.cr", "password": "y"}).status_code == 403

