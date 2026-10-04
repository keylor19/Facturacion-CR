"""
Pruebas de seguridad: aislamiento entre empresas, verificación en dos pasos,
bitácora, SSRF de webhooks, inyección CSV, límites y configuración de producción.
"""
import socket

import pytest
from fastapi.testclient import TestClient

from api.services import dos_pasos, usuarios
from tests.conftest import ADMIN_KEY, crear_emisor, factura_payload
from tests.test_recepcion import _registrar, xml_de_proveedor

PASSWORD = "Clave-Segura-2026"


# --- Aislamiento entre empresas ----------------------------------------------

@pytest.fixture
def dos_empresas(db, cola):
    """Empresa A con un comprobante emitido y uno recibido; empresa B con su propia llave."""
    from api.main import app
    from api.security import crear_api_key

    a = crear_emisor(db, numero="3101123456", nombre="Empresa A")
    b = crear_emisor(db, numero="3101654321", nombre="Empresa B")
    _, llave_a = crear_api_key(db, "POS A", False, a.id)
    _, llave_b = crear_api_key(db, "POS B", False, b.id)
    with TestClient(app) as ca, TestClient(app) as cb:
        ca.headers["X-API-Key"] = llave_a
        cb.headers["X-API-Key"] = llave_b
        factura_id = ca.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
        doc_id = _registrar(ca, xml_de_proveedor()).json()["id"]
        yield {"a": a, "b": b, "ca": ca, "cb": cb, "factura_id": factura_id, "doc_id": doc_id}


def test_otra_empresa_no_ve_ni_opera_documentos_ajenos(dos_empresas):
    cb, fid, did = dos_empresas["cb"], dos_empresas["factura_id"], dos_empresas["doc_id"]
    for metodo, ruta in [
        ("get", f"/api/v1/facturas/{fid}"),
        ("get", f"/api/v1/facturas/{fid}/eventos"),
        ("get", f"/api/v1/facturas/{fid}/xml"),
        ("get", f"/api/v1/facturas/{fid}/pdf"),
        ("get", f"/api/v1/facturas/{fid}/pagos"),
        ("post", f"/api/v1/facturas/{fid}/anular"),
        ("post", f"/api/v1/facturas/{fid}/reenviar"),
        ("post", f"/api/v1/facturas/{fid}/consultar"),
        ("post", f"/api/v1/facturas/{fid}/correo"),
        ("get", f"/api/v1/recepcion/{did}"),
        ("get", f"/api/v1/recepcion/{did}/eventos"),
        ("get", f"/api/v1/recepcion/{did}/xml"),
        ("post", f"/api/v1/recepcion/{did}/reenviar"),
    ]:
        r = getattr(cb, metodo)(ruta)
        assert r.status_code in (404, 422), f"{metodo.upper()} {ruta} -> {r.status_code}"
    r = cb.post(f"/api/v1/recepcion/{did}/mensaje", json={"mensaje": "1"})
    assert r.status_code in (404, 422)
    assert cb.get("/api/v1/facturas").json() == []
    assert cb.get("/api/v1/recepcion").json() == []


def test_llave_de_empresa_no_puede_cambiar_de_empresa_ni_administrar(dos_empresas):
    cb, a = dos_empresas["cb"], dos_empresas["a"]
    assert cb.get("/api/v1/facturas", headers={"X-Emisor-Id": a.id}).status_code == 403
    assert cb.get("/api/v1/saldo", headers={"X-Emisor-Id": a.id}).status_code == 403
    for metodo, ruta in [
        ("get", "/api/v1/emisores"), ("get", f"/api/v1/emisores/{a.id}"), ("get", "/api/v1/api-keys"),
        ("post", "/api/v1/api-keys"), ("get", "/api/v1/usuarios"), ("get", "/api/v1/admin/auditoria"),
        ("get", f"/api/v1/emisores/{a.id}/paquetes"), ("get", "/api/v1/planes"),
    ]:
        r = getattr(cb, metodo)(ruta, **({"json": {"nombre": "x"}} if metodo == "post" else {}))
        assert r.status_code == 403, f"{metodo.upper()} {ruta} -> {r.status_code}"


