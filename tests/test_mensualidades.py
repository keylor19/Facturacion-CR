"""Mensualidades: cada servicio se cobra por aparte y se factura una vez al mes."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from api.models.database import CobroMensual, Contratacion, EstadoFactura, Factura
from api.services import administracion, cobros, mensualidades, usuarios
from tests.conftest import crear_emisor

PASSWORD = "Clave-Segura-2026"


@pytest.fixture
def precios(db, monkeypatch):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "CONTROL_SUSCRIPCIONES", True)
    a = administracion.ajustes(db)
    a.precio_web_mensual, a.precio_contabilidad_mensual, a.precio_contador_mensual = Decimal("9000"), Decimal("6000"), Decimal("15000")
    a.prueba_dias, a.dias_para_pagar, a.moneda_web = 15, 10, "CRC"
    db.commit()
    return a


def _sesion(app_client, email):
    token = app_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}", "X-API-Key": ""}


def test_el_dueno_activa_la_contabilidad_al_precio_que_se_le_muestra(db, emisor, app_client, precios):
    mensualidades.contratar(db, "facturacion_web", emisor=emisor)   # el sistema en línea ya lo tiene
    usuarios.crear_usuario(db, "duena@pruebas.cr", "Dueña", PASSWORD, False, emisor.id, "dueno")
    h = _sesion(app_client, "duena@pruebas.cr")

    r = app_client.get("/api/v1/contabilidad/cuentas", headers=h)
    assert r.status_code == 403 and r.headers["X-Requiere-Servicio"] == "contabilidad" and "6,000.00" in r.json()["detail"]
    servicios = {s["servicio"]: s for s in app_client.get("/api/v1/servicios", headers=h).json()["servicios"]}
    assert set(servicios) == {"facturacion_web", "contabilidad"}
    assert servicios["contabilidad"]["precio"] == "6000.00" and servicios["contabilidad"]["activo"] is False

    c = app_client.post("/api/v1/servicios/contabilidad/contratar", headers=h)
    assert c.status_code == 201 and c.json()["precio"] == "6000.00" and c.json()["gratis_hasta"]
    assert app_client.get("/api/v1/contabilidad/cuentas", headers=h).status_code == 200
    assert app_client.post("/api/v1/servicios/contabilidad/contratar", headers=h).status_code == 409

    # Un cajero no maneja servicios
    usuarios.crear_usuario(db, "caja@pruebas.cr", "Caja", PASSWORD, False, emisor.id, "cajero")
    assert app_client.get("/api/v1/servicios", headers=_sesion(app_client, "caja@pruebas.cr")).status_code == 403


def test_el_contador_paga_su_mensualidad_y_cubre_sus_empresas(db, emisor, app_client, precios):
    from api.models.database import UsuarioEmpresa
    u = usuarios.crear_usuario(db, "conta@despacho.cr", "Conta", PASSWORD, False, None, es_contador=True)
    db.add(UsuarioEmpresa(usuario_id=u.id, emisor_id=emisor.id, rol="contador_externo"))
    db.commit()
    h = {**_sesion(app_client, "conta@despacho.cr"), "X-Emisor-Id": emisor.id}
    r = app_client.get("/api/v1/contabilidad/cuentas", headers=h)
    assert r.status_code == 403 and r.headers["X-Requiere-Servicio"] == "contador"
    assert [s["servicio"] for s in app_client.get("/api/v1/servicios", headers=h).json()["servicios"]] == ["contador"]
    assert app_client.post("/api/v1/servicios/contador/contratar", headers=h).status_code == 201
    # La empresa no paga contabilidad: la cubre la mensualidad del contador
    assert app_client.get("/api/v1/contabilidad/cuentas", headers=h).status_code == 200


def test_factura_mensual_proporcional_y_suspension_por_falta_de_pago(db, emisor, app_client, admin, precios):
    cliente = mensualidades.clave_cliente(emisor_id=emisor.id)
    # Sistema en línea desde el día 16 (15 de 30 días) y contabilidad con prueba gratis hasta el 20
    db.add_all([
        Contratacion(cliente=cliente, emisor_id=emisor.id, servicio="facturacion_web", precio=Decimal("9000"),
                     moneda="CRC", desde=date(2026, 9, 16)),
        Contratacion(cliente=cliente, emisor_id=emisor.id, servicio="contabilidad", precio=Decimal("6000"),
                     moneda="CRC", desde=date(2026, 9, 1), gratis_hasta=date(2026, 9, 20)),
    ])
    db.commit()
    creados = mensualidades.generar(db, date(2026, 9, 1))
    assert len(creados) == 1 and mensualidades.generar(db, date(2026, 9, 1)) == []   # no duplica
    cobro = creados[0]
    montos = {x["servicio"]: Decimal(x["monto"]) for x in cobro.lineas}
    assert montos == {"facturacion_web": Decimal("4500.00"), "contabilidad": Decimal("2000.00")}
    assert cobro.total == Decimal("6500.00") and cobro.vence == mensualidades.hoy() + timedelta(days=10)

    usuarios.crear_usuario(db, "duena@pruebas.cr", "Dueña", PASSWORD, False, emisor.id, "dueno")
    h = _sesion(app_client, "duena@pruebas.cr")
    assert app_client.get("/api/v1/contabilidad/cuentas", headers=h).status_code == 200
    # Vence sin pagar: se suspenden las mensualidades
    cobro.vence = mensualidades.hoy() - timedelta(days=1)
    db.commit()
    r = app_client.get("/api/v1/contabilidad/cuentas", headers=h)
    assert r.status_code == 403 and "Suspendido" in r.json()["detail"]
    facturas = app_client.get("/api/v1/servicios/facturas", headers=h).json()
    assert facturas[0]["vencido"] is True
    # Reporta el pago: se reactiva mientras se confirma
    assert app_client.post(f"/api/v1/servicios/facturas/{cobro.id}/pago", headers=h, json={"referencia": "SINPE 555"}).status_code == 200
    assert app_client.get("/api/v1/contabilidad/cuentas", headers=h).status_code == 200
    pendientes = admin.get("/api/v1/admin/mensualidades", params={"estado": "REPORTADO"}).json()
    assert [p["id"] for p in pendientes] == [cobro.id] and "Pruebas S.A." in pendientes[0]["cliente"]
    assert admin.post(f"/api/v1/admin/mensualidades/{cobro.id}/confirmar", json={}).json()["estado"] == "PAGADO"


def test_factura_electronica_de_la_mensualidad_y_su_pago(db, emisor, admin, precios):
    # La plataforma factura desde su propia empresa; el cliente es otra empresa
    precios.emisor_ventas_id, precios.codigo_cabys = emisor.id, "8314100000000"
    db.commit()
    cliente = crear_emisor(db, numero="3101555666", nombre="Cliente Mensual S.A.")
    mensualidades.contratar(db, "facturacion_web", emisor=cliente)
    c = db.query(Contratacion).filter_by(emisor_id=cliente.id).one()
    c.desde, c.gratis_hasta = date(2026, 9, 1), None
    db.commit()
    cobro = mensualidades.generar(db, date(2026, 9, 1))[0]
    factura = mensualidades.emitir_comprobante(db, cobro)
    assert factura is not None and factura.condicion_venta == "02" and factura.receptor_identificacion == "3101555666"
    assert Decimal(factura.monto_total) == Decimal("9000.00")   # precio con IVA incluido
    factura.estado = EstadoFactura.ACEPTADO
    db.commit()
    assert admin.post(f"/api/v1/admin/mensualidades/{cobro.id}/confirmar", json={"referencia": "TRF-9"}).status_code == 200
    assert cobros.saldo_factura(db, db.get(Factura, factura.id)) == 0   # el pago quedó como abono


def test_al_inscribirse_queda_contratado_el_sistema_en_linea_con_su_prueba(db, app_client, precios, monkeypatch):
    from api.services import hacienda_publico
    monkeypatch.setattr(hacienda_publico, "contribuyente", lambda c: {
        "nombre": "LA ESPIGA S.A.", "tipoIdentificacion": "02", "situacion": {"estado": "Inscrito"},
        "actividades": [{"codigo": 107101, "tipo": "P", "estado": "A"}]})
    usuarios.crear_usuario(db, "ana@espiga.cr", "Ana", PASSWORD, False, None)
    h = _sesion(app_client, "ana@espiga.cr")
    r = app_client.post("/api/v1/registro/empresa", headers=h, json={
        "tipo_identificacion": "02", "numero_identificacion": "3101777777", "nombre": "La Espiga", "codigo_actividad": "107101",
        "correo": "info@espiga.cr", "provincia": "1", "canton": "01", "distrito": "01", "otras_senas": "Centro"})
    assert r.status_code == 201, r.text
    c = db.query(Contratacion).filter_by(emisor_id=r.json()["id"], servicio="facturacion_web").one()
    assert c.precio == Decimal("9000.00") and c.gratis_hasta == mensualidades.hoy() + timedelta(days=14)
    assert db.query(CobroMensual).count() == 0
