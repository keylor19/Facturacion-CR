"""Servicios por empresa: la conexión por API se paga solo con documentos; el panel web tiene mensualidad."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.models.database import Suscripcion
from api.services import suscripciones, usuarios
from tests.conftest import factura_payload

CLAVE = "Clave-Segura-2026"


@pytest.fixture
def control(monkeypatch):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "CONTROL_SUSCRIPCIONES", True)


@pytest.fixture
def clientes(db, emisor, api_key, cola):
    """Sistema del cliente (API key) y usuario del panel de la misma empresa."""
    from api.main import app
    usuarios.crear_usuario(db, "cajera@empresa.cr", "Cajera", CLAVE, False, emisor.id)
    sistema = TestClient(app, headers={"X-API-Key": api_key})
    panel = TestClient(app)
    token = panel.post("/api/v1/auth/login", json={"email": "cajera@empresa.cr", "password": CLAVE}).json()["token"]
    panel.headers["Authorization"] = f"Bearer {token}"
    return sistema, panel


def _vender(admin, emisor, servicio, meses=1, precio="15000", **extra):
    r = admin.post(f"/api/v1/emisores/{emisor.id}/suscripciones",
                   json={"servicio": servicio, "meses": meses, "precio": precio, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_sumar_meses_ajusta_fin_de_mes():
    d = datetime(2026, 1, 31, 10, tzinfo=timezone.utc)
    assert suscripciones.sumar_meses(d, 1) == datetime(2026, 2, 28, 10, tzinfo=timezone.utc)
    assert suscripciones.sumar_meses(d, 12) == datetime(2027, 1, 31, 10, tzinfo=timezone.utc)
    assert suscripciones.sumar_meses(datetime(2026, 11, 15, tzinfo=timezone.utc), 3).month == 2


def test_sin_control_todo_funciona_como_antes(clientes):
    sistema, panel = clientes
    assert sistema.post("/api/v1/facturas", json=factura_payload()).status_code == 202
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 202


def test_api_se_paga_solo_con_documentos(control, clientes, admin, emisor):
    """Quien se conecta por API no paga mensualidad: le basta con tener documentos."""
    sistema, panel = clientes
    assert sistema.post("/api/v1/facturas", json=factura_payload()).status_code == 202
    servicios = {s["servicio"]: s for s in admin.get(f"/api/v1/emisores/{emisor.id}/suscripciones").json()["servicios"]}
    assert servicios["api"]["estado"] == "ACTIVO" and servicios["api"]["con_mensualidad"] is False
    # La conexión por API ya no se vende como mensualidad
    r = admin.post(f"/api/v1/emisores/{emisor.id}/suscripciones", json={"servicio": "api", "precio": "1000"})
    assert r.status_code == 422


def test_panel_web_sin_contratar_no_funciona(control, clientes):
    _, panel = clientes
    r = panel.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 403 and "panel web" in r.json()["detail"]
    assert panel.get("/api/v1/auth/yo").json()["empresas"][0]["facturacion_web"] is False
    # El panel web es un servicio adicional: sin él no hay acceso a los datos desde el panel
    assert panel.get("/api/v1/facturas").status_code == 403
    assert panel.get("/api/v1/saldo").status_code == 403


def test_panel_web_se_cobra_aparte(control, clientes, admin, emisor):
    sistema, panel = clientes
    assert sistema.post("/api/v1/facturas", json=factura_payload()).status_code == 202
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 403
    _vender(admin, emisor, "facturacion_web", precio="10000", referencia_pago="SINPE 123")
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 202
    assert panel.get("/api/v1/auth/yo").json()["empresas"][0]["facturacion_web"] is True
    servicios = {s["servicio"]: s for s in panel.get("/api/v1/saldo").json()["servicios"]}
    assert servicios["api"]["estado"] == "ACTIVO" and servicios["facturacion_web"]["activo"] is True


def test_vencimiento_gracia_y_corte(db, control, clientes, admin, emisor):
    _, panel = clientes
    _vender(admin, emisor, "facturacion_web")
    sus = db.query(Suscripcion).one()
    ahora = datetime.now(timezone.utc)

    sus.hasta = ahora + timedelta(days=2)          # por vencer
    db.commit()
    assert suscripciones.estado(db, emisor, "facturacion_web")["estado"] == "POR_VENCER"
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 202

    sus.hasta = ahora - timedelta(days=1)          # vencida, pero en los días de gracia
    db.commit()
    assert suscripciones.estado(db, emisor, "facturacion_web")["estado"] == "EN_GRACIA"
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 202

    sus.hasta = ahora - timedelta(days=5)          # pasó la gracia: se corta
    db.commit()
    r = panel.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 403 and "venció" in r.json()["detail"]

    # Al renovar vuelve a funcionar de inmediato
    _vender(admin, emisor, "facturacion_web")
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 202


def test_renovar_antes_de_vencer_extiende_el_periodo(db, control, admin, emisor):
    primera = _vender(admin, emisor, "facturacion_web", meses=1)["suscripcion"]
    segunda = _vender(admin, emisor, "facturacion_web", meses=3)["suscripcion"]
    assert segunda["desde"] == primera["hasta"]
    assert segunda["estado"] == "PROGRAMADA"
    fin = datetime.fromisoformat(segunda["hasta"])
    assert 115 <= (fin - datetime.now(timezone.utc)).days <= 125


def test_anular_cobro(db, control, clientes, admin, emisor):
    _, panel = clientes
    sus = _vender(admin, emisor, "facturacion_web")["suscripcion"]
    assert admin.post(f"/api/v1/suscripciones/{sus['id']}/anular").json()["estado"] == "ANULADA"
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 403


def test_casilla_deshabilitada_corta(control, clientes, admin, emisor):
    sistema, panel = clientes
    admin.patch(f"/api/v1/emisores/{emisor.id}", json={"acceso_api": False})
    r = sistema.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 403 and "conexión por API" in r.json()["detail"]
    # El panel pagado también se corta si se desmarca su casilla
    _vender(admin, emisor, "facturacion_web")
    admin.patch(f"/api/v1/emisores/{emisor.id}", json={"facturacion_web": False})
    assert panel.post("/api/v1/facturas", json=factura_payload()).status_code == 403


def test_administrador_no_depende_de_suscripciones(control, admin, emisor):
    r = admin.post("/api/v1/facturas", json=factura_payload(), headers={"X-Emisor-Id": emisor.id})
    assert r.status_code == 202


def test_ingresos_del_mes_separan_documentos_y_servicios(control, admin, emisor):
    admin.post(f"/api/v1/emisores/{emisor.id}/paquetes", json={"documentos": 500, "precio": "20000"})
    _vender(admin, emisor, "facturacion_web", precio="15000")
    _vender(admin, emisor, "facturacion_web", meses=12, precio="100000", moneda="CRC")
    hoy = datetime.now(timezone(timedelta(hours=-6)))
    r = admin.get("/api/v1/admin/ventas", params={"anio": hoy.year, "mes": hoy.month}).json()
    assert r["ingresos_servicios"] == {"CRC": "115000.00"}
    assert r["ingresos"]["CRC"] == "135000.00"
    assert {s["servicio"] for s in r["servicios_vendidos"]} == {"facturacion_web"}
    acciones = {a["accion"] for a in admin.get("/api/v1/admin/auditoria").json()}
    assert "suscripcion.vender" in acciones


def test_solo_administradores_venden_servicios(control, clientes, emisor):
    sistema, panel = clientes
    for c in (sistema, panel):
        r = c.post(f"/api/v1/emisores/{emisor.id}/suscripciones", json={"servicio": "facturacion_web", "precio": "0"})
        assert r.status_code == 403


def test_aviso_de_vencimiento(db, control, admin, emisor, monkeypatch):
    from workers import tasks
    enviados = []
    monkeypatch.setattr(tasks.notificar_saldo, "delay", lambda *a: enviados.append(a))
    _vender(admin, emisor, "facturacion_web")
    sus = db.query(Suscripcion).one()
    sus.hasta = datetime.now(timezone.utc) + timedelta(days=3)
    db.commit()
    assert tasks.revisar_suscripciones()["avisos"] == 1
    assert enviados[0][1] == "suscripcion.por_vencer" and enviados[0][2]["servicio"] == "panel web"