def test_usuario_de_empresa_solo_ve_su_empresa(db, dos_empresas, app_client):
    usuarios.crear_usuario(db, "b@empresa.cr", "B", PASSWORD, False, dos_empresas["b"].id)
    token = app_client.post("/api/v1/auth/login", json={"email": "b@empresa.cr", "password": PASSWORD}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert [e["id"] for e in yo["empresas"]] == [dos_empresas["b"].id]
    assert app_client.get(f"/api/v1/facturas/{dos_empresas['factura_id']}", headers=h).status_code == 404
    assert app_client.get("/api/v1/facturas", headers={**h, "X-Emisor-Id": dos_empresas["a"].id}).status_code == 403


def test_llave_revocada_deja_de_funcionar(db, dos_empresas, admin):
    lista = admin.get("/api/v1/api-keys", params={"emisor_id": dos_empresas["b"].id}).json()
    assert admin.delete(f"/api/v1/api-keys/{lista[0]['id']}").status_code == 204
    assert dos_empresas["cb"].get("/api/v1/facturas").status_code == 401


# --- Verificación en dos pasos (TOTP) ----------------------------------------

def test_totp_vector_rfc6238():
    import base64
    secreto = base64.b32encode(b"12345678901234567890").decode()
    assert dos_pasos._codigo(secreto, 59 // 30) == "287082"
    assert dos_pasos.verificar(secreto, "287082", None, ahora=59) == 1
    assert dos_pasos.verificar(secreto, "287082", 1, ahora=59) is None   # no se reutiliza
    assert dos_pasos.verificar(secreto, "28708", None, ahora=59) is None
    assert dos_pasos.verificar(secreto, "abcdef", None, ahora=59) is None


def test_qr_es_svg():
    svg = dos_pasos.qr_svg(dos_pasos.uri(dos_pasos.generar_secreto(), "ana@x.cr"))
    assert "<svg" in svg and "<script" not in svg


def _codigo_actual(secreto, desfase=0):
    return dos_pasos._codigo(secreto, dos_pasos.paso_actual() + desfase)


def _login(c, codigo=None, email="admin@contadores.cr"):
    body = {"email": email, "password": PASSWORD}
    if codigo:
        body["codigo"] = codigo
    return c.post("/api/v1/auth/login", json=body)


def test_activar_2fa_y_login_con_codigo(db, app_client):
    usuarios.crear_usuario(db, "admin@contadores.cr", "Admin", PASSWORD, True, None)
    h = {"Authorization": f"Bearer {_login(app_client).json()['token']}"}

    r = app_client.post("/api/v1/auth/2fa/iniciar", headers=h)
    assert r.status_code == 200 and r.json()["uri"].startswith("otpauth://totp/")
    secreto = r.json()["secreto"]
    assert app_client.post("/api/v1/auth/2fa/activar", json={"codigo": "000000"}, headers=h).status_code == 422
    assert app_client.post("/api/v1/auth/2fa/activar", json={"codigo": _codigo_actual(secreto)}, headers=h).status_code == 204
    assert app_client.get("/api/v1/auth/yo", headers=h).json()["usuario"]["dos_pasos"] is True

    # Sin código: 401 con aviso para el panel
    r = _login(app_client)
    assert r.status_code == 401 and r.headers["X-Requiere-2FA"] == "codigo"
    # Código incorrecto
    assert _login(app_client, "123456").status_code == 401
    # El código usado para activar no sirve de nuevo; el siguiente sí
    assert _login(app_client, _codigo_actual(secreto, 1)).status_code == 200
    assert _login(app_client, _codigo_actual(secreto, 1)).status_code == 401   # reutilizado


def test_codigos_fallidos_bloquean_la_cuenta(db, app_client):
    u = usuarios.crear_usuario(db, "admin@contadores.cr", "Admin", PASSWORD, True, None)
    secreto = usuarios.iniciar_2fa(db, u)
    usuarios.activar_2fa(db, u, _codigo_actual(secreto))
    for _ in range(5):
        _login(app_client, "000000")
    r = _login(app_client, _codigo_actual(secreto, 1))
    assert r.status_code == 401 and "bloqueado" in r.json()["detail"]


def test_admin_sin_2fa_bloqueado_si_es_obligatorio(db, app_client, monkeypatch):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "EXIGIR_2FA_ADMIN", True)
    usuarios.crear_usuario(db, "admin@contadores.cr", "Admin", PASSWORD, True, None)
    h = {"Authorization": f"Bearer {_login(app_client).json()['token']}"}

    r = app_client.get("/api/v1/emisores", headers=h)
    assert r.status_code == 403 and r.headers["X-Requiere-2FA"] == "activar"
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["debe_activar_2fa"] is True and yo["empresas"] == []

    secreto = app_client.post("/api/v1/auth/2fa/iniciar", headers=h).json()["secreto"]
    app_client.post("/api/v1/auth/2fa/activar", json={"codigo": _codigo_actual(secreto)}, headers=h)
    assert app_client.get("/api/v1/emisores", headers=h).status_code == 200
    # Un administrador no puede quitársela si es obligatoria
    r = app_client.post("/api/v1/auth/2fa/desactivar", headers=h,
                        json={"password": PASSWORD, "codigo": _codigo_actual(secreto, 1)})
    assert r.status_code == 409


def test_2fa_obligatoria_por_defecto_solo_en_produccion():
    from config.settings import Settings
    assert Settings().exige_2fa_admin is False   # pruebas (stag)
    assert Settings(EXIGIR_2FA_ADMIN=True).exige_2fa_admin is True
    assert Settings(EXIGIR_2FA_ADMIN="").exige_2fa_admin is False   # vacío en .env = valor por defecto


def test_usuario_de_empresa_puede_desactivar_su_2fa(db, emisor, app_client):
    u = usuarios.crear_usuario(db, "ana@empresa.cr", "Ana", PASSWORD, False, emisor.id)
    secreto = usuarios.iniciar_2fa(db, u)
    usuarios.activar_2fa(db, u, _codigo_actual(secreto, -1))
    token = _login(app_client, _codigo_actual(secreto), email="ana@empresa.cr").json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    r = app_client.post("/api/v1/auth/2fa/desactivar", headers=h, json={"password": "mala", "codigo": _codigo_actual(secreto, 1)})
    assert r.status_code == 422
    r = app_client.post("/api/v1/auth/2fa/desactivar", headers=h, json={"password": PASSWORD, "codigo": _codigo_actual(secreto, 1)})
    assert r.status_code == 204
    assert _login(app_client, email="ana@empresa.cr").status_code == 200


def test_admin_reinicia_2fa_y_cierra_sesiones(db, emisor, app_client, admin):
    u = usuarios.crear_usuario(db, "ana@empresa.cr", "Ana", PASSWORD, False, emisor.id)
    secreto = usuarios.iniciar_2fa(db, u)
    usuarios.activar_2fa(db, u, _codigo_actual(secreto))
    token = _login(app_client, _codigo_actual(secreto, 1), email="ana@empresa.cr").json()["token"]

    assert admin.delete(f"/api/v1/usuarios/{u.id}/2fa").status_code == 204
    assert app_client.get("/api/v1/auth/yo", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert _login(app_client, email="ana@empresa.cr").status_code == 200


def test_secreto_totp_se_guarda_cifrado(db):
    u = usuarios.crear_usuario(db, "ana@x.cr", "Ana", PASSWORD, False, None)
    secreto = usuarios.iniciar_2fa(db, u)
    assert secreto.encode() not in bytes(u.totp_secreto_cifrado)


# --- Bitácora -------------------------------------------------------------------

def test_bitacora_registra_acciones_sensibles(db, admin, emisor):
    from tests.test_admin import EMISOR
    nuevo = admin.post("/api/v1/emisores", json={**EMISOR, "numero_identificacion": "3101999999"}).json()
    admin.post("/api/v1/api-keys", json={"nombre": "ERP", "emisor_id": nuevo["id"]})
    admin.put(f"/api/v1/emisores/{nuevo['id']}/credenciales-hacienda",
              json={"usuario": "cpj@stag.comprobanteselectronicos.go.cr", "password": "NoDebeVerse-123"})
    admin.post(f"/api/v1/emisores/{nuevo['id']}/paquetes", json={"documentos": 500, "precio": 10000})

    registros = admin.get("/api/v1/admin/auditoria").json()
    acciones = {r["accion"] for r in registros}
    assert {"emisor.crear", "llave.crear", "emisor.credenciales_hacienda", "paquete.vender"} <= acciones
    assert all(r["actor"] == "llave de administrador (.env)" for r in registros)
    assert "NoDebeVerse" not in str(registros)   # nunca se guardan secretos
    solo_llaves = admin.get("/api/v1/admin/auditoria", params={"accion": "llave."}).json()
    assert {r["accion"] for r in solo_llaves} == {"llave.crear"}


def test_bitacora_registra_login_con_nombre_de_usuario(db, app_client, admin):
    usuarios.crear_usuario(db, "ana@contadores.cr", "Ana", PASSWORD, True, None)
    _login(app_client, email="ana@contadores.cr")
    r = admin.get("/api/v1/admin/auditoria", params={"accion": "login"}).json()
    assert r[0]["actor"] == "usuario:ana@contadores.cr" and r[0]["ip"]


# --- Webhooks: sin acceso a la red interna (SSRF) ------------------------------

@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "172.17.0.2", "192.168.1.1", "169.254.169.254", "::1", "fd00::1"])
def test_webhook_no_puede_apuntar_a_red_interna(monkeypatch, ip):
    from api.services import webhooks
    familia = socket.AF_INET6 if ":" in ip else socket.AF_INET
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(familia, 1, 6, "", (ip, 443))])
    assert webhooks.destino_permitido("https://interno.ejemplo.com/hook") is False


