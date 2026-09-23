"""Usuarios del panel: login, sesiones, bloqueo y permisos."""
from api.services import usuarios
from tests.conftest import factura_payload, crear_emisor

PASSWORD = "Clave-Segura-2026"


def _crear(db, email="ana@contadores.cr", es_admin=False, emisor_id=None):
    return usuarios.crear_usuario(db, email, "Ana", PASSWORD, es_admin, emisor_id)


def _login(c, email="ana@contadores.cr", password=PASSWORD):
    return c.post("/api/v1/auth/login", json={"email": email, "password": password})


def _sesion(c, **kw):
    return {"Authorization": f"Bearer {_login(c, **kw).json()['token']}"}


def test_password_se_guarda_con_scrypt(db, emisor):
    u = _crear(db, emisor_id=emisor.id)
    assert u.password_hash.startswith("scrypt$") and PASSWORD not in u.password_hash
    assert usuarios.verificar_password(PASSWORD, u.password_hash)
    assert not usuarios.verificar_password("otra", u.password_hash)


def test_login_y_uso_de_la_sesion(db, emisor, app_client):
    _crear(db, emisor_id=emisor.id)
    r = _login(app_client)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert [e["id"] for e in yo["empresas"]] == [emisor.id]
    assert yo["es_admin"] is False

    assert app_client.post("/api/v1/facturas", json=factura_payload(), headers=h).status_code == 202
    assert app_client.get("/api/v1/emisores", headers=h).status_code == 403   # no es admin
    assert app_client.get("/api/v1/usuarios", headers=h).status_code == 403

    assert app_client.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert app_client.get("/api/v1/facturas", headers=h).status_code == 401


def test_credenciales_incorrectas_mensaje_generico(db, emisor, app_client):
    _crear(db, emisor_id=emisor.id)
    r1 = _login(app_client, password="incorrecta")
    r2 = _login(app_client, email="noexiste@x.cr")
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_bloqueo_tras_intentos_fallidos(db, emisor, app_client):
    _crear(db, emisor_id=emisor.id)
    for _ in range(5):
        _login(app_client, password="mala")
    r = _login(app_client)   # contraseña correcta, pero bloqueado
    assert r.status_code == 401 and "bloqueado" in r.json()["detail"]


def test_admin_opera_cualquier_empresa_con_x_emisor_id(db, emisor, app_client):
    otra = crear_emisor(db, numero="3101888888", nombre="Otra S.A.")
    _crear(db, email="jefe@contadores.cr", es_admin=True)
    h = _sesion(app_client, email="jefe@contadores.cr")
    assert len(app_client.get("/api/v1/auth/yo", headers=h).json()["empresas"]) == 2
    r = app_client.post("/api/v1/facturas", json=factura_payload(), headers={**h, "X-Emisor-Id": otra.id})
    assert r.status_code == 202
    assert app_client.get("/api/v1/emisores", headers=h).status_code == 200


def test_usuario_de_empresa_no_ve_otra(db, emisor, app_client):
    otra = crear_emisor(db, numero="3101888888", nombre="Otra S.A.")
    _crear(db, emisor_id=emisor.id)
    h = _sesion(app_client)
    assert app_client.get("/api/v1/facturas", headers={**h, "X-Emisor-Id": otra.id}).status_code == 403


def test_admin_gestiona_usuarios(db, emisor, admin):
    datos = {"email": "asis@x.cr", "nombre": "Asistente", "emisor_id": emisor.id}
    assert admin.post("/api/v1/usuarios", json={**datos, "password": "corta"}).status_code == 422
    r = admin.post("/api/v1/usuarios", json={**datos, "password": PASSWORD})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert admin.post("/api/v1/usuarios", json={**datos, "password": PASSWORD}).status_code == 409

    token = _login(admin, email="asis@x.cr").json()["token"]
    # Desactivar cierra sus sesiones
    assert admin.patch(f"/api/v1/usuarios/{uid}", json={"activo": False}).json()["activo"] is False
    admin.headers.pop("X-API-Key")
    assert admin.get("/api/v1/auth/yo", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_cambiar_password(db, emisor, app_client):
    _crear(db, emisor_id=emisor.id)
    h = _sesion(app_client)
    r = app_client.post("/api/v1/auth/cambiar-password", headers=h, json={"actual": "mala", "nueva": "Nueva-Clave-2026"})
    assert r.status_code == 422
    r = app_client.post("/api/v1/auth/cambiar-password", headers=h, json={"actual": PASSWORD, "nueva": "Nueva-Clave-2026"})
    assert r.status_code == 204
    assert _login(app_client).status_code == 401
    assert _login(app_client, password="Nueva-Clave-2026").status_code == 200
