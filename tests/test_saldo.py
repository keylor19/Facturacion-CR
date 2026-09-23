"""Venta por consumo: saldo de documentos, paquetes, planes y límites de uso."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from api.models.database import Consumo, Factura, EstadoFactura, Paquete, utcnow
from api.security import crear_api_key
from api.services import saldo
from tests.conftest import crear_emisor, factura_payload


@pytest.fixture
def sin_saldo(db, app_client):
    """Empresa sin paquetes y un cliente autenticado con su llave."""
    emisor = crear_emisor(db, numero="3101555555", nombre="Sin Saldo S.A.", documentos=0)
    _, llave = crear_api_key(db, "POS", False, emisor.id)
    app_client.headers["X-API-Key"] = llave
    return emisor, app_client


def _consumos(db, emisor):
    return db.query(Consumo).filter(Consumo.emisor_id == emisor.id).count()


def test_sin_paquete_no_se_puede_emitir(sin_saldo, db):
    emisor, c = sin_saldo
    r = c.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 402
    assert "agotado" in r.json()["detail"]
    assert db.query(Factura).count() == 0


def test_cada_emision_consume_un_documento(sin_saldo, db):
    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=3)
    r = c.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 202
    assert r.headers["X-Documentos-Disponibles"] == "2"
    assert c.get("/api/v1/saldo").json()["disponible"] == 2
    movs = c.get("/api/v1/saldo/movimientos").json()
    assert len(movs) == 1 and movs[0]["referencia"] == r.json()["clave"]


def test_idempotencia_y_reenvio_no_cobran_dos_veces(sin_saldo, db):
    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=5)
    r1 = c.post("/api/v1/facturas", json=factura_payload(referencia_externa="POS-1"))
    r2 = c.post("/api/v1/facturas", json=factura_payload(referencia_externa="POS-1"))
    assert r2.status_code == 200
    c.post(f"/api/v1/facturas/{r1.json()['factura_id']}/reenviar")
    assert saldo.disponible(db, emisor.id) == 4


def test_emision_fallida_no_cobra(sin_saldo, db):
    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=5)
    malos_medios = [{"tipo": "01", "monto": "1"}, {"tipo": "02", "monto": "1"}]   # no suman el total
    assert c.post("/api/v1/facturas", json=factura_payload(medios_pago=malos_medios)).status_code == 422
    assert saldo.disponible(db, emisor.id) == 5 and _consumos(db, emisor) == 0


def test_rechazo_de_hacienda_no_devuelve_credito(sin_saldo, db):
    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=2)
    fid = c.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    db.get(Factura, fid).estado = EstadoFactura.RECHAZADO
    db.commit()
    assert saldo.disponible(db, emisor.id) == 1


def test_se_consume_primero_el_paquete_que_vence_antes(sin_saldo, db):
    emisor, c = sin_saldo
    sin_vencimiento = saldo.acreditar(db, emisor, documentos=10, nombre="Anual")
    vence_pronto = saldo.acreditar(db, emisor, documentos=10, dias_vigencia=5, nombre="Promo")
    c.post("/api/v1/facturas", json=factura_payload())
    db.expire_all()
    assert db.get(Paquete, vence_pronto.id).usados == 1
    assert db.get(Paquete, sin_vencimiento.id).usados == 0


def test_paquetes_vencidos_y_anulados_no_cuentan(sin_saldo, db, admin):
    emisor, c = sin_saldo
    vencido = saldo.acreditar(db, emisor, documentos=10)
    vencido.vence = utcnow() - timedelta(days=1)
    db.commit()
    assert c.post("/api/v1/facturas", json=factura_payload()).status_code == 402

    vigente = saldo.acreditar(db, emisor, documentos=10)
    assert admin.post(f"/api/v1/paquetes/{vigente.id}/anular").json()["estado"] == "ANULADO"
    assert saldo.disponible(db, emisor.id) == 0


def test_concurrencia_no_vende_mas_de_lo_comprado(sin_saldo, db):
    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=5)

    def emitir(_):
        return c.post("/api/v1/facturas", json=factura_payload()).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codigos = list(pool.map(emitir, range(12)))
    assert codigos.count(202) == 5
    assert codigos.count(402) == 7
    assert saldo.disponible(db, emisor.id) == 0 and _consumos(db, emisor) == 5


def test_mensaje_receptor_y_nota_de_credito_consumen(sin_saldo, db):
    from tests.test_recepcion import xml_de_proveedor

    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=10)
    xml = xml_de_proveedor(receptor_numero="3101555555")
    doc = c.post("/api/v1/recepcion", json={"xml_base64": base64.b64encode(xml).decode()}).json()
    assert saldo.disponible(db, emisor.id) == 10                  # registrar es gratis
    r = c.post(f"/api/v1/recepcion/{doc['id']}/mensaje", json={"mensaje": "1", "condicion_impuesto": "01"})
    assert r.status_code == 202 and r.headers["X-Documentos-Disponibles"] == "9"

    fid = c.post("/api/v1/facturas", json=factura_payload()).json()["factura_id"]
    db.get(Factura, fid).estado = EstadoFactura.ACEPTADO
    db.commit()
    assert c.post(f"/api/v1/facturas/{fid}/anular", json={"razon": "x"}).status_code == 202
    assert saldo.disponible(db, emisor.id) == 7


def test_aviso_de_saldo_bajo_y_agotado(sin_saldo, db, cola, monkeypatch):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "SALDO_ALERTA_DOCUMENTOS", 1)
    emisor, c = sin_saldo
    saldo.acreditar(db, emisor, documentos=2)
    c.post("/api/v1/facturas", json=factura_payload())
    c.post("/api/v1/facturas", json=factura_payload())
    eventos = [a[1] for n, a in cola if n == "notificar_saldo"]
    assert eventos == ["saldo.bajo", "saldo.agotado"]


def test_admin_vende_paquete_desde_plan_y_ve_ventas(admin, db):
    emisor = crear_emisor(db, numero="3101666666", nombre="Cliente S.A.", documentos=0)
    plan = admin.post("/api/v1/planes", json={"nombre": "Pyme 500", "documentos": 500, "precio": "15000",
                                               "dias_vigencia": 365}).json()
    r = admin.post(f"/api/v1/emisores/{emisor.id}/paquetes",
                   json={"plan_id": plan["id"], "referencia_pago": "SINPE 12345678"})
    assert r.status_code == 201, r.text
    assert r.json()["disponible"] == 500
    assert r.json()["paquete"]["vence"] is not None

    cortesia = admin.post(f"/api/v1/emisores/{emisor.id}/paquetes", json={"documentos": 20, "nombre": "Cortesía"})
    assert cortesia.json()["disponible"] == 520

    hoy = utcnow()
    ventas = admin.get(f"/api/v1/admin/ventas?anio={hoy.year}&mes={hoy.month}").json()
    assert ventas["ingresos"]["CRC"] == "15000.00"
    assert len(ventas["paquetes_vendidos"]) == 2

    emisores = admin.get("/api/v1/emisores").json()
    assert [e["saldo_documentos"] for e in emisores if e["id"] == emisor.id] == [520]


def test_cliente_no_administra_paquetes(client, emisor):
    assert client.post(f"/api/v1/emisores/{emisor.id}/paquetes", json={"documentos": 1000}).status_code == 403
    assert client.get("/api/v1/planes").status_code == 403
    assert client.get("/api/v1/saldo").status_code == 200


def test_control_de_saldo_desactivable(sin_saldo, monkeypatch):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(), "CONTROL_SALDO", False)
    _, c = sin_saldo
    r = c.post("/api/v1/facturas", json=factura_payload())
    assert r.status_code == 202 and "X-Documentos-Disponibles" not in r.headers


def test_limite_de_solicitudes(client, monkeypatch):
    from api.services import limites
    monkeypatch.setattr(limites, "contar", lambda clave, ventana=60: (10_000, 30))
    r = client.get("/api/v1/facturas")
    assert r.status_code == 429 and r.headers["Retry-After"] == "30"