def test_webhook_publico_permitido(monkeypatch):
    from api.services import webhooks
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 443))])
    assert webhooks.destino_permitido("https://erp.ejemplo.com/hook") is True
    assert webhooks.destino_permitido("http://erp.ejemplo.com/hook") is False


def test_api_rechaza_webhook_interno(admin, emisor, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("10.0.0.5", 443))])
    r = admin.put(f"/api/v1/emisores/{emisor.id}/webhook", json={"url": "https://interno.ejemplo.com/hook"})
    assert r.status_code == 422


# --- Inyección de fórmulas en CSV ----------------------------------------------

def test_csv_neutraliza_formulas():
    from api.services.reportes import _csv
    contenido = _csv(["nombre", "monto"], [["=HYPERLINK(\"http://malo\")", 10], ["+1+1", 5], ["Normal", -3]])
    assert "'=HYPERLINK" in contenido and "'+1+1" in contenido
    assert ";-3" in contenido   # los números negativos no se alteran


# --- Autenticación ----------------------------------------------------------------

def test_fallos_de_autenticacion_limitados_por_ip(app_client, monkeypatch):
    from api.services import limites
    claves = []

    def contar(clave, ventana=60):
        claves.append(clave)
        return (1000, 30) if clave.startswith("fallo-auth:") else (1, 30)
    monkeypatch.setattr(limites, "contar", contar)
    r = app_client.get("/api/v1/facturas", headers={"X-API-Key": "fcr_inventada"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert any(c.startswith("fallo-auth:") for c in claves)


def test_sin_credenciales_no_hay_acceso(app_client):
    for ruta in ["/api/v1/facturas", "/api/v1/recepcion", "/api/v1/emisores", "/api/v1/usuarios",
                 "/api/v1/saldo", "/api/v1/admin/auditoria", "/api/v1/reportes/estadisticas"]:
        assert app_client.get(ruta).status_code == 401, ruta
    assert app_client.get("/api/v1/facturas", headers={"Authorization": "Bearer ses_falso"}).status_code == 401


# --- Configuración de producción -----------------------------------------------

def _prod(**cambios):
    from cryptography.fernet import Fernet
    from config.settings import Settings
    base = dict(
        AMBIENTE="prod", MASTER_KEY=Fernet.generate_key().decode(),
        DATABASE_URL="postgresql+psycopg2://facturacion:Una-Clave-Larga-De-Verdad@db:5432/facturacion",
        CALLBACK_BASE_URL="https://facturas.miempresa.cr", CALLBACK_TOKEN="x" * 40,
        API_KEYS="k" * 40, CORS_ORIGINS="https://panel.miempresa.cr",
    )
    base.update(cambios)
    return Settings(**base)


def test_produccion_valida_configuracion_segura():
    assert _prod().exige_2fa_admin is True
    for cambios, texto in [
        ({"MASTER_KEY": "corta"}, "MASTER_KEY"),
        ({"DATABASE_URL": "postgresql+psycopg2://facturacion:facturacion@db:5432/facturacion"}, "base de datos"),
        ({"CALLBACK_TOKEN": "corto"}, "CALLBACK_TOKEN"),
        ({"API_KEYS": "corta"}, "API_KEYS"),
        ({"CORS_ORIGINS": "*"}, "CORS"),
        ({"CALLBACK_BASE_URL": "http://facturas.miempresa.cr"}, "CALLBACK_BASE_URL"),
    ]:
        with pytest.raises(ValueError, match=texto):
            _prod(**cambios)


def test_login_inexistente_y_bloqueado_mismo_mensaje(db, emisor, app_client):
    usuarios.crear_usuario(db, "ana@contadores.cr", "Ana", PASSWORD, False, emisor.id)
    for _ in range(5):
        app_client.post("/api/v1/auth/login", json={"email": "ana@contadores.cr", "password": "mala"})
    bloqueado = app_client.post("/api/v1/auth/login", json={"email": "ana@contadores.cr", "password": "otra-mala"})
    inexistente = app_client.post("/api/v1/auth/login", json={"email": "nadie@contadores.cr", "password": "otra-mala"})
    assert bloqueado.json()["detail"] == inexistente.json()["detail"]
